#!/usr/bin/env python3
"""Запуск проектно-ориентированного GUI (gui_project)."""
import sys

try:
    from PyQt5.QtWidgets import QApplication  # noqa: F401
except ImportError:
    print("PyQt5 не установлен. Установите: pip install -r requirements_gui.txt")
    sys.exit(1)

from gui.gui_project import main

if __name__ == "__main__":
    main()
