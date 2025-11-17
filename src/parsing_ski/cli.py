import argparse
from pathlib import Path
from typing import List, Dict

from parsing_ski.models import Product, MIN_SKI_LENGTH_CM, MAX_SKI_LENGTH_CM
from shops.shop_extreme_ge import scrape_xtreme
from shops.shop_snowmania_ge import scrape_snowmania
from shops.shop_burosports_ge import (
    scrape_burosports,
    product_to_unified_rows as burosports_product_to_unified_rows,
)
from shops.shop_megasport_ge import scrape_megasport

from .export_unified import export_unified_to_csv, get_default_export_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Georgian ski shops and export unified CSV."
    )
    parser.add_argument(
        "--shops",
        nargs="+",
        default=["all"],
        help=(
            "Какие магазины парсить: xtreme snowmania burosports megasport "
            "или 'all' чтобы спарсить все (по умолчанию all)."
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Тестовый режим: только первая страница на магазин (где применимо).",
    )
    parser.add_argument(
        "--min",
        dest="min_length",
        type=int,
        default=None,
        help="Минимальная длина лыжи в см (например 150).",
    )
    parser.add_argument(
        "--max",
        dest="max_length",
        type=int,
        default=None,
        help="Максимальная длина лыжи в см (например 190).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Путь к CSV. Если не указан — файл создаётся в data/exports/ "
            "с таймстампом."
        ),
    )
    return parser.parse_args()


def product_to_unified_rows_generic(p: Product) -> List[dict]:
    """
    Превратить Product в одну или несколько строк унифицированного формата.

    - Пытаемся достать ВСЕ длины из p.sizes (типа '185', '185cm', '176 სმ').
    - Если не получилось — пробуем 3-значное число из названия модели.
    """
    rows: List[dict] = []

    sizes = getattr(p, "sizes", []) or []

    # 1. Пытаемся парсить длины из sizes
    lengths: List[int] = []
    for s in sizes:
        clean = "".join(
            ch if ch.isdigit() or ch.isspace() else " " for ch in (s or "")
        )
        for chunk in clean.split():
            if len(chunk) >= 2 and chunk.isdigit():
                L = int(chunk)
                if MIN_SKI_LENGTH_CM <= L <= MAX_SKI_LENGTH_CM and L not in lengths:
                    lengths.append(L)

    # 2. Если ничего не нашли — пробуем из model
    if not lengths and (p.model or ""):
        import re as _re

        m = _re.search(r"(\d{3})", p.model)
        if m:
            L = int(m.group(1))
            if MIN_SKI_LENGTH_CM <= L <= MAX_SKI_LENGTH_CM:
                lengths.append(L)

    # Если всё равно пусто — длину оставляем None
    if not lengths:
        lengths = [None]

    for L in lengths:
        rows.append(
            {
                "shops": p.shop,
                "brand": p.brand,
                "model": p.model,
                "condition": p.condition,
                "orig_price": p.old_price,
                "price": p.current_price,
                "length_cm": L,
                "url": p.url,
            }
        )

    return rows


def main() -> None:
    args = parse_args()

    # Нормализуем список магазинов
    available_shops: Dict[str, str] = {
        "xtreme": "xtreme.ge",
        "snowmania": "snowmania.ge",
        "burosports": "burusports.ge",
        "megasport": "megasport.ge",
    }

    requested = [s.lower() for s in args.shops]

    if "all" in requested:
        shop_codes = list(available_shops.keys())
    else:
        unknown = [s for s in requested if s not in available_shops]
        if unknown:
            raise SystemExit(f"Unknown shop codes: {', '.join(unknown)}")
        shop_codes = requested

    all_rows: List[dict] = []

    for code in shop_codes:
        print(f"[RUN] Scraping {available_shops[code]} ...")

        # Вызываем нужный скрейпер с параметрами тестового режима
        if code == "xtreme":
            products = scrape_xtreme(
                test_mode=args.test,
                max_pages=1 if args.test else None,
            )
        elif code == "snowmania":
            products = scrape_snowmania(
                test_mode=args.test,
                test_max_pages=1 if args.test else 99,
            )
        elif code == "burosports":
            products = scrape_burosports(test_mode=args.test)
        elif code == "megasport":
            products = scrape_megasport(test_mode=args.test)
        else:
            # На всякий случай, сюда не должны попасть
            continue

        print(f"[INFO] {available_shops[code]}: {len(products)} products scraped")

        for p in products:
            if code == "burosports":
                # Для burusports уже есть своя функция разбиения по длинам
                rows = burosports_product_to_unified_rows(p)
            else:
                rows = product_to_unified_rows_generic(p)
            all_rows.extend(rows)

    if not all_rows:
        print("[WARN] No rows scraped, nothing to export.")
        return

    out_path = Path(args.output) if args.output else get_default_export_path()
    export_unified_to_csv(
        all_rows,
        filename=out_path,
        min_length=args.min_length,
        max_length=args.max_length,
    )
    print(f"[OK] Export finished: {out_path}")


if __name__ == "__main__":
    main()
