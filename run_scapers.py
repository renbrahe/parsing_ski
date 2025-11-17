#!/usr/bin/env python
"""
Удобная обёртка для запуска скрейперов.

Примеры:

    python run_scrapers.py --shops all --min 90 --max 195
    python run_scrapers.py --shops xtreme snowmania --test
"""
import sys
from pathlib import Path

# Добавляем src/ в sys.path, чтобы импортировались parsing_ski и shops
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from parsing_ski.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
