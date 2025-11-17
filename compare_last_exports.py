#!/usr/bin/env python
"""
Сравнение двух последних экспортов и вывод diff-файла.

Пример:
    python compare_last_exports.py
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from parsing_ski.diff_exports import main  # noqa: E402


if __name__ == "__main__":
    main()
