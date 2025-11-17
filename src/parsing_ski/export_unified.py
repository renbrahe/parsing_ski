import csv
from pathlib import Path
from datetime import datetime
from typing import Iterable, List, Optional, Union, Dict, Any

# Каталог для экспорта относительно корня проекта
DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"


def get_default_export_path(prefix: str = "skis_unified") -> Path:
    """Вернуть путь вида data/exports/skis_unified_YYYYMMDD_HHMM.csv."""
    DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return DEFAULT_EXPORT_DIR / f"{prefix}_{ts}.csv"


UNIFIED_HEADER = [
    "№",
    "shop",
    "brand",
    "model",
    "length_cm",
    "condition",
    "orig_price",
    "price",
    "url",
]


def export_unified_to_csv(
    items: Iterable[Dict[str, Any]],
    filename: Union[str, Path],
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
) -> None:
    """
    Экспортирует список словарей в CSV в унифицированном формате.

    items — iterable словарей с ключами:
        shop, brand, model, condition, orig_price, price, length_cm, url

    filename — строка или Path до итогового CSV.

    min_length / max_length — необязательные границы длины лыж в см.
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Фильтрация по длине, если заданы границы
    filtered: List[Dict[str, Any]] = []
    for item in items:
        length = item.get("length_cm")

        if length is not None:
            try:
                L = int(length)
            except (TypeError, ValueError):
                L = None
        else:
            L = None

        if L is not None:
            if min_length is not None and L < min_length:
                continue
            if max_length is not None and L > max_length:
                continue

        filtered.append(item)

    # 2. Запись CSV
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_HEADER)
        writer.writeheader()

        for idx, item in enumerate(filtered, start=1):
            row = {
                "№": idx,
                "shop": item.get("shop"),
                "brand": item.get("brand"),
                "model": item.get("model"),
                "condition": item.get("condition"),
                "orig_price": item.get("orig_price"),
                "price": item.get("price"),
                "length_cm": item.get("length_cm"),
                "url": item.get("url"),
            }
            writer.writerow(row)

    print(f"[OK] Exported {len(filtered)} rows to {path}")
