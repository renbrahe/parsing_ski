#!/usr/bin/env python
"""
Сравнение двух последних экспортов и вывод diff-файла.

Пример:
    python compare_last_exports.py
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"


def setup_logging() -> Path:
    """
    Настраивает логирование в файл и консоль.
    Логи кладём в ./logs/diff_YYYYMMDD_HHMMSS.log
    """
    logs_dir = CURRENT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"diff_{ts}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    logging.getLogger(__name__).info("Логирование diff включено. Файл: %s", log_path)
    return log_path


if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from parsing_ski.diff_exports import main  # noqa: E402


if __name__ == "__main__":
    setup_logging()
    main()
