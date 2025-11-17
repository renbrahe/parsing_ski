import csv
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple, List

logger = logging.getLogger(__name__)

# Каталог с итоговыми CSV
EXPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"


def parse_length(value: str) -> Optional[int]:
    """
    Приводим length_cm к int (например '170.0' -> 170).
    Если не получается — возвращаем None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        s = s.replace(",", ".")
        f = float(s)
        return int(round(f))
    except ValueError:
        return None


def parse_price(value: str) -> Optional[float]:
    """
    Приводим price к float для сравнения.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def read_csv_to_map(path: Path) -> Dict[Tuple[str, str, Optional[int]], dict]:
    """
    Читает CSV и строит словарь:
        key = (shop, model, length_cm_int_or_None)
        value = строка CSV (dict)
    """
    mapping: Dict[Tuple[str, str, Optional[int]], dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # поддерживаем и старый вариант "shops", и новый "shop"
            shop = row.get("shop") or row.get("shops") or ""
            model = row.get("model") or ""
            length = parse_length(row.get("length_cm"))
            key = (shop, model, length)
            mapping[key] = row
    return mapping


def _key_sorter(key: Tuple[str, str, Optional[int]]):
    """
    Ключ сортировки для (shop, model, length_cm):
    - сортируем по shop, model как по строкам
    - длину None кладём «ниже» всех чисел, чтобы не было сравнения int и None
    """
    shop, model, length = key
    # Если length is None, поставим его, например, в -1, чтобы шёл перед 0/70/90/...
    # (или можно использовать большое число, чтобы шёл в конце — не критично)
    length_sort = -1 if length is None else length
    return (shop or "", model or "", length_sort)


def compare_two_files(old_path: Path, new_path: Path, out_path: Path) -> Path:
    """
    Сравнивает два CSV и пишет третий с изменениями.

    Ключ сравнения: (shop, model, length_cm).
    Логика:
      - есть в old, нет в new              -> sold_out
      - нет в old, есть в new              -> new_arrival
      - есть в обоих, но price отличается  -> price_change
    """
    old_map = read_csv_to_map(old_path)
    new_map = read_csv_to_map(new_path)

    all_keys = set(old_map.keys()) | set(new_map.keys())
    diff_rows: List[dict] = []

    count_sold_out = 0
    count_new = 0
    count_price_change = 0

    for key in sorted(all_keys, key=_key_sorter):
        in_old = key in old_map
        in_new = key in new_map

        if in_old and not in_new:
            status = "sold_out"
            base = old_map[key]
            count_sold_out += 1
        elif not in_old and in_new:
            status = "new_arrival"
            base = new_map[key]
            count_new += 1
        else:
            # есть и там, и там — проверяем изменение цены
            old_price = parse_price(old_map[key].get("price"))
            new_price = parse_price(new_map[key].get("price"))
            if old_price == new_price:
                # никаких изменений — пропускаем
                continue
            status = "price_change"
            base = new_map[key]  # показываем новую цену
            count_price_change += 1

        row = {
            "status": status,
            "shop": base.get("shop") or base.get("shops"),
            "brand": base.get("brand"),
            "model": base.get("model"),
            "length_cm": base.get("length_cm"),
            "condition": base.get("condition"),
            "orig_price": base.get("orig_price"),
            "price": base.get("price"),
            "url": base.get("url"),
        }
        diff_rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Порядок колонок: №, status, shop, brand, ...
    fieldnames = [
        "№",
        "status",
        "shop",
        "brand",
        "model",
        "length_cm",
        "condition",
        "orig_price",
        "price",
        "url",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, row in enumerate(diff_rows, start=1):
            row_to_write = {"№": idx}
            row_to_write.update(row)
            writer.writerow(row_to_write)

    logger.info(
        "[OK] Diff saved to: %s (rows: %d; sold_out=%d, new_arrival=%d, price_change=%d)",
        out_path,
        len(diff_rows),
        count_sold_out,
        count_new,
        count_price_change,
    )
    return out_path


def find_last_two_exports(
    export_dir: Path = EXPORT_DIR,
    prefix: str = "skis_unified_",
    suffix: str = ".csv",
) -> List[Path]:
    """
    Ищет два последних по имени файла типа skis_unified_YYYYMMDD_HHMM.csv
    в каталоге export_dir.
    """
    files = sorted(
        [p for p in export_dir.glob(f"{prefix}*{suffix}") if p.is_file()],
        key=lambda p: p.name,
    )
    if len(files) < 2:
        return []
    return files[-2:]


def compare_last_two_exports() -> Optional[Path]:
    """
    Автоматическая функция:
      - находит 2 последних export-файла
      - строит diff-файл
      - возвращает путь к diff-файлу
    """
    last_two = find_last_two_exports(EXPORT_DIR)
    if len(last_two) < 2:
        logger.error(
            "Нашлось меньше двух файлов skis_unified_*.csv в %s", EXPORT_DIR
        )
        return None

    old_path, new_path = last_two[0], last_two[1]

    old_label = old_path.stem.replace("skis_unified_", "")
    new_label = new_path.stem.replace("skis_unified_", "")
    out_name = f"skis_diff_{old_label}_vs_{new_label}.csv"
    out_path = EXPORT_DIR / out_name

    logger.info("[INFO] Old export: %s", old_path.name)
    logger.info("[INFO] New export: %s", new_path.name)
    return compare_two_files(old_path, new_path, out_path)


def main() -> None:
    compare_last_two_exports()


if __name__ == "__main__":
    main()
