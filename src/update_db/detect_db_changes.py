#!/usr/bin/env python3
"""
detect_db_changes.py – фиксирует изменения между двумя scrape_runs в БД.

По умолчанию:
  - берёт два последних scrape_runs по run_at
  - сравнивает набор ski_id и цены в price_history
  - пишет результаты в 3 таблицы:
      changes_new_arrival    (новые позиции)
      changes_sold_out       (пропавшие позиции)
      changes_price_change   (изменение цены)

Таблицы создаются автоматически, если их ещё нет.

Логи:
  <root>/logs/db_changes_YYYY-MM-DD.log
"""

import argparse
import logging
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Dict, Tuple

# ──────────────────────────────────────────────
# ПУТИ
# ──────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "db" / "skis.db"
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / f"db_changes_{datetime.now().strftime('%Y-%m-%d')}.log"

# ──────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ──────────────────────────────────────────────

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


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ──────────────────────────────────────────────
# СХЕМА ТАБЛИЦ И ИНИЦИАЛИЗАЦИЯ
# ──────────────────────────────────────────────

def ensure_changes_tables(conn: sqlite3.Connection) -> None:
    """Создаём таблицы для изменений, если их нет."""
    sql = """
    CREATE TABLE IF NOT EXISTS changes_new_arrival (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id    INTEGER NOT NULL REFERENCES scrape_runs(id),
        ski_id    INTEGER NOT NULL REFERENCES skis(id),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, ski_id)
    );

    CREATE TABLE IF NOT EXISTS changes_sold_out (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id    INTEGER NOT NULL REFERENCES scrape_runs(id),
        ski_id    INTEGER NOT NULL REFERENCES skis(id),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, ski_id)
    );

    CREATE TABLE IF NOT EXISTS changes_price_change (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     INTEGER NOT NULL REFERENCES scrape_runs(id),
        ski_id     INTEGER NOT NULL REFERENCES skis(id),
        old_price  REAL NOT NULL,
        new_price  REAL NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(run_id, ski_id, old_price, new_price)
    );
    """
    conn.executescript(sql)
    conn.commit()


# ──────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ──────────────────────────────────────────────

def get_last_two_runs(conn: sqlite3.Connection) -> Tuple[int, int]:
    cur = conn.execute(
        "SELECT id, run_at, source_file FROM scrape_runs ORDER BY run_at"
    )
    rows = cur.fetchall()
    if len(rows) < 2:
        raise RuntimeError("В scrape_runs меньше двух записей, сравнивать нечего")

    old_id, old_at, old_file = rows[-2]
    new_id, new_at, new_file = rows[-1]

    logging.info(
        f"Using runs: OLD(id={old_id}, at={old_at}, file={old_file}) "
        f"-> NEW(id={new_id}, at={new_at}, file={new_file})"
    )
    return old_id, new_id


def load_prices_for_run(conn: sqlite3.Connection, run_id: int) -> Dict[int, float]:
    """
    Возвращает словарь: ski_id -> price для заданного run_id.
    """
    cur = conn.execute(
        "SELECT ski_id, price FROM price_history WHERE run_id = ?", (run_id,)
    )
    data: Dict[int, float] = {}
    for ski_id, price in cur.fetchall():
        data[int(ski_id)] = float(price)
    return data


def clear_existing_changes_for_run(conn: sqlite3.Connection, run_id: int) -> None:
    """
    На всякий случай очищаем изменения для данного run_id,
    чтобы можно было безопасно перезапускать скрипт.
    """
    conn.execute("DELETE FROM changes_new_arrival WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM changes_sold_out WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM changes_price_change WHERE run_id = ?", (run_id,))
    conn.commit()


# ──────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА
# ──────────────────────────────────────────────

def detect_changes(
    conn: sqlite3.Connection,
    old_run_id: int,
    new_run_id: int,
) -> None:
    """
    Сравнивает два run'а и пишет результаты в 3 таблицы изменений.
    """
    ensure_changes_tables(conn)

    logging.info(f"Detecting changes: old_run_id={old_run_id}, new_run_id={new_run_id}")

    old_prices = load_prices_for_run(conn, old_run_id)
    new_prices = load_prices_for_run(conn, new_run_id)

    old_set = set(old_prices.keys())
    new_set = set(new_prices.keys())

    # Новые: были только в новом
    new_arrivals = new_set - old_set
    # Проданные: были только в старом
    sold_out = old_set - new_set
    # Цена изменилась: есть в обоих, но цены различаются
    common = old_set & new_set
    price_changes = {
        ski_id
        for ski_id in common
        if old_prices[ski_id] != new_prices[ski_id]
    }

    logging.info(
        f"Changes: new_arrivals={len(new_arrivals)}, "
        f"sold_out={len(sold_out)}, price_changes={len(price_changes)}"
    )

    # Очистим прошлые записи для new_run_id, если они были
    clear_existing_changes_for_run(conn, new_run_id)

    conn.execute("BEGIN;")
    try:
        now = now_iso()

        # Новые
        for ski_id in new_arrivals:
            conn.execute(
                """
                INSERT OR IGNORE INTO changes_new_arrival (run_id, ski_id, created_at)
                VALUES (?, ?, ?)
                """,
                (new_run_id, ski_id, now),
            )

        # Проданные
        for ski_id in sold_out:
            conn.execute(
                """
                INSERT OR IGNORE INTO changes_sold_out (run_id, ski_id, created_at)
                VALUES (?, ?, ?)
                """,
                (new_run_id, ski_id, now),
            )

        # Изменение цены
        for ski_id in price_changes:
            old_price = old_prices[ski_id]
            new_price = new_prices[ski_id]
            conn.execute(
                """
                INSERT OR IGNORE INTO changes_price_change
                    (run_id, ski_id, old_price, new_price, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (new_run_id, ski_id, old_price, new_price, now),
            )

        conn.commit()
        logging.info("Changes saved to DB successfully.")

    except Exception as e:
        conn.rollback()
        logging.error(f"ERROR while saving changes: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Detect changes between two scrape_runs and store them in DB tables"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--old-run-id", type=int, help="ID старого run (опционально)")
    parser.add_argument("--new-run-id", type=int, help="ID нового run (опционально)")
    args = parser.parse_args()

    db_path = Path(args.db)

    logging.info("────────────────────────────────────────────")
    logging.info("START DB CHANGES DETECTION")
    logging.info(f"DB: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")

    try:
        if args.old_run_id is not None and args.new_run_id is not None:
            old_run_id = args.old_run_id
            new_run_id = args.new_run_id
        else:
            old_run_id, new_run_id = get_last_two_runs(conn)

        detect_changes(conn, old_run_id, new_run_id)
        logging.info("DB CHANGES DETECTION FINISHED")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
