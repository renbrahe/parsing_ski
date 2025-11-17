#!/usr/bin/env python3
"""
import_csvs.py – импортирует выгрузки skis_unified*.csv в БД.

По умолчанию:
    DB:       <корень>/data/db/skis.db
    CSV dir:  <корень>/data/exports
    LOGS:     <корень>/logs/db_update_YYYY-MM-DD.log
"""

import argparse
import csv
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging


# ──────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "db" / "skis.db"
DEFAULT_CSV_DIR = ROOT_DIR / "data" / "exports"
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / f"db_update_{datetime.now().strftime('%Y-%m-%d')}.log"


# ──────────────────────────────────────────────────────────────
# LOGGING CONFIG
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
    """Возвращает время в ISO8601 UTC, timezone-aware."""
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
# DB HELPERS
# ──────────────────────────────────────────────────────────────

def get_processed_files(conn: sqlite3.Connection) -> set:
    cur = conn.execute("SELECT file_name FROM processed_files;")
    return {row[0] for row in cur.fetchall()}


def get_or_create_shop(conn: sqlite3.Connection, code: str) -> int:
    code = code.strip()
    cur = conn.execute("SELECT id FROM shops WHERE code = ?", (code,))
    row = cur.fetchone()
    if row:
        return row[0]

    base_url = f"https://{code}" if "." in code else None
    cur = conn.execute(
        "INSERT INTO shops (code, name, base_url) VALUES (?, ?, ?)",
        (code, code, base_url),
    )
    return cur.lastrowid


def get_or_create_ski(
    conn: sqlite3.Connection,
    shop_id: int,
    brand: str,
    model: str,
    length_cm: Optional[float],
    condition: str,
    url: str,
    orig_price: Optional[float],
) -> int:
    condition = (condition or "new").strip()
    brand = (brand or "").strip()
    model = (model or "").strip()
    url = (url or "").strip()

    cur = conn.execute(
        """
        SELECT id, orig_price FROM skis
        WHERE shop_id = ?
          AND url = ?
          AND ((length_cm IS NULL AND ? IS NULL) OR length_cm = ?)
          AND condition = ?
        """,
        (shop_id, url, length_cm, length_cm, condition),
    )
    row = cur.fetchone()
    now = now_iso()

    if row:
        ski_id, db_orig_price = row
        if db_orig_price is None and orig_price is not None:
            conn.execute(
                "UPDATE skis SET orig_price=?, last_seen_at=?, is_active=1 WHERE id=?",
                (orig_price, now, ski_id),
            )
        else:
            conn.execute(
                "UPDATE skis SET last_seen_at=?, is_active=1 WHERE id=?",
                (now, ski_id),
            )
        return ski_id

    cur = conn.execute(
        """
        INSERT INTO skis (
            shop_id, brand, model, length_cm, condition,
            url, orig_price, first_seen_at, last_seen_at, is_active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (shop_id, brand, model, length_cm, condition, url, orig_price, now, now),
    )
    return cur.lastrowid


def create_scrape_run(conn, file_name, min_length, max_length) -> int:
    cur = conn.execute(
        """
        INSERT INTO scrape_runs(run_at, source_file, min_length_cm, max_length_cm, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now_iso(), file_name, min_length, max_length, "auto-import"),
    )
    return cur.lastrowid


def insert_price_history(conn, ski_id, run_id, price):
    conn.execute(
        "INSERT OR IGNORE INTO price_history(ski_id, run_id, price, created_at) VALUES (?, ?, ?, ?)",
        (ski_id, run_id, price, now_iso()),
    )


def mark_file_processed(conn, file_name, run_id):
    conn.execute(
        """
        INSERT INTO processed_files(file_name, run_id, processed_at)
        VALUES (?, ?, ?)
        """,
        (file_name, run_id, now_iso()),
    )


# ──────────────────────────────────────────────────────────────
# CSV PROCESSING
# ──────────────────────────────────────────────────────────────

def process_csv_file(conn: sqlite3.Connection, file_path: Path) -> None:
    file_name = file_path.name
    logging.info(f"Processing: {file_name}")

    rows = []
    lengths = []

    with file_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            l = parse_float(row.get("length_cm"))
            if l is not None:
                lengths.append(l)

    min_len = min(lengths) if lengths else None
    max_len = max(lengths) if lengths else None

    conn.execute("BEGIN;")
    try:
        run_id = create_scrape_run(conn, file_name, min_len, max_len)

        for row in rows:
            shop_code = (row.get("shop") or "").strip()
            brand = row.get("brand") or ""
            model = row.get("model") or ""
            condition = row.get("condition") or "new"
            url = row.get("url") or ""

            length_cm = parse_float(row.get("length_cm"))
            orig_price = parse_float(row.get("orig_price"))
            price = parse_float(row.get("price"))

            if not shop_code or not url or price is None:
                continue

            shop_id = get_or_create_shop(conn, shop_code)
            ski_id = get_or_create_ski(
                conn,
                shop_id,
                brand,
                model,
                length_cm,
                condition,
                url,
                orig_price,
            )
            insert_price_history(conn, ski_id, run_id, price)

        mark_file_processed(conn, file_name, run_id)
        conn.commit()

        logging.info(
            f"Done: {file_name} | {len(rows)} rows | run_id={run_id} | range={min_len}-{max_len}"
        )

    except Exception as e:
        conn.rollback()
        logging.error(f"ERROR while processing {file_name}: {e}")
        raise


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import skis_unified*.csv into DB")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR))
    args = parser.parse_args()

    db_path = Path(args.db)
    csv_dir = Path(args.csv_dir)

    logging.info("────────────────────────────────────────────")
    logging.info("START IMPORT")
    logging.info(f"DB:  {db_path}")
    logging.info(f"CSV: {csv_dir}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        processed = get_processed_files(conn)
        logging.info(f"Already processed: {len(processed)}")

        files = sorted(f for f in csv_dir.glob("skis_unified*.csv") if f.is_file())
        logging.info(f"Found CSV files: {len(files)}")

        new_files = [f for f in files if f.name not in processed]
        logging.info(f"New CSV files to import: {len(new_files)}")

        if not new_files:
            logging.info("Nothing to import.")
            return

        for f in new_files:
            process_csv_file(conn, f)

        logging.info("IMPORT FINISHED OK")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
