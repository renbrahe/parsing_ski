#!/usr/bin/env python
"""
Утилита обслуживания данных проекта:

- Сравнение двух последних экспортов и генерация diff-файла.
- Операции с БД: создание/обновление, бэкфил, детект изменений, импорт CSV.

Примеры:
    # Поведение как раньше — просто diff последних файлов
    python manage_data.py

    # Явно запустить diff c новым именем файла (с текущим временем в конце)
    python manage_data.py --diff

    # Создать/обновить структуру БД
    python manage_data.py --db-init

    # Запустить все шаги обновления БД (бэкфил + детект + импорт)
    python manage_data.py --db-all

    # Только бэкфил
    python manage_data.py --db-backfill

    # Только детект изменений в БД
    python manage_data.py --db-detect-changes

    # Только импорт CSV в БД
    python manage_data.py --db-import-csv
"""

import sys
import logging
import argparse
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"


def setup_logging(mode: str) -> Path:
    """
    Настраивает логирование в файл и консоль.
    Логи кладём в ./logs/{mode}_YYYYMMDD_HHMMSS.log
    """
    logs_dir = CURRENT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{mode}_{ts}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    logging.getLogger(__name__).info(
        "Логирование включено для режима '%s'. Файл: %s", mode, log_path
    )
    return log_path


# Добавляем src в PYTHONPATH, чтобы видеть пакеты parsing_ski и update_db
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ==== Импортируем реальные реализации ====

# diff-логика
from parsing_ski.diff_exports import (  # type: ignore[import]
    EXPORT_DIR,
    compare_two_files,
)

# Скрипты работы с БД
from update_db.create_db import main as create_db_main  # type: ignore[import]
from update_db.backfill_orig_price import main as db_backfill_main  # type: ignore[import]
from update_db.detect_db_changes import main as detect_db_changes_main  # type: ignore[import]
from update_db.import_csvs import main as import_csv_main  # type: ignore[import]


def parse_args() -> argparse.Namespace:
    """
    Разбор аргументов командной строки.
    """
    parser = argparse.ArgumentParser(
        description="Утилита для diff экспортов и обслуживания БД."
    )

    group = parser.add_mutually_exclusive_group()

    # Текущий функционал (по умолчанию)
    group.add_argument(
        "--diff",
        action="store_true",
        help="Сравнить два последних экспортных CSV и вывести diff "
             "(создаёт новый файл с текущим временем в конце имени).",
    )

    # Режимы работы с БД
    group.add_argument(
        "--db-init",
        action="store_true",
        help="Создать/обновить структуру БД (обёртка над update_db/create_db.py).",
    )
    group.add_argument(
        "--db-all",
        action="store_true",
        help="Выполнить все шаги обновления БД: бэкфил, детект изменений, импорт CSV.",
    )
    group.add_argument(
        "--db-backfill",
        action="store_true",
        help="Выполнить только бэкфил БД.",
    )
    group.add_argument(
        "--db-detect-changes",
        action="store_true",
        help="Выполнить только детект изменений в БД.",
    )
    group.add_argument(
        "--db-import-csv",
        action="store_true",
        help="Выполнить только импорт CSV в БД.",
    )

    return parser.parse_args()


def _call_cli_main_safely(func):
    """
    Обёртка для сторонних main(), которые внутри themselves используют argparse.

    Она временно очищает sys.argv, чтобы внутренний argparse
    не видел ключи manage_data.py (типа --db-all).
    """
    def wrapper():
        old_argv = sys.argv
        try:
            # оставляем только имя скрипта — без флагов manage_data
            sys.argv = [old_argv[0]]
            return func()
        finally:
            sys.argv = old_argv

    return wrapper


# Оборачиваем потенциально "CLI-шные" main-функции
create_db_safe = _call_cli_main_safely(create_db_main)
db_backfill_safe = _call_cli_main_safely(db_backfill_main)
detect_db_changes_safe = _call_cli_main_safely(detect_db_changes_main)
import_csv_safe = _call_cli_main_safely(import_csv_main)


def run_diff():
    """
    Сравнивает два последних unified-экспорта и создаёт новый diff-файл
    с добавлением текущего времени к имени, чтобы не перезаписывать старый.
    """
    setup_logging("diff")
    logger = logging.getLogger(__name__)

    exports_dir = EXPORT_DIR
    csv_files = sorted(exports_dir.glob("skis_unified_*.csv"))

    if len(csv_files) < 2:
        logger.error(
            "Недостаточно файлов для diff: найдено %d, нужно минимум 2.",
            len(csv_files),
        )
        return

    old_path = csv_files[-2]
    new_path = csv_files[-1]

    logger.info("Old export: %s", old_path.name)
    logger.info("New export: %s", new_path.name)

    # Формируем имя diff-файла с текущим временем
    # получаем только дату из имени исходных CSV
    old_date_full = old_path.stem.replace("skis_unified_", "")
    new_date_full = new_path.stem.replace("skis_unified_", "")

    old_date = old_date_full.split("_")[0]  # YYYYMMDD
    new_date = new_date_full.split("_")[0]  # YYYYMMDD

    # timestamp самого дифа
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # итоговое имя
    out_name = f"diff_{old_date}_vs_{new_date}_{ts}.csv"
    out_path = exports_dir / out_name

    compare_two_files(old_path, new_path, out_path)

    logger.info("[OK] Diff saved to: %s", out_path)


def run_db_init():
    setup_logging("db_init")
    create_db_safe()


def run_db_all():
    """
    Полный цикл обновления БД:
      1) импорт новых CSV в БД (scrape_runs + price_history),
      2) бэкфил orig_price в таблице skis,
      3) детект изменений между двумя последними scrape_runs.

    CSV читаются только на шаге импорта, все остальные шаги работают ТОЛЬКО с БД.
    """
    setup_logging("db_all")
    logger = logging.getLogger(__name__)
    logger.info(
        "Старт полной процедуры обновления БД "
        "(импорт CSV -> бэкфил -> детект изменений)."
    )

    # 1) Импорт новых CSV в БД
    import_csv_safe()
    logger.info("Импорт CSV в БД завершён.")

    # 2) Бэкфил orig_price
    db_backfill_safe()
    logger.info("Бэкфил БД завершён.")

    # 3) Детект изменений между двумя последними run'ами
    detect_db_changes_safe()
    logger.info("Детект изменений в БД завершён.")

    logger.info("Полная процедура обновления БД успешно завершена.")



def run_db_backfill():
    setup_logging("db_backfill")
    db_backfill_safe()


def run_db_detect_changes():
    setup_logging("db_detect_changes")
    detect_db_changes_safe()


def run_db_import_csv():
    setup_logging("db_import_csv")
    import_csv_safe()


if __name__ == "__main__":
    args = parse_args()

    # Если флагов нет — сохраняем старое поведение: просто diff
    if not any(
        [
            args.diff,
            args.db_init,
            args.db_all,
            args.db_backfill,
            args.db_detect_changes,
            args.db_import_csv,
        ]
    ):
        run_diff()
    elif args.diff:
        run_diff()
    elif args.db_init:
        run_db_init()
    elif args.db_all:
        run_db_all()
    elif args.db_backfill:
        run_db_backfill()
    elif args.db_detect_changes:
        run_db_detect_changes()
    elif args.db_import_csv:
        run_db_import_csv()
