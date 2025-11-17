# db.py
import sqlite3
from datetime import datetime
from typing import Optional
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "db" / "skis.sqlite"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shops TEXT NOT NULL,
            url TEXT NOT NULL,
            brand TEXT,
            model TEXT,
            title TEXT,
            sizes TEXT,
            current_price REAL,
            old_price REAL,
            currency TEXT,
            in_stock INTEGER DEFAULT 1,
            quantity INTEGER,              -- сколько пар в магазине (если известно)
            shop_sku TEXT,
            is_interesting INTEGER,        -- NULL=не решено, 1=интересно, 0=неинтересно
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            UNIQUE (shops, url)
        )
        """
    )

    conn.commit()
    conn.close()


def _get_existing_product(cur: sqlite3.Cursor, shop: str, url: str):
    cur.execute(
        """
        SELECT id, is_interesting
          FROM products
         WHERE shops = ?
           AND url = ?
        """,
        (shop, url),
    )
    return cur.fetchone()


def upsert_product(
    *,
    shop: str,
    url: str,
    brand: Optional[str],
    model: Optional[str],
    title: Optional[str],
    sizes: Optional[str],
    current_price: Optional[float],
    old_price: Optional[float],
    currency: Optional[str],
    in_stock: bool = True,
    quantity: Optional[int] = None,
    shop_sku: Optional[str] = None,
) -> None:
    """
    Вставка или обновление товара.

    Логика:
      - если записи нет — вставляем (is_interesting = NULL, т.е. ещё не решено).
      - если запись есть и is_interesting = 0 — считаем товар НЕинтересным, дальше
        ничего НЕ обновляем (цены/размеры остаются как в момент первого парсинга).
      - если is_interesting = 1 или NULL — обновляем данные + last_seen.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")

    conn = get_connection()
    cur = conn.cursor()

    existing = _get_existing_product(cur, shop, url)

    if existing is None:
        # нет записи — вставляем
        cur.execute(
            """
            INSERT INTO products (
                shops, url, brand, model, title, sizes,
                current_price, old_price, currency,
                in_stock, quantity, shop_sku,
                is_interesting,
                created_at, last_seen
            )
            VALUES (
                :shops, :url, :brand, :model, :title, :sizes,
                :current_price, :old_price, :currency,
                :in_stock, :quantity, :shop_sku,
                :is_interesting,
                :created_at, :last_seen
            )
            """,
            {
                "shops": shop,
                "url": url,
                "brand": brand,
                "model": model,
                "title": title,
                "sizes": sizes,
                "current_price": current_price,
                "old_price": old_price,
                "currency": currency,
                "in_stock": 1 if in_stock else 0,
                "quantity": quantity,
                "shop_sku": shop_sku,
                "is_interesting": None,  # по умолчанию не решено
                "created_at": now,
                "last_seen": now,
            },
        )
    else:
        # запись есть
        product_id = existing["id"]
        is_interesting = existing["is_interesting"]

        if is_interesting == 0:
            # помечен как неинтересный — не обновляем цену, размеры и т.п.
            # Можно обновлять last_seen, если хочешь видеть, что товар всё ещё на сайте.
            # Сейчас вообще ничего не трогаем:
            conn.close()
            return

        # интересный или ещё не решён — обновляем
        cur.execute(
            """
            UPDATE products
               SET brand = :brand,
                   model = :model,
                   title = :title,
                   sizes = :sizes,
                   current_price = :current_price,
                   old_price = :old_price,
                   currency = :currency,
                   in_stock = :in_stock,
                   quantity = :quantity,
                   shop_sku = :shop_sku,
                   last_seen = :last_seen
             WHERE id = :id
            """,
            {
                "id": product_id,
                "brand": brand,
                "model": model,
                "title": title,
                "sizes": sizes,
                "current_price": current_price,
                "old_price": old_price,
                "currency": currency,
                "in_stock": 1 if in_stock else 0,
                "quantity": quantity,
                "shop_sku": shop_sku,
                "last_seen": now,
            },
        )

    conn.commit()
    conn.close()


def set_interesting(shop: str, url: str, is_interesting: bool) -> None:
    """
    Ручная пометка товара:
      - True  -> is_interesting = 1 (отслеживаем дальше)
      - False -> is_interesting = 0 (фиксируем и больше не обновляем)
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE products
           SET is_interesting = :val
         WHERE shops = :shops
           AND url = :url
        """,
        {
            "val": 1 if is_interesting else 0,
            "shops": shop,
            "url": url,
        },
    )

    conn.commit()
    conn.close()
