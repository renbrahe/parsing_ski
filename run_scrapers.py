import argparse
import re
from typing import Dict, List, Callable

from models import Product
from shop_extreme_ge import scrape_xtreme
from shop_snowmania_ge import scrape_snowmania
from shop_burosports_ge import (
    scrape_burosports,
    product_to_unified_rows as burosports_product_to_unified_rows,
)
from export_unified import export_unified_to_csv


def product_to_unified_rows(p: Product) -> List[dict]:
    """
    Преобразует Product из models.py в унифицированный dict
    под export_unified_to_csv.
    """
    if getattr(p, "shop", None) == "burusports":
        return burosports_product_to_unified_rows(p)

    # длина лыжи: берём первый размер из списка sizes
    length_cm = None
    sizes = getattr(p, "sizes", []) or []
    if sizes:
        s0 = str(sizes[0])
        m = re.search(r"\d+", s0)
        if m:
            try:
                length_cm = int(m.group(0))
            except ValueError:
                length_cm = None

    row = {
        "shop": p.shop,
        "brand": p.brand,
        # если model пустая — подставим title
        "model": p.model or p.title,
        "condition": p.condition,
        "orig_price": p.old_price,
        "price": p.current_price,
        "length_cm": length_cm,
        "url": p.url,
    }
    return [row]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: only first page per shop",
    )
    parser.add_argument(
        "--shops",
        nargs="+",
        choices=["xtreme", "snowmania", "burosports"],
        required=True,
        help="Shops to scrape",
    )
    parser.add_argument(
        "--min",
        dest="min_length",
        type=int,
        default=None,
        help="Min ski length in cm (e.g. 150)",
    )
    parser.add_argument(
        "--max",
        dest="max_length",
        type=int,
        default=None,
        help="Max ski length in cm (e.g. 190)",
    )
    return parser.parse_args()


def build_runners(test_mode: bool) -> Dict[str, Callable[[], List[Product]]]:
    """
    Создаёт раннеры, учитывающие test_mode.
    """

    def xtreme_runner() -> List[Product]:
        # внутри scrape_xtreme test_mode=True ограничит страницы
        return scrape_xtreme(test_mode=test_mode)

    def snowmania_runner() -> List[Product]:
        # в тестовом режиме только 1 страница на категорию
        return scrape_snowmania(
            test_mode=test_mode,
            test_max_pages=1,
        )

    def burosports_runner() -> List[Product]:
        # при желании сюда тоже можно добавить test_mode
        return scrape_burosports(test_mode=test_mode)

    return {
        "xtreme": xtreme_runner,
        "snowmania": snowmania_runner,
        "burosports": burosports_runner,
    }


def validate_shops(
    requested: List[str],
    available: Dict[str, Callable[[], List[Product]]],
) -> List[str]:
    """
    Проверяет корректность списка магазинов.
    """
    valid: List[str] = []

    for s in requested:
        s_norm = s.strip().lower()
        if s_norm in available:
            valid.append(s_norm)
        else:
            print(f"[WARN] Unknown shop '{s}', skipping.")

    if not valid:
        print("[ERROR] No valid shops selected. Exiting.")

    return valid


def main():
    args = parse_args()

    # создаём раннеры с учётом test_mode
    runners = build_runners(test_mode=args.test)

    # нормализуем и проверяем список магазинов
    shops = validate_shops(args.shops, runners)
    if not shops:
        return

    all_items = []

    for shop_code in shops:
        runner = runners[shop_code]
        print(f"[RUN] Scraping {shop_code} ...")
        products = runner()
        print(f"[INFO] {shop_code}: {len(products)} products scraped")

        # конвертируем Product → dict для export_unified_to_csv
        for p in products:
            all_items.extend(product_to_unified_rows(p))

    export_unified_to_csv(
        all_items,
        filename="skis_unified.csv",
        min_length=args.min_length,
        max_length=args.max_length,
    )
    print("[OK] Export finished: skis_unified.csv")


if __name__ == "__main__":
    main()
