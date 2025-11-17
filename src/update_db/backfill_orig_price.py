#!/usr/bin/env python3
"""
backfill_orig_price.py – дозаполняет orig_price в таблице skis
на основе всех CSV-файлов skis_unified*.csv.

По умолчанию:
    DB:       <корень>/data/db/skis.db
    CSV dir:  <корень>/data/exports
    LOGS:     <корень>/logs/db_backfill_YYYY-MM-DD.log

Логика:
    - читаем все skis_unified*.csv
    - для строк с НЕпустым orig_price ищем соответствующие записи в skis
      (по shop_code, url, length_cm, condition)
    - если в БД orig_price IS NULL — записываем значение
"""

import csv
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional, Dict, Tuple, Any
import logging


# ──────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "db" / "skis.db"
DEFAULT_CSV_DIR = ROOT_DIR / "data" / "exports"
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / f"db_backfill_{datetime.now().strftime('%Y-%m-%d')}.log"


# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    encoding="utf-8",
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(console)


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_float(value: str) -> Optional[float]:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    v = v.replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────
# MAIN LOGIC
# ──────────────────────────────────────────────────────────────

def load_ski_index(conn: sqlite3.Connection) -> Dict[Tuple[str, str, Optional[float], str], Tuple[int, Optional[float]]]:
    """
    Загружает все лыжи из БД и строит индекс:
        key = (shop_code, url, length_cm, condition)
        value = (ski_id, orig_price)
    """
    sql = """
        SELECT s.id,
               s.orig_price,
               s.length_cm,
               s.condition,
               s.url,
               sh.code
        FROM skis s
        JOIN shops sh ON sh.id = s.shop_id
    """
    cur = conn.execute(sql)

    index: Dict[Tuple[str, str, Optional[float], str], Tuple[int, Optional[float]]] = {}
    for ski_id, orig_price, length_cm, condition, url, shop_code in cur.fetchall():
        key = (
            (shop_code or "").strip(),
            (url or "").strip(),
            float(length_cm) if length_cm is not None else None,
            (condition or "new").strip(),
        )
        index[key] = (ski_id, orig_price)

    logging.info(f"Loaded {len(index)} skis from DB into index")
    return index


def backfill_from_csvs(
    conn: sqlite3.Connection,
    csv_dir: Path,
) -> None:
    """
    Проходит по всем skis_unified*.csv, собирает orig_price
    и обновляет только те skis, где orig_price IS NULL.
    """
    files = sorted(f for f in csv_dir.glob("skis_unified*.csv") if f.is_file())
    if not files:
        logging.info(f"No CSV files matching 'skis_unified*.csv' in {csv_dir}")
        return

    logging.info(f"Found {len(files)} CSV files for backfill")

    ski_index = load_ski_index(conn)

    updates: Dict[int, float] = {}  # ski_id -> orig_price_to_set

    for file_path in files:
        logging.info(f"Scanning {file_path.name} ...")
        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                shop_code = (row.get("shop") or "").strip()
                url = (row.get("url") or "").strip()
                condition = (row.get("condition") or "new").strip()
                length_cm = parse_float(row.get("length_cm"))
                orig_price = parse_float(row.get("orig_price"))

                if not shop_code or not url or orig_price is None:
                    continue

                key = (shop_code, url, length_cm, condition)
                if key not in ski_index:
                    # Лыжи в БД нет – значит, либо старый CSV, либо что-то нестандартное.
                    continue

                ski_id, db_orig_price = ski_index[key]
                if db_orig_price is None and ski_id not in updates:
                    # Кандидат на обновление
                    updates[ski_id] = orig_price

    if not updates:
        logging.info("No orig_price values to backfill – everything already filled.")
        return

    logging.info(f"Will backfill orig_price for {len(updates)} skis")

    conn.execute("BEGIN;")
    try:
        for ski_id, orig_price in updates.items():
            conn.execute(
                "UPDATE skis SET orig_price = ? WHERE id = ? AND orig_price IS NULL",
                (orig_price, ski_id),
            )
        conn.commit()
        logging.info("Backfill committed successfully")
    except Exception as e:
        conn.rollback()
        logging.error(f"ERROR during backfill: {e}")
        raise


def main():
    db_path = DEFAULT_DB_PATH
    csv_dir = DEFAULT_CSV_DIR

    logging.info("────────────────────────────────────────────")
    logging.info("START BACKFILL ORIG_PRICE")
    logging.info(f"DB:  {db_path}")
    logging.info(f"CSV: {csv_dir}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        backfill_from_csvs(conn, csv_dir)
        logging.info("BACKFILL FINISHED")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
