#!/usr/bin/env python3
"""
create_db.py – создаёт SQLite-базу для проекта лыж.

По умолчанию БД: <корень_проекта>/data/db/skis.db

Ожидаемая структура проекта:
  parsing_ski/
    data/
      db/
        skis.db
      exports/
        skis_unified_*.csv
    src/
      update_db/
        create_db.py
        import_csvs.py
"""

import argparse
import sqlite3
from textwrap import dedent
from pathlib import Path


# Определяем корень проекта: .../parsing_ski
ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "data" / "db" / "skis.db"


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")

    schema_sql = dedent(
        """
        -- Магазины
        CREATE TABLE IF NOT EXISTS shops (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT NOT NULL UNIQUE,      -- 'xtreme.ge', 'megasport.ge' и т.п.
            name        TEXT NOT NULL,             -- Человеческое название
            base_url    TEXT,
            currency    TEXT NOT NULL DEFAULT 'GEL'
        );

        -- Лыжи (уникально: магазин + url + длина + состояние)
        CREATE TABLE IF NOT EXISTS skis (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id         INTEGER NOT NULL REFERENCES shops(id),
            brand           TEXT,
            model           TEXT NOT NULL,
            length_cm       REAL,
            condition       TEXT NOT NULL,        -- 'new', 'used'
            url             TEXT NOT NULL,
            orig_price      REAL,                 -- первый зафиксированный orig_price
            first_seen_at   TEXT NOT NULL,
            last_seen_at    TEXT NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1, -- 1 – есть, 0 – пропала

            UNIQUE (shop_id, url, length_cm, condition)
        );

        -- Запуски парсинга (выгрузки)
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT NOT NULL,        -- ISO8601
            source_file     TEXT,                 -- имя CSV
            min_length_cm   REAL,
            max_length_cm   REAL,
            notes           TEXT
        );

        -- История цен
        CREATE TABLE IF NOT EXISTS price_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ski_id          INTEGER NOT NULL REFERENCES skis(id),
            run_id          INTEGER NOT NULL REFERENCES scrape_runs(id),
            price           REAL NOT NULL,
            created_at      TEXT NOT NULL,

            UNIQUE (ski_id, run_id)
        );

        -- Какие CSV уже обработаны
        CREATE TABLE IF NOT EXISTS processed_files (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name       TEXT NOT NULL UNIQUE,
            run_id          INTEGER NOT NULL REFERENCES scrape_runs(id),
            processed_at    TEXT NOT NULL
        );

        -- Индексы
        CREATE INDEX IF NOT EXISTS idx_skis_shop_url_len_cond
            ON skis (shop_id, url, length_cm, condition);

        CREATE INDEX IF NOT EXISTS idx_price_history_ski
            ON price_history (ski_id);

        CREATE INDEX IF NOT EXISTS idx_price_history_run
            ON price_history (run_id);

        CREATE INDEX IF NOT EXISTS idx_scrape_runs_run_at
            ON scrape_runs (run_at);

        --------------------------------------------------------------------
        -- Представление с актуальной ценой и скидкой
        --------------------------------------------------------------------
        CREATE VIEW IF NOT EXISTS v_latest_prices AS
        WITH last_price AS (
            SELECT
                ph.ski_id,
                ph.price,
                sr.run_at,
                ROW_NUMBER() OVER (
                    PARTITION BY ph.ski_id
                    ORDER BY sr.run_at DESC
                ) AS rn
            FROM price_history ph
            JOIN scrape_runs sr ON ph.run_id = sr.id
        )
        SELECT
            s.id                AS ski_id,
            sh.code             AS shop_code,
            s.brand,
            s.model,
            s.length_cm,
            s.condition,
            s.url,
            s.orig_price,
            lp.price            AS current_price,
            lp.run_at           AS last_price_at,
            CASE
                WHEN s.orig_price IS NOT NULL AND s.orig_price > 0 THEN
                    ROUND((s.orig_price - lp.price) * 100.0 / s.orig_price, 1)
                ELSE NULL
            END                 AS discount_pct
        FROM skis s
        JOIN shops sh      ON sh.id = s.shop_id
        JOIN last_price lp ON lp.ski_id = s.id AND lp.rn = 1;

        --------------------------------------------------------------------
        -- История изменений/цен по трём таблицам: price_history + skis + scrape_runs
        --------------------------------------------------------------------
        CREATE VIEW IF NOT EXISTS v_changes_history AS
        SELECT
            ph.id              AS price_history_id,
            sr.id              AS run_id,
            sr.run_at          AS run_at,
            sr.source_file     AS source_file,

            s.id               AS ski_id,
            sh.code            AS shop_code,
            s.brand,
            s.model,
            s.length_cm,
            s.condition,
            s.url,

            s.orig_price,
            ph.price           AS price,
            CASE
                WHEN s.orig_price IS NOT NULL AND s.orig_price > 0 THEN
                    ROUND((s.orig_price - ph.price) * 100.0 / s.orig_price, 1)
                ELSE NULL
            END                 AS discount_pct,

            s.first_seen_at,
            s.last_seen_at,
            s.is_active
        FROM price_history ph
        JOIN skis       s   ON s.id = ph.ski_id
        JOIN shops      sh  ON sh.id = s.shop_id
        JOIN scrape_runs sr ON sr.id = ph.run_id;
        """
    )

    conn.executescript(schema_sql)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create SQLite DB for skis project")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to SQLite DB file (default: data/db/skis.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        print(f"Database schema created (or already existed) in {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
