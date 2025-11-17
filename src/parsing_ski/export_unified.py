import csv
from datetime import datetime
from pathlib import Path

DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"

def get_default_export_path(prefix: str = "skis_unified") -> Path:
    DEFAULT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return DEFAULT_EXPORT_DIR / f"{prefix}_{ts}.csv"

UNIFIED_HEADER = [
    "№",
    "shops",
    "brand",
    "model",
    "length_cm",
    "condition",
    "orig_price",
    "price",
    "url",
]

def export_unified_to_csv(items, filename, min_length=None, max_length=None):
    """
    items — список dict вида:
      {
        "shops": "xtreme",
        "brand": "HEAD",
        "model": "Kore X 90",
        "condition": "new" / "used",
        "orig_price": 1350.0,
        "price": 999.0,
        "length_cm": 177,  # int или None
        "url": "https://..."
      }
    min_length / max_length — int или None
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    # если пользователь передал "output.csv", получим "output_20251115_2304.csv"
    if filename.lower().endswith(".csv"):
        filename = filename[:-4] + f"_{ts}.csv"
    else:
        filename = filename + f"_{ts}.csv"


    filtered = []
    for item in items:
        length = item.get("length_cm")

        # фильтрация по длине только если длина распознана
        if length is not None:
            if min_length is not None and length < min_length:
                continue
            if max_length is not None and length > max_length:
                continue

        filtered.append(item)

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_HEADER)
        writer.writeheader()

        for idx, item in enumerate(filtered, start=1):
            row = {
                "№": idx,
                "shops": item.get("shops"),
                "brand": item.get("brand"),
                "model": item.get("model"),
                "condition": item.get("condition"),
                "orig_price": item.get("orig_price"),
                "price": item.get("price"),
                "length_cm": item.get("length_cm"),
                "url": item.get("url"),
            }
            writer.writerow(row)

    print(f"[OK] Exported {len(filtered)} rows to {filename}")
