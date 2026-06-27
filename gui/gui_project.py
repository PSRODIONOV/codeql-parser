"""gui_project.py — проектно-ориентированный графический интерфейс.

Поток:
  ProjectPicker (создать / открыть / история)  →  ProjectWindow (вкладки):
    • «Статический анализ»  — выбор CodeQL БД, язык, состав проверок, RAM/маршруты,
       запуск анализа (→ project.db), создание отчётов (→ reports/static).
    • «Динамический анализ» — инструментация исходников (→ src-instrumented),
       добавление трасс (счётчик покрытия), отчёты покрытия (→ reports/dynamic).

Персистентность — project.db (см. project_db.ProjectDB). Реестр недавних проектов —
~/.codeql-gui/recent_projects.json.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QSlider, QCheckBox, QGroupBox,
    QTabWidget, QListWidget, QListWidgetItem, QTextEdit, QPlainTextEdit, QFileDialog,
    QMessageBox, QInputDialog, QScrollArea,
)

from gui import gui_styles
from gui.gui_widgets import (
    FileDropZone, set_locked, is_locked, enable_dragdrop_under_uac,
    install_disabled_tab_cursor,
)
from core.project_db import ProjectDB
from core import project_runner as pr
from paths import third_party, PROJECT_ROOT

ROOT = PROJECT_ROOT
RECENT_FILE = Path.home() / ".codeql-gui" / "recent_projects.json"

LANGUAGES = [("C++", "cpp"), ("Java", "java"), ("JavaScript", "javascript"), ("Python", "python"), ("PHP", "php"), ("SQL", "sql")]

SQL_DIALECTS = [
    ("MySQL / MariaDB", "mysql"),
    ("PostgreSQL",      "postgres"),
    ("T-SQL (SQL Server)", "tsql"),
    ("Oracle PL/SQL",   "oracle"),
    ("SQLite",          "sqlite"),
    ("Generic SQL",     "generic"),
]

# Состав проверок (1:1 с отчётами), сгруппированный
CHECK_GROUPS = {
    "Основные": [
        (pr.CHECK_FUNCTIONAL, "Перечень ФО (процедур/функций)"),
        (pr.CHECK_INFO, "Перечень ИО"),
        (pr.CHECK_SIGNATURE, "Сигнатурный анализ"),
    ],
    "Матрицы": [
        (pr.CHECK_MATRIX, "Матрица связей по управлению"),
        (pr.CHECK_DATA_MATRIX, "Матрица связей по информации"),
    ],
    "Маршруты и ветви": [
        (pr.CHECK_ROUTES_BR, "Маршруты выполнения (ветвей)"),
        (pr.CHECK_ROUTES_CALL, "Маршруты выполнения (вызовов)"),
        (pr.CHECK_BRANCH_LIST, "Перечень ветвей"),
    ],
    "Графы": [
        (pr.CHECK_GRAPH_FUNC, "Граф функций"),
        (pr.CHECK_GRAPH_BR, "Граф ветвей"),
        (pr.CHECK_GRAPH_ROUTE, "Граф маршрутов"),
    ],
    "Визуализация": [
        (pr.CHECK_FLOWCHARTS, "Блок-схемы (SVG)"),
    ],
}


def _bar_text(label: str, cur: int, total: int, width: int = 24) -> str:
    """Строка текстового прогресс-бара: 'label [████░░░░] 250/590 (42%)'."""
    if total <= 0:
        return f"{label}…"
    frac = max(0.0, min(1.0, cur / total))
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    return f"{label} [{bar}] {cur}/{total} ({int(frac*100)}%)"


def _fixed_counter(cur: int, total: int) -> str:
    """'тек/итог', право-выровненное в зарезервированной ширине
    цифр(итог)*2+1 — чтобы счётчик не "прыгал" по мере роста cur (см.
    обсуждение формата лога)."""
    width = len(str(max(total, 1))) * 2 + 1
    return f"{cur}/{total}".rjust(width)


def _bar_only(cur: int, total: int, width: int = 24) -> str:
    """Полоса прогресса + фиксированный счётчик, без подписи — для вставки
    внутрь ячейки таблицы (см. attach_progress, _DERIVED_LABELS)."""
    if total <= 0:
        return "…"
    frac = max(0.0, min(1.0, cur / total))
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {_fixed_counter(cur, total)}"


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _set_cell_text(cell, text: str):
    """Заменяет содержимое ячейки QTextTable целиком (выделяет от начала до
    конца ячейки и вставляет новый текст) — у QTextTableCell нет метода
    "select all", это стандартный приём Qt для частичного обновления
    готовой таблицы (не пересобирать всю таблицу/HTML на каждое изменение)."""
    from PyQt5.QtGui import QTextCursor
    start = cell.firstCursorPosition()
    end = cell.lastCursorPosition()
    start.setPosition(end.position(), QTextCursor.KeepAnchor)
    start.insertText(text)


def _new_table_cursor(log_widget):
    """Курсор в конец лога, с переводом строки перед новой таблицей (если
    лог не пуст) — общая подготовка перед insertTable для обеих таблиц."""
    from PyQt5.QtGui import QTextCursor
    cursor = log_widget.textCursor()
    cursor.movePosition(QTextCursor.End)
    if log_widget.toPlainText():
        cursor.insertText("\n")
    return cursor


def _table_format():
    from PyQt5.QtGui import QTextTableFormat
    fmt = QTextTableFormat()
    fmt.setCellPadding(4)
    fmt.setCellSpacing(0)
    fmt.setBorder(1)
    return fmt


# Метки progress(), которые рендерятся как прогресс-бар ВНУТРИ ячейки
# Таблицы 2 ("Производные"), а не полнострочным текстом — см.
# viz/flowchart_generator.py (БЛОК-СХЕМЫ/МАРШРУТЫ, фаза run_static_analysis)
# и core/project_runner.py (Запись маршрутов/Выгрузка блок-схем, фаза
# generate_static_reports — второй клик "Создать отчёты").
_DERIVED_LABELS = [
    "[БЛОК-СХЕМЫ] Генерация блок-схем (ФО)",
    "[МАРШРУТЫ] Формирование маршрутов (ФО)",
    "Запись маршрутов",
    "Выгрузка блок-схем",
]


def attach_progress(log_widget, worker):
    """Подключает прогресс воркера к QTextEdit. Известные label из
    _DERIVED_LABELS рисуются прогресс-баром внутри ячейки Таблицы 2
    (создаётся лениво при первом таком label); остальные — старым способом,
    одной строкой, перезаписываемой на месте (см. _bar_text)."""
    from PyQt5.QtGui import QTextCursor
    import time as _time

    state = {"active": False, "derived_table": None, "row_of": {}, "start_time": {}}

    def _ensure_derived_table():
        if state["derived_table"] is not None:
            return state["derived_table"]
        cursor = _new_table_cursor(log_widget)
        table = cursor.insertTable(len(_DERIVED_LABELS) + 1, 3, _table_format())
        for c, name in enumerate(["Производные", "Прогресс", "Время"]):
            _set_cell_text(table.cellAt(0, c), name)
        row_of = {}
        for i, label in enumerate(_DERIVED_LABELS, start=1):
            _set_cell_text(table.cellAt(i, 0), label)
            _set_cell_text(table.cellAt(i, 1), "—")
            _set_cell_text(table.cellAt(i, 2), "—")
            row_of[label] = i
        cursor.movePosition(QTextCursor.End)
        log_widget.setTextCursor(cursor)
        state["derived_table"] = table
        state["row_of"] = row_of
        return table

    def on_progress(label, cur, total):
        if label in _DERIVED_LABELS:
            table = _ensure_derived_table()
            row = state["row_of"][label]
            state["start_time"].setdefault(label, _time.perf_counter())
            if total > 0 and cur >= total:
                elapsed = _time.perf_counter() - state["start_time"][label]
                _set_cell_text(table.cellAt(row, 1), str(cur))
                _set_cell_text(table.cellAt(row, 2), pr._dt(elapsed))
            else:
                _set_cell_text(table.cellAt(row, 1), _bar_only(cur, total))
            return
        text = _bar_text(label, cur, total)
        cursor = log_widget.textCursor()
        cursor.movePosition(QTextCursor.End)
        if state["active"]:
            # удалить предыдущую строку прогресса
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.removeSelectedText()
        else:
            if log_widget.toPlainText():
                cursor.insertText("\n")
            state["active"] = True
        cursor.insertText(text)
        log_widget.setTextCursor(cursor)

    def on_log(_msg):
        # обычное сообщение завершает текущую строку прогресса
        state["active"] = False

    worker.progress.connect(on_progress)
    worker.log.connect(on_log)


# Столбцы Таблицы 1 ("воронка" по запросам/фильтрам) и шаги фильтрации,
# которым они соответствуют (см. core/project_runner.py::_table — события
# query_batch_start/query_batch_done/filter_step).
_FUNNEL_COLS = ["Сущность", "Запрошено", "Вне списка", "Макро-фильтр", "Итог", "Время"]
_FUNNEL_STEP_COL = {"вне списка": 2, "макро-фильтр": 3}


def attach_funnel_table(log_widget, worker):
    """Подключает Таблицу 1 (воронка ФО/ИО/файлы/матрицы/анализ/поток/
    датчики). Рисуется целиком на "query_batch_start" (все ячейки "—"),
    столбец "Запрошено" крутит ОБЩИЙ спиннер на всех строках сразу (см.
    обсуждение формата: codeql выполняет все запросы ОДНИМ блокирующим
    вызовом — честного покадрового прогресса по отдельным запросам нет),
    "query_batch_done" останавливает спиннер и заполняет числа. Шаги
    "вне списка"/"макро-фильтр" заполняют только строки, упомянутые в
    payload — остальные остаются "—" (см. план: control/arg_flow/file_flow/
    files не трогаются макро-фильтром, это архитектурно корректно)."""
    state = {"table": None, "row_of": {}, "timer": None, "frame": 0}

    def _stop_timer():
        if state["timer"] is not None:
            state["timer"].stop()
            state["timer"] = None

    def _tick():
        state["frame"] = (state["frame"] + 1) % len(_SPINNER)
        glyph = _SPINNER[state["frame"]]
        table = state["table"]
        if table is None:
            return
        for row in state["row_of"].values():
            _set_cell_text(table.cellAt(row, 1), glyph)

    def on_table(event, payload):
        if event == "query_batch_start":
            from PyQt5.QtGui import QTextCursor
            rows = payload["rows"]  # [(key, (tag, label)), ...]
            cursor = _new_table_cursor(log_widget)
            table = cursor.insertTable(len(rows) + 1, len(_FUNNEL_COLS), _table_format())
            for c, name in enumerate(_FUNNEL_COLS):
                _set_cell_text(table.cellAt(0, c), name)
            row_of = {}
            for i, (key, (tag, label)) in enumerate(rows, start=1):
                _set_cell_text(table.cellAt(i, 0), f"[{tag}] {label}")
                for c in range(1, len(_FUNNEL_COLS)):
                    _set_cell_text(table.cellAt(i, c), "—")
                row_of[key] = i
            cursor.movePosition(QTextCursor.End)
            log_widget.setTextCursor(cursor)
            state["table"] = table
            state["row_of"] = row_of
            _stop_timer()
            timer = QTimer(log_widget)
            timer.timeout.connect(_tick)
            timer.start(120)
            state["timer"] = timer

        elif event == "query_batch_done":
            _stop_timer()
            table = state["table"]
            if table is None:
                return
            elapsed = pr._dt(payload.get("elapsed", 0.0))
            for key, count in payload["counts"].items():
                row = state["row_of"].get(key)
                if row is None:
                    continue
                _set_cell_text(table.cellAt(row, 1), str(count))
                _set_cell_text(table.cellAt(row, 5), elapsed)

        elif event == "filter_step":
            table = state["table"]
            if table is None:
                return
            col = _FUNNEL_STEP_COL.get(payload.get("step", ""))
            if col is None:
                return
            before, after = payload["before"], payload["after"]
            for key, a in after.items():
                row = state["row_of"].get(key)
                if row is None:
                    continue
                b = before.get(key, a)
                delta = a - b
                _set_cell_text(table.cellAt(row, col), f"{delta:+d}" if delta else "0")
                _set_cell_text(table.cellAt(row, 4), str(a))

    worker.table.connect(on_table)


# Шаги instrument_cpp.py/instrument_java.py печатают регулярные строки вида
# "[N] текст" / "[5.1] текст" / "[extract] текст" (а также вспомогательные
# строки без тега — warning/совет, отступом). Это subprocess (codeql.exe/
# отдельный python), а не вызов внутри процесса GUI — честного table_cb
# здесь нет, поэтому строим таблицу, парся уже идущий построчно stdout (без
# изменений в самих instrument-скриптах).
_PIPELINE_RE = re.compile(r"^\[([\w.]+)\]\s*(.*)$")


def attach_pipeline_table(log_widget, worker):
    """Таблица шагов инструментации: "Этап | Описание | Время". Каждая
    строка stdout вида "[N] ..." становится отдельной строкой таблицы;
    "Время" — интервал между соседними помеченными строками (между ними и
    идёт реальная работа этого шага). Строки БЕЗ тега (warning/совет с
    отступом, traceback) остаются обычным текстом под таблицей — ПОЛНОСТЬЮ
    заменяет worker.log.connect(self.log.append) для подключённого worker'а."""
    import time as _time

    state = {"table": None, "row": 0, "last_ts": None, "timer": None, "frame": 0,
             "plain_active": False}

    def _stop_timer():
        if state["timer"] is not None:
            state["timer"].stop()
            state["timer"] = None

    def _tick():
        table = state["table"]
        if table is None or state["row"] == 0:
            return
        state["frame"] = (state["frame"] + 1) % len(_SPINNER)
        _set_cell_text(table.cellAt(state["row"], 2), _SPINNER[state["frame"]])

    def _ensure_table():
        if state["table"] is not None:
            return state["table"]
        from PyQt5.QtGui import QTextCursor
        cursor = _new_table_cursor(log_widget)
        table = cursor.insertTable(1, 3, _table_format())
        for c, name in enumerate(["Этап", "Описание", "Время"]):
            _set_cell_text(table.cellAt(0, c), name)
        cursor.movePosition(QTextCursor.End)
        log_widget.setTextCursor(cursor)
        state["table"] = table
        timer = QTimer(log_widget)
        timer.timeout.connect(_tick)
        timer.start(120)
        state["timer"] = timer
        return table

    def _finalize_last_row(now):
        table = state["table"]
        if table is not None and state["row"] > 0 and state["last_ts"] is not None:
            _set_cell_text(table.cellAt(state["row"], 2), pr._dt(now - state["last_ts"]))

    def on_log(text):
        now = _time.perf_counter()
        for line in text.splitlines() if text else []:
            m = _PIPELINE_RE.match(line.strip())
            if not m:
                if line.strip():
                    log_widget.append(line)
                continue
            table = _ensure_table()
            _finalize_last_row(now)
            table.appendRows(1)
            state["row"] += 1
            _set_cell_text(table.cellAt(state["row"], 0), m.group(1))
            _set_cell_text(table.cellAt(state["row"], 1), m.group(2))
            _set_cell_text(table.cellAt(state["row"], 2), _SPINNER[0])
            state["last_ts"] = now

    def on_done(ok, msg):
        _finalize_last_row(_time.perf_counter())
        _stop_timer()

    worker.log.connect(on_log)
    worker.done.connect(on_done)


def _codeql() -> str:
    for c in (third_party("codeql-win", "codeql.exe"), third_party("codeql-linux", "codeql")):
        if c.exists():
            return str(c)
    return "codeql"


def _joern() -> str:
    for c in (
        third_party("joern-cli", "joern.bat"),
        third_party("joern-cli", "joern"),
        third_party("joern-cli", "bin", "joern.bat"),
        third_party("joern-cli", "bin", "joern"),
    ):
        if c.exists():
            return str(c)
    return "joern"


# ─────────────────────────────────────────────────────────────────────────────
# Реестр недавних проектов
# ─────────────────────────────────────────────────────────────────────────────
def load_recent() -> List[dict]:
    try:
        return json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def add_recent(db_path: str, name: str):
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    items = [r for r in load_recent() if r.get("path") != db_path]
    items.insert(0, {"path": db_path, "name": name})
    RECENT_FILE.write_text(json.dumps(items[:15], ensure_ascii=False, indent=2), encoding="utf-8")


def remove_recent(db_path: str):
    """Удаляет запись о проекте из реестра недавних (файлы проекта не трогает)."""
    items = [r for r in load_recent() if r.get("path") != db_path]
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECENT_FILE.write_text(json.dumps(items[:15], ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Рабочие потоки
# ─────────────────────────────────────────────────────────────────────────────
class _Worker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)  # label, current, total
    table = pyqtSignal(str, dict)         # событие воронки (см. attach_funnel_table)
    done = pyqtSignal(bool, str)          # success, message

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self._fn(self.log.emit, self.progress.emit, self.table.emit)  # task(emit, prog, table_cb)
            self.done.emit(True, "OK")
        except Exception as e:
            import traceback
            self.log.emit(traceback.format_exc())
            self.done.emit(False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Стартовое окно: выбор проекта
# ─────────────────────────────────────────────────────────────────────────────
class ProjectPicker(QWidget):
    project_opened = pyqtSignal(object)  # ProjectDB

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CodeQL Analyzer — выбор проекта")
        self.resize(640, 520)
        lay = QVBoxLayout(self)

        title = QLabel("CodeQL Analyzer")
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        btns = QHBoxLayout()
        b_new = QPushButton("➕ Создать проект")
        b_new.clicked.connect(self.create_project)
        b_open = QPushButton("📂 Открыть проект")
        b_open.clicked.connect(self.open_project_dialog)
        btns.addWidget(b_new)
        btns.addWidget(b_open)
        lay.addLayout(btns)

        lay.addWidget(QLabel("История проектов:"))
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(self._open_recent)
        lay.addWidget(self.recent_list)

        hist_btns = QHBoxLayout()
        b_remove = QPushButton("🗑 Удалить из истории")
        b_remove.clicked.connect(self._remove_selected)
        b_clear = QPushButton("Очистить историю")
        b_clear.clicked.connect(self._clear_recent)
        hist_btns.addWidget(b_remove)
        hist_btns.addWidget(b_clear)
        hist_btns.addStretch()
        lay.addLayout(hist_btns)

        self._reload_recent()

    def _reload_recent(self):
        self.recent_list.clear()
        for i, r in enumerate(load_recent(), 1):
            item = QListWidgetItem(f"{i}. {r['name']}  —  {r['path']}")
            item.setData(Qt.UserRole, r["path"])
            self.recent_list.addItem(item)

    def _remove_selected(self):
        item = self.recent_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Удаление", "Выберите проект в списке истории.")
            return
        if QMessageBox.question(
                self, "Удалить из истории",
                f"Убрать проект из истории?\n\n{item.text()}\n\n"
                "Файлы проекта на диске НЕ удаляются.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        remove_recent(item.data(Qt.UserRole))
        self._reload_recent()

    def _clear_recent(self):
        if not load_recent():
            return
        if QMessageBox.question(
                self, "Очистить историю",
                "Удалить все записи из истории проектов?\n\n"
                "Файлы проектов на диске НЕ удаляются.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECENT_FILE.write_text("[]", encoding="utf-8")
        self._reload_recent()

    def create_project(self):
        name, ok = QInputDialog.getText(self, "Новый проект", "Имя проекта:")
        if not ok or not name.strip():
            return
        location = QFileDialog.getExistingDirectory(self, "Где сохранить проект")
        if not location:
            return
        target = Path(location) / name.strip()
        if target.exists():
            QMessageBox.warning(self, "Ошибка", f"Каталог уже существует:\n{target}")
            return
        proj = ProjectDB.create(location, name.strip())
        add_recent(str(proj.db_path), name.strip())
        self.project_opened.emit(proj)

    def open_project_dialog(self):
        f, _ = QFileDialog.getOpenFileName(self, "Открыть project.db", "", "Проект (project.db)")
        if f:
            self._open_path(f)

    def _open_recent(self, item: QListWidgetItem):
        self._open_path(item.data(Qt.UserRole))

    def _open_path(self, path: str):
        try:
            proj = ProjectDB.open(path)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть проект:\n{e}")
            return
        add_recent(str(proj.db_path), proj.get_project().get("name", "project"))
        self.project_opened.emit(proj)


# ─────────────────────────────────────────────────────────────────────────────
# Вкладка статического анализа
# ─────────────────────────────────────────────────────────────────────────────
class StaticTab(QWidget):
    def __init__(self, window: "ProjectWindow"):
        super().__init__()
        self.win = window
        self.proj = window.proj
        self.checks: dict = {}
        self._worker: Optional[_Worker] = None
        self._build()
        self._restore()
        self._on_lang_changed()  # sync label with restored language

    def _build(self):
        lay = QVBoxLayout(self)

        # Кодовая база / директория исходников
        self.db_label = QLabel("Кодовая база CodeQL:")
        lay.addWidget(self.db_label)
        self.db_zone = FileDropZone("Перетащите каталог БД CodeQL или нажмите для выбора",
                                    mode="dir", caption="Выберите каталог CodeQL БД")
        self.db_zone.pathChanged.connect(self._on_db)
        lay.addWidget(self.db_zone)

        # Язык
        row = QHBoxLayout()
        row.addWidget(QLabel("Язык:"))
        self.lang_combo = QComboBox()
        for label, _ in LANGUAGES:
            self.lang_combo.addItem(label)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        row.addWidget(self.lang_combo)
        row.addSpacing(8)
        self.dialect_label = QLabel("Диалект SQL:")
        row.addWidget(self.dialect_label)
        self.dialect_combo = QComboBox()
        for label, code in SQL_DIALECTS:
            self.dialect_combo.addItem(label, code)
        self.dialect_combo.currentIndexChanged.connect(self._on_dialect_changed)
        row.addWidget(self.dialect_combo)
        row.addSpacing(8)
        row.addWidget(QLabel("Блок-схемы:"))
        self.renderer_combo = QComboBox()
        self.renderer_combo.addItem("ELK (стандартный)", "elk")
        self.renderer_combo.addItem("ELK (снизу вверх, ось)", "elk-axis")
        self.renderer_combo.addItem("DRAKON (без зависимостей)", "drakon")
        row.addWidget(self.renderer_combo)
        row.addSpacing(12)
        self.simplified_cb = QCheckBox("Упрощённый вид")
        self.simplified_cb.setToolTip(
            "Заменяет текст узлов типовыми метками:\n"
            "if → Условие, for/while/do → Цикл, try → Обработка исключений\n"
            "Последовательные операторы → Базовый блок")
        row.addWidget(self.simplified_cb)
        row.addStretch()
        lay.addLayout(row)

        # Состав проверок
        checks_group = QGroupBox("Состав проверок (= отчёты)")
        cg = QVBoxLayout(checks_group)
        for group, items in CHECK_GROUPS.items():
            cg.addWidget(QLabel(f"— {group}"))
            for key, label in items:
                cb = QCheckBox(label)
                cb.setChecked(True)
                self.checks[key] = cb
                cg.addWidget(cb)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(checks_group)
        scroll.setMaximumHeight(220)
        lay.addWidget(scroll)

        # Ограничения: RAM (шаг 512), маршруты (шаг 500)
        limits = QGridLayout()
        limits.addWidget(QLabel("ОЗУ (МБ):"), 0, 0)
        self.ram = QSlider(Qt.Horizontal)
        self.ram.setMinimum(512); self.ram.setMaximum(32768)
        self.ram.setSingleStep(512); self.ram.setPageStep(512); self.ram.setTickInterval(512)
        self.ram.setValue(4096)
        self.ram_lbl = QLabel("4096")
        self.ram.valueChanged.connect(lambda v: self._snap(self.ram, v, 512, self.ram_lbl))
        limits.addWidget(self.ram, 0, 1); limits.addWidget(self.ram_lbl, 0, 2)

        limits.addWidget(QLabel("Маршрутов на ФО:"), 1, 0)
        self.routes = QSlider(Qt.Horizontal)
        self.routes.setMinimum(500); self.routes.setMaximum(100000)
        self.routes.setSingleStep(500); self.routes.setPageStep(5000); self.routes.setTickInterval(10000)
        self.routes.setValue(1000)
        self.routes_lbl = QLabel("1000")
        self.routes.valueChanged.connect(lambda v: self._snap(self.routes, v, 500, self.routes_lbl))
        limits.addWidget(self.routes, 1, 1); limits.addWidget(self.routes_lbl, 1, 2)
        lay.addLayout(limits)

        # Фильтры файлов: белый и чёрный списки (по одному шаблону/пути на
        # строку — шаблон с '*'/'?' или точный/относительный путь файла,
        # см. core/file_lists.py). Тот же список передаётся инструментатору
        # (instrument_c_make.py/instrument_cpp.py), чтобы оба этапа видели
        # одно и то же подмножество файлов.
        filt_group = QGroupBox("Фильтры файлов (шаблон ИЛИ путь файла, по одному на строку)")
        fg = QGridLayout(filt_group)
        fg.addWidget(QLabel("Белый список (включить):"), 0, 0)
        self.include_edit = QPlainTextEdit()
        self.include_edit.setPlaceholderText(
            "пусто = все файлы (включая сгенерированные во время сборки)\n"
            "напр.:\n*/src/*\nhotspot/src/share/vm/oops/instanceKlass.cpp")
        self.include_edit.setMaximumHeight(70)
        fg.addWidget(self.include_edit, 1, 0)
        include_load_btn = QPushButton("Загрузить из файла…")
        include_load_btn.clicked.connect(lambda: self._load_file_list(self.include_edit))
        fg.addWidget(include_load_btn, 2, 0)
        fg.addWidget(QLabel("Чёрный список (исключить):"), 0, 1)
        self.exclude_edit = QPlainTextEdit()
        self.exclude_edit.setPlaceholderText(
            "напр.:\n*/test*/*\n*/node_modules/*")
        self.exclude_edit.setMaximumHeight(70)
        fg.addWidget(self.exclude_edit, 1, 1)
        exclude_load_btn = QPushButton("Загрузить из файла…")
        exclude_load_btn.clicked.connect(lambda: self._load_file_list(self.exclude_edit))
        fg.addWidget(exclude_load_btn, 2, 1)
        lay.addWidget(filt_group)

        # Перечень критических ИО (необязательно) — для отчёта Критические_маршруты.csv
        crit_row = QHBoxLayout()
        crit_row.addWidget(QLabel("Перечень критических ИО:"))
        self.critical_io_edit = QLineEdit()
        self.critical_io_edit.setPlaceholderText(
            "необязательно — CSV-подмножество Перечень_ИО.csv (для Критические_маршруты.csv)")
        crit_row.addWidget(self.critical_io_edit, 1)
        crit_btn = QPushButton("Обзор…")
        crit_btn.clicked.connect(self._pick_critical_io)
        crit_row.addWidget(crit_btn)
        lay.addLayout(crit_row)

        # Кнопки
        btns = QHBoxLayout()
        self.run_btn = QPushButton("▶ Запустить статический анализ")
        self.run_btn.clicked.connect(self.run_analysis)
        self.report_btn = QPushButton("📄 Создать отчёты")
        self.report_btn.clicked.connect(self.create_reports)
        btns.addWidget(self.run_btn)
        btns.addWidget(self.report_btn)
        lay.addLayout(btns)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        lay.addWidget(self.log)

    def _snap(self, slider, value, step, label):
        snapped = round(value / step) * step
        if snapped != value:
            slider.blockSignals(True); slider.setValue(snapped); slider.blockSignals(False)
        label.setText(str(snapped))

    @staticmethod
    def _lines(edit) -> list:
        return [ln.strip() for ln in edit.toPlainText().splitlines() if ln.strip()]

    def _on_lang_changed(self, _idx: int = 0):
        lang = LANGUAGES[self.lang_combo.currentIndex()][1]
        if lang == "php":
            self.db_label.setText("Исходники PHP:")
            hint = "Перетащите директорию с .php файлами или нажмите для выбора"
        elif lang == "sql":
            self.db_label.setText("Исходники SQL:")
            hint = "Перетащите директорию с .sql файлами или нажмите для выбора"
        else:
            self.db_label.setText("Кодовая база CodeQL:")
            hint = "Перетащите каталог БД CodeQL или нажмите для выбора"
        self.db_zone._base_label = hint
        if not self.db_zone.path:
            self.db_zone._lbl.setText(hint)
        is_sql = lang == "sql"
        self.dialect_label.setVisible(is_sql)
        self.dialect_combo.setVisible(is_sql)

    def _on_dialect_changed(self, _idx: int = 0):
        lang = LANGUAGES[self.lang_combo.currentIndex()][1]
        if lang == "sql":
            dialect = self.dialect_combo.currentData() or "mysql"
            self.proj.conn.execute(
                "UPDATE project SET sql_dialect=? WHERE id=1", (dialect,))
            self.proj.conn.commit()

    def _on_db(self, path):
        meta_lang = LANGUAGES[self.lang_combo.currentIndex()][1]
        sql_dialect = self.dialect_combo.currentData() if meta_lang == "sql" else ""
        self.proj.conn.execute(
            "UPDATE project SET codeql_db_path=?, language=?, sql_dialect=? WHERE id=1",
            (path, meta_lang, sql_dialect))
        self.proj.conn.commit()

    def _selected_checks(self) -> List[str]:
        return [k for k, cb in self.checks.items() if cb.isChecked()]

    def _restore(self):
        meta = self.proj.get_project()
        if meta.get("codeql_db_path"):
            self.db_zone.set_path_text(meta["codeql_db_path"])
            self.db_zone.path = meta["codeql_db_path"]
        lang = meta.get("language", "cpp")
        for i, (_, code) in enumerate(LANGUAGES):
            if code == lang:
                self.lang_combo.setCurrentIndex(i)
        saved_dialect = meta.get("sql_dialect", "mysql")
        for i, (_, code) in enumerate(SQL_DIALECTS):
            if code == saved_dialect:
                self.dialect_combo.setCurrentIndex(i)
        st = self.proj.get_static_state()
        if st.get("ram_mb"):
            self.ram.setValue(st["ram_mb"]); self.routes.setValue(st["max_routes"])
        if st["selected_checks"]:
            for k, cb in self.checks.items():
                cb.setChecked(k in st["selected_checks"])
        self.simplified_cb.setChecked(bool(st.get("simplified_flowcharts", False)))
        flt = self.proj.get_file_filters()
        if flt["include"]:
            self.include_edit.setPlainText("\n".join(flt["include"]))
        if flt["exclude"]:
            self.exclude_edit.setPlainText("\n".join(flt["exclude"]))
        self._refresh_gating()

    def _refresh_gating(self):
        done = self.proj.get_static_state()["status"] == "done"
        set_locked(self.report_btn, not done, "Сначала выполните статический анализ")

    # ── Действия ─────────────────────────────────────────────────────────────
    def run_analysis(self):
        db_path = self.db_zone.path or self.proj.get_project().get("codeql_db_path")
        lang = LANGUAGES[self.lang_combo.currentIndex()][1]
        if not db_path:
            if lang == "php":
                msg = "Укажите директорию с PHP исходниками."
            elif lang == "sql":
                msg = "Укажите директорию с SQL исходниками."
            else:
                msg = "Укажите кодовую базу CodeQL."
            QMessageBox.warning(self, "Нет пути", msg)
            return
        if lang in ("php", "sql"):
            # For PHP/SQL: just verify the directory exists
            if not Path(db_path).is_dir():
                QMessageBox.warning(self, "Директория не найдена",
                                    f"Директория не существует:\n{db_path}")
                return
        else:
            # For CodeQL languages: verify the database is a valid CodeQL DB
            if not (Path(db_path) / "codeql-database.yml").exists():
                QMessageBox.warning(
                    self, "Это не база CodeQL",
                    f"Каталог не является базой CodeQL (нет codeql-database.yml):\n{db_path}\n\n"
                    "Выберите каталог БД (например examples\\databases\\...\\*-db), "
                    "а не каталог с исходными текстами.")
                return
        self._on_db(db_path)
        ram = self.ram.value(); routes = self.routes.value()
        checks = self._selected_checks()
        include = self._lines(self.include_edit)
        exclude = self._lines(self.exclude_edit)
        self.run_btn.setEnabled(False)
        self.log.append("⏳ Статический анализ запущен…")

        renderer = self.renderer_combo.currentData()
        simplified = self.simplified_cb.isChecked()
        sql_dialect = self.dialect_combo.currentData() if lang == "sql" else "mysql"
        def task(emit, prog=None, table_cb=None):
            # Те же строки передаём и как шаблоны (glob/подстрока), и как
            # точный/относительный список путей (см. core/file_lists.py) —
            # строки без '*'/'?' (типичные пути файлов, напр. загруженные
            # через "Загрузить из файла…") надёжнее матчатся именно как
            # список (совпадение по хвосту на границе '/'), а не как
            # подстрока. Оба механизма комбинируются по ИЛИ, лишний путь не
            # повлияет, если строка реально была шаблоном.
            pr.run_static_analysis(self.proj, codeql_path=_codeql(),
                                   joern_path=_joern(), sql_dialect=sql_dialect,
                                   ram_mb=ram,
                                   max_routes=routes, selected_checks=checks,
                                   flowchart_renderer=renderer,
                                   simplified_flowcharts=simplified,
                                   include_patterns=include, exclude_patterns=exclude,
                                   include_list=include, exclude_list=exclude,
                                   log=emit, progress=prog, table_cb=table_cb)

        self._worker = _Worker(task)
        self._worker.log.connect(self.log.append)
        attach_progress(self.log, self._worker)
        attach_funnel_table(self.log, self._worker)
        self._worker.done.connect(self._analysis_done)
        self._worker.start()

    def _analysis_done(self, ok, msg):
        self.run_btn.setEnabled(True)
        if ok:
            self.log.append("✅ Анализ завершён. Данные сохранены в project.db.")
            self.log.append("ℹ Создайте отчёты, чтобы открыть вкладку «Динамический анализ».")
            self.win.refresh_stats()
            self._refresh_gating()
            self.win.refresh_dynamic_tab_state()
        else:
            self.log.append(f"❌ Ошибка: {msg}")

    def _pick_critical_io(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Перечень критических ИО (CSV)", "", "CSV (*.csv);;Все файлы (*.*)")
        if path:
            self.critical_io_edit.setText(path)

    def _load_file_list(self, target_edit):
        """Загружает текстовый список путей (один на строку, см.
        core/file_lists.py) и дописывает его в указанное текстовое поле
        белого/чёрного списка — пользователь может сформировать такой
        список самостоятельно, не зная точные абсолютные пути build-машины,
        хранящиеся в БД (относительные пути сопоставляются по хвосту)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Список файлов (по одному пути на строку)", "",
            "Текст (*.txt);;Все файлы (*.*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Ошибка чтения", str(e))
            return
        existing = target_edit.toPlainText()
        target_edit.setPlainText((existing + "\n" + text) if existing.strip() else text)

    def create_reports(self):
        if is_locked(self.report_btn):
            QMessageBox.information(self, "Недоступно",
                                    "Сначала выполните статический анализ.")
            return
        self.report_btn.setEnabled(False)
        self.log.append("⏳ Создание отчётов из базы…")
        crit_path = self.critical_io_edit.text().strip() or None

        def task(emit, prog=None, table_cb=None):
            pr.generate_static_reports(self.proj, log=emit, progress=prog,
                                       critical_io_path=crit_path)

        self._worker = _Worker(task)
        self._worker.log.connect(self.log.append)
        attach_progress(self.log, self._worker)
        self._worker.done.connect(self._reports_done)
        self._worker.start()

    def _reports_done(self, ok, msg):
        self.report_btn.setEnabled(True)
        self._refresh_gating()
        self.win.refresh_dynamic_tab_state()
        if ok:
            self.log.append(f"✅ Отчёты созданы: {self.proj.reports_static}")
        else:
            self.log.append(f"❌ Ошибка: {msg}")


def _dynamic_help_html(lang: str, build: bool) -> str:
    """HTML-инструкции по сборке и запуску инструментированного проекта."""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QPalette

    pal = QApplication.instance().palette()
    is_dark = pal.color(QPalette.Base).lightness() < 128

    text_col = pal.color(QPalette.Text).name()
    base_col = pal.color(QPalette.Base).name()
    link_col = pal.color(QPalette.Link).name()
    alt_col  = pal.color(QPalette.AlternateBase).name()

    pre_border  = '#555'  if is_dark else '#ccc'
    note_bg     = '#2d2400' if is_dark else '#fff8e1'
    note_text   = '#ffd060' if is_dark else text_col
    note_border = '#b07800' if is_dark else '#f0a000'
    dim_col     = '#888'  if is_dark else '#666'

    def esc(s: str) -> str:
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    def pre(code: str) -> str:
        return (f'<pre style="background:{alt_col};color:{text_col};padding:6px 10px;'
                f'font-family:monospace;font-size:12px;'
                f'border-left:3px solid {pre_border};margin:4px 0">{esc(code)}</pre>')

    def h3(title: str, is_cur: bool) -> str:
        col = link_col if is_cur else text_col
        badge = (f'&nbsp;<span style="color:{link_col};font-size:11px;'
                 f'border:1px solid {link_col};padding:1px 4px;border-radius:3px">'
                 f'текущий</span>') if is_cur else ''
        return f'<h3 style="color:{col};margin:16px 0 4px 0">{esc(title)}{badge}</h3>'

    def note(html: str) -> str:
        return (f'<p style="background:{note_bg};color:{note_text};padding:6px 10px;'
                f'border-left:3px solid {note_border};margin:4px 0">{html}</p>')

    def step(n: int, html: str) -> str:
        return (f'<p style="margin:6px 0"><b style="color:{dim_col}">Шаг&nbsp;{n}.</b> {html}</p>')

    def trace_note(prefix: str) -> str:
        return (f'<p style="margin:4px 0 8px 0;color:{dim_col};font-size:12px">'
                f'Трасса: <code>~/</code> (Linux/Mac) или '
                f'<code>%USERPROFILE%\\</code> (Windows) → '
                f'<code>{prefix}-ГГГГММДД-ЧЧММСС-&lt;pid&gt;.log</code></p>')

    p = [f'<html><body style="font-family:sans-serif;font-size:13px;'
         f'margin:12px;background:{base_col};color:{text_col}">',
         f'<h2 style="margin:0 0 4px 0;color:{text_col}">'
         f'Запуск инструментированного кода</h2>',
         f'<p style="color:{dim_col};margin:0 0 8px 0;font-size:12px">'
         f'После нажатия «Инструментировать» программа создаёт копию исходников '
         f'с вставленными датчиками. Следуйте инструкции для вашего языка.</p>']

    p.append(note(
        'После сборки/запуска и кнопки «Построить отчёт о покрытии» создаются: '
        '<b>отчёты о покрытии</b> (ФО, ветви, сводка) и <b>сопоставление фактических '
        'маршрутов со статическими</b> — <code>Сопоставление_маршрутов(функций_процедур).csv</code> '
        'и <code>(ветвей).csv</code>. Маршрут по вызовам строится всегда; по ветвям — '
        'только если включена «Инструментация ветвей» и в трассах есть данные о ветвях.'))
    p.append(note(
        '<b>Куда пишутся трассы.</b> Рантаймы C/C++, Python, PHP, Java пишут файл '
        '<code>&lt;lang&gt;-…-&lt;pid&gt;.log</code> в домашний каталог '
        '(<code>HOME</code> / <code>%USERPROFILE%</code>; Java — свойство '
        '<code>user.home</code>). <b>JavaScript — исключение:</b> датчики пишут в '
        'стандартный вывод, его нужно перенаправить в файл (см. раздел JavaScript). '
        'Каталог трасс можно задать, переопределив <code>HOME</code> перед запуском.'))

    # ── C/C++ без своей сборки ────────────────────────────────────────────
    p.append(h3('C/C++ — прямая сборка', lang == 'cpp' and not build))
    p.append(step(1, 'Инструментатор создал копию в <code>instrumented-sources/</code> '
                     'и добавил туда <code>__trace.h</code> и <code>__trace_rt.cpp</code>.'))
    p.append(step(2, 'Соберите программу:'))
    p.append(pre('# Linux / Mac / Windows (MinGW):\n'
                 'cd instrumented-sources\n'
                 'g++ -I. -std=c++14 __trace_rt.cpp *.cpp -lpthread -o program\n\n'
                 '# Windows (MSVC, Developer Command Prompt):\n'
                 'cd instrumented-sources\n'
                 'cl /EHsc /std:c++14 /I. __trace_rt.cpp *.cpp /Fe:program.exe'))
    p.append(step(3, 'Запустите программу — датчики сами запишут трассы.'))
    p.append(trace_note('cpp'))
    p.append(step(4, 'Добавьте файл(ы) трасс через поле «Трассы выполнения» и нажмите '
                     '«Построить отчёт о покрытии».'))
    p.append('<hr>')

    # ── C/C++ со своей сборкой ────────────────────────────────────────────
    p.append(h3('C/C++ — собственная система сборки (make / CMake)', lang == 'cpp' and build))
    p.append(step(1, 'Инструментатор записал <code>__trace.h</code> в корень '
                     '<code>instrumented-sources/</code>. Скопируйте его в системный '
                     'include-путь (обычно <code>/usr/include</code>) — тогда '
                     '<code>#include "__trace.h"</code> найдётся из любого файла проекта '
                     'независимо от <code>-I</code> путей сборки и от того, сколько '
                     'отдельных бинарников (.so/.exe) собирается из исходников.'))
    p.append(step(2, 'Запустите вашу систему сборки в <code>instrumented-sources/</code>:'))
    p.append(pre('sudo cp instrumented-sources/__trace.h /usr/include/__trace.h\n\n'
                 '# make:\ncd instrumented-sources\nmake -j4\n\n'
                 '# CMake:\ncd instrumented-sources && mkdir build && cd build\n'
                 'cmake ..\nmake -j4'))
    p.append(note('Single-header рантайм использует GNU-расширения '
                  '(<code>__attribute__((weak))</code>, <code>__attribute__((cleanup))</code>) '
                  '— нужен <b>GCC или Clang</b> (в т.ч. MinGW на Windows). MSVC/<code>nmake</code> '
                  'этот рантайм не компилирует.'))
    p.append(note('Если сборка не находит <code>__trace.h</code> при нестандартном тулчейне '
                  '(<code>--sysroot</code>, <code>-nostdinc</code> и т.п. отключают поиск '
                  'системных include-путей) — поправьте команды компиляции, добавив '
                  '<code>-I</code> на каталог с заголовком явно.'))
    p.append(step(3, 'Запустите скомпилированную программу, затем добавьте трасс-файлы.'))
    p.append(trace_note('cpp'))
    p.append('<hr>')

    # ── Python ───────────────────────────────────────────────────────────
    p.append(h3('Python', lang == 'python'))
    p.append(step(1, 'Инструментатор скопировал <code>cqtrace.py</code> в '
                     '<code>instrumented-sources/</code> и добавил '
                     '<code>import cqtrace</code> в каждый файл. '
                     'Дополнительная установка не требуется.'))
    p.append(step(2, 'Запустите программу — компиляция не нужна:'))
    p.append(pre('cd instrumented-sources\npython main.py [аргументы]'))
    p.append(trace_note('python'))
    p.append(step(3, 'Добавьте файл(ы) трасс и постройте отчёт о покрытии.'))
    p.append('<hr>')

    # ── JavaScript ────────────────────────────────────────────────────────
    p.append(h3('JavaScript (Node.js)', lang == 'javascript'))
    p.append(step(1, 'Инструментатор скопировал <code>cqtrace.js</code> в '
                     '<code>instrumented-sources/</code> и добавил '
                     '<code>require(\'./cqtrace\')</code> в каждый файл. '
                     'Глобальная установка npm не нужна.'))
    p.append(step(2, 'Запустите через Node.js, перенаправив вывод в файл '
                     '(датчики пишут в stdout, а НЕ в файл в домашнем каталоге):'))
    p.append(pre('cd instrumented-sources\n'
                 '# Linux / Mac / cmd:\n'
                 'node main.js > trace.log\n\n'
                 '# Windows PowerShell — иначе файл будет UTF-16 и не прочитается:\n'
                 'node main.js | Out-File trace.log -Encoding utf8'))
    p.append(note('JavaScript-рантайм выводит трассы в <b>стандартный вывод</b> '
                  '(<code>console.log</code>). В PowerShell оператор <code>&gt;</code> '
                  'создаёт UTF-16 — используйте <code>Out-File -Encoding utf8</code> '
                  'или <code>cmd /c "node main.js &gt; trace.log"</code>. Запускайте '
                  '<b>нативным</b> Node (не Windows-node под WSL).'))
    p.append(step(3, 'Добавьте файл <code>trace.log</code> и постройте отчёт о покрытии.'))
    p.append('<hr>')

    # ── PHP ───────────────────────────────────────────────────────────────
    p.append(h3('PHP', lang == 'php'))
    p.append(note('Joern нужен только на машине анализа (инструментация уже выполнена). '
                  'На целевой ЭВМ достаточно PHP 7.4+.'))
    p.append(step(1, '<code>cqtrace.php</code> уже в корне <code>instrumented-sources/</code>; '
                     'каждый файл содержит '
                     '<code>require_once __DIR__ . \'/cqtrace.php\';</code>.'))
    p.append(step(2, 'Запустите (<code>php</code> должен быть в PATH):'))
    p.append(pre('cd instrumented-sources\nphp main.php [аргументы]'))
    p.append(trace_note('php'))
    p.append(note('Известная проблема: для классов инструментатор может вставить '
                  'датчик класс-уровневого ФО прямо в тело класса '
                  '(<code>$__cqtg_… = cqtrace_fn(…);</code> рядом со свойствами) → '
                  'PHP parse error. Временное решение — удалить такую строку в теле '
                  'класса (датчики внутри методов корректны).'))
    p.append(step(3, 'Добавьте файл(ы) трасс и постройте отчёт о покрытии.'))
    p.append('<hr>')

    # ── Java без своей сборки ─────────────────────────────────────────────
    p.append(h3('Java — прямая компиляция', lang == 'java' and not build))
    p.append(step(1, 'Инструментатор поместил <code>Cqtrace.java</code> '
                     'в пакет проекта внутри <code>instrumented-sources/</code>.'))
    p.append(step(2, 'Скомпилируйте все файлы:'))
    p.append(pre('# Linux / Mac:\ncd instrumented-sources\n'
                 'find . -name "*.java" | xargs javac -cp .\n\n'
                 '# Windows (PowerShell):\ncd instrumented-sources\n'
                 'Get-ChildItem -Recurse -Filter *.java | ForEach-Object { $_.FullName } '
                 '| Out-File files.txt\njavac -cp . @files.txt'))
    p.append(step(3, 'Запустите (<code>-Duser.home</code> задаёт каталог трасс):'))
    p.append(pre('java -Duser.home=. -cp . com.example.MainClass [аргументы]'))
    p.append(note('Java-рантайм пишет трассу в каталог из свойства <code>user.home</code>; '
                  'без <code>-Duser.home</code> — в домашний каталог пользователя. '
                  'Проверено на JDK 25 (javac/java).'))
    p.append(trace_note('java'))
    p.append(step(4, 'Добавьте файл(ы) трасс и постройте отчёт о покрытии.'))
    p.append('<hr>')

    # ── Java со своей сборкой ─────────────────────────────────────────────
    p.append(h3('Java — Maven / Gradle', lang == 'java' and build))
    p.append(step(1, 'При инструментации укажите дополнительные аргументы:'))
    p.append(pre('--cqtrace-package org.example --cqtrace-dir src/main/org/example'))
    p.append(step(2, 'Запустите вашу систему сборки:'))
    p.append(pre('# Maven:\ncd instrumented-sources\nmvn package\n\n'
                 '# Gradle:\ncd instrumented-sources\ngradle build'))
    p.append(step(3, 'Запустите JAR / main-класс, затем добавьте трасс-файлы.'))
    p.append(trace_note('java'))
    p.append('<hr>')

    # ── Результаты ────────────────────────────────────────────────────────
    p.append(h3('Результаты после «Построить отчёт о покрытии»', False))
    p.append('<p style="margin:6px 0">Покрытие: <code>Покрытие_ФО.csv</code>, '
             '<code>Покрытие_ветвей.csv</code>, <code>Сводка_покрытия.csv</code> '
             '(да / нет / не инстр.).</p>')
    p.append('<p style="margin:6px 0">Сопоставление фактических маршрутов со '
             'статическими: <code>Сопоставление_маршрутов(функций_процедур).csv</code> '
             '(цепочки вызовов) и <code>Сопоставление_маршрутов(ветвей).csv</code> '
             '(последовательности ветвей). Колонка «Тип записи»:</p>')
    p.append('<ul style="margin:4px 0 4px 18px">'
             '<li><b>статический</b> — маршрут из статики, отмечается, исполнялся ли;</li>'
             '<li><b>непредусмотренный</b> — реальный путь, которого нет в статике '
             '(комбинированный путь за один прогон, исключения и т.п.);</li>'
             '<li><b>неоднозначно (try)</b> — маршруты, различающиеся лишь исходом '
             '<code>try</code> (по трассе неразличимы).</li></ul>')
    p.append(note('Итерации циклов и прямая рекурсия в фактическом маршруте '
                  '<b>схлопываются</b> (цикл «вошёл», а не «вошёл N раз»), чтобы '
                  'совпадать со статическим базисным маршрутом.'))
    p.append(note('Совет: при создании БД/статики ограничивайте анализ каталогом '
                  'проекта (маска пути), иначе в перечни ФО попадут библиотечные '
                  'и встроенные функции (особенно в JavaScript).'))

    p.append('</body></html>')
    return ''.join(p)


# ─────────────────────────────────────────────────────────────────────────────
# Вкладка динамического анализа
# ─────────────────────────────────────────────────────────────────────────────
class DynamicTab(QWidget):
    def __init__(self, window: "ProjectWindow"):
        super().__init__()
        self.win = window
        self.proj = window.proj
        self._worker: Optional[_Worker] = None
        self._build()
        self.refresh_gating()

    def _build(self):
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Исходные тексты для инструментации:"))
        self.src_zone = FileDropZone("Перетащите каталог исходников или нажмите для выбора",
                                     mode="dir", caption="Каталог исходников")
        self.src_zone.pathChanged.connect(self._on_src)
        lay.addWidget(self.src_zone)

        # Проект со своей сборкой (make/Maven) — влияет на выбор инструментатора
        self.buildsys_cb = QCheckBox("Проект со своей системой сборки (make / Maven)")
        self.buildsys_cb.toggled.connect(self._update_extra_placeholder)
        lay.addWidget(self.buildsys_cb)

        # Доп. аргументы — по чек-боксу, плейсхолдер зависит от языка
        self.extra_cb = QCheckBox("Дополнительные аргументы инструментатора")
        self.extra_cb.toggled.connect(lambda v: self.extra_edit.setVisible(v))
        lay.addWidget(self.extra_cb)
        self.extra_edit = QLineEdit()
        self.extra_edit.setVisible(False)
        lay.addWidget(self.extra_edit)
        self._update_extra_placeholder()

        # Инструментация ветвей
        self.branches_cb = QCheckBox("Инструментация ветвей")
        lay.addWidget(self.branches_cb)

        _irow = QHBoxLayout()
        self.instrument_btn = QPushButton("🔬 Инструментировать")
        self.instrument_btn.clicked.connect(self.instrument)
        _help_btn = QPushButton("?")
        _help_btn.setFixedWidth(28)
        _help_btn.setToolTip("Инструкции по сборке и запуску инструментированного проекта")
        _help_btn.clicked.connect(self._show_help)
        _irow.addWidget(self.instrument_btn)
        _irow.addWidget(_help_btn)
        lay.addLayout(_irow)

        # Трассы
        lay.addWidget(QLabel("Трассы выполнения:"))
        self.trace_zone = FileDropZone("Перетащите файлы трасс или нажмите для выбора",
                                       mode="file", multiple=True,
                                       caption="Выберите трассы", name_filter="Трассы (*.log *.txt)")
        self.trace_zone.filesAdded.connect(self.add_traces)
        lay.addWidget(self.trace_zone)

        # Статистика покрытия
        stats_group = QGroupBox("Покрытие")
        sg = QGridLayout(stats_group)
        sg.addWidget(QLabel("Трасс добавлено:"), 0, 0)
        self.trace_count_lbl = QLabel("0")
        sg.addWidget(self.trace_count_lbl, 0, 1)
        sg.addWidget(QLabel("Покрытие ФО:"), 1, 0)
        self.fo_cov_lbl = QLabel("—")
        sg.addWidget(self.fo_cov_lbl, 1, 1)
        sg.addWidget(QLabel("Покрытие ветвей:"), 2, 0)
        self.br_cov_lbl = QLabel("—")
        sg.addWidget(self.br_cov_lbl, 2, 1)
        lay.addWidget(stats_group)

        _crow = QHBoxLayout()
        self.coverage_btn = QPushButton("📊 Создать отчёты покрытия")
        self.coverage_btn.clicked.connect(self.build_coverage)
        self.reset_coverage_btn = QPushButton("🗑 Обнулить покрытие")
        self.reset_coverage_btn.setToolTip(
            "Удалить все добавленные трассы и отчёты покрытия. "
            "Инструментация проекта не затрагивается.")
        self.reset_coverage_btn.clicked.connect(self._reset_coverage)
        _crow.addWidget(self.coverage_btn)
        _crow.addWidget(self.reset_coverage_btn)
        lay.addLayout(_crow)

        self.log = QTextEdit(); self.log.setReadOnly(True)
        lay.addWidget(self.log)

    def _on_src(self, path):
        # копируем исходники в orig-sources
        pass  # фиксируем путь, копирование при инструментации

    def _update_extra_placeholder(self):
        """Плейсхолдер «Доп. аргументы» — по языку проекта и режиму сборки."""
        lang = self.proj.get_project().get("language", "cpp")
        build = self.buildsys_cb.isChecked()
        if lang == "cpp" and build:
            ph = ("обычно пусто (__trace.h пишется в instrumented-sources/, "
                  "скопируйте его в /usr/include перед сборкой)")
        elif lang == "java" and build:
            ph = ("--cqtrace-package <общий-корень> --cqtrace-dir src/main/<пакет>   "
                  "(напр. --cqtrace-package org.h2 --cqtrace-dir src/main/org/h2)")
        elif lang == "cpp":
            ph = "обычно пусто (датчики и рантайм генерируются автоматически)"
        elif lang == "java":
            ph = "обычно пусто; для своей сборки — отметьте «со своей сборкой»"
        elif lang == "php":
            ph = "обычно пусто; при необходимости --joern <путь к joern>"
        elif lang == "sql":
            ph = "динамическая инструментация SQL не поддерживается"
        else:  # python / javascript
            ph = "обычно пусто; при необходимости --codeql <путь>"
        self.extra_edit.setPlaceholderText(ph)

    def _show_help(self):
        from PyQt5.QtWidgets import QDialog, QTextBrowser, QDialogButtonBox
        lang = self.proj.get_project().get("language", "cpp")
        build = self.buildsys_cb.isChecked()
        dlg = QDialog(self)
        dlg.setWindowTitle("Инструкции: инструментация и запуск")
        dlg.resize(700, 560)
        vlay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setHtml(_dynamic_help_html(lang, build))
        vlay.addWidget(browser)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(dlg.accept)
        vlay.addWidget(bb)
        dlg.exec_()

    def refresh_gating(self):
        # Кнопка инструментации доступна после статического анализа.
        # Недостающий «Перечень ФО» создаётся автоматически при инструментации.
        static_done = self.proj.get_static_state()["status"] == "done"
        set_locked(self.instrument_btn, not static_done,
                   "Сначала выполните статический анализ")
        # Чек-бокс ветвей — только если в статике есть данные по ветвям
        has_br = self.proj.has_branch_reports()
        if not has_br:
            self.branches_cb.setChecked(False)
        set_locked(self.branches_cb, not has_br,
                   "Нет отчётов по ветвям в составе статического анализа")
        self.branches_cb.setEnabled(has_br)
        self._refresh_counts()

    def _refresh_counts(self):
        self.trace_count_lbl.setText(str(self.proj.trace_count()))
        t = self.proj.coverage_totals()
        # else-ветка нужна, иначе после обнуления покрытия (см.
        # _reset_coverage) лейблы остаются со старым значением — счётчик
        # раньше мог только расти, поэтому отсутствие "сброса в —" не
        # проявлялось до появления самого обнуления.
        # Показываем покрыто/инструментировано и рядом — всего по статике:
        # без этого процент считался бы относительно ВСЕХ объектов статики
        # (включая "не инстр." — самодостаточные макросы, идиома CHECK и
        # т.п.), что не совпадало бы с тем, что печатает coverage_report.py
        # в лог (см. dynamic/coverage_report.py).
        if t["fo_total"]:
            self.fo_cov_lbl.setText(
                f"{t['fo_covered']}/{t['fo_instrumented']} (всего по статике {t['fo_total']})")
        else:
            self.fo_cov_lbl.setText("—")
        if t["branch_total"]:
            self.br_cov_lbl.setText(
                f"{t['branch_covered']}/{t['branch_instrumented']} (всего по статике {t['branch_total']})")
        else:
            self.br_cov_lbl.setText("—")

    # ── Действия ─────────────────────────────────────────────────────────────
    def instrument(self):
        lang_now = self.proj.get_project().get("language", "cpp")
        if lang_now == "sql":
            QMessageBox.information(self, "Не применимо",
                                    "Динамическая инструментация SQL-кода не поддерживается.\n"
                                    "SQL хранимые процедуры выполняются на стороне СУБД.")
            return
        if is_locked(self.instrument_btn):
            QMessageBox.information(self, "Недоступно", "Сначала выполните статический анализ.")
            return

        meta = self.proj.get_project()
        lang = meta.get("language", "cpp")

        # Для cpp и java каталог исходников не нужен — инструментатор сам
        # берёт их из src.zip внутри CodeQL БД (точный снэпшот того, что
        # реально анализировал CodeQL, включая файлы, появляющиеся только во
        # время сборки — см. core/file_lists.py). Для остальных языков
        # (php/python/js) копия с диска пока нужна, как и раньше.
        orig = self.proj.orig_sources
        if lang not in ("cpp", "java"):
            if not self.src_zone.path:
                QMessageBox.warning(self, "Нет исходников", "Укажите каталог исходников.")
                return
            # Отчёты статики нужны инструментатору (Перечень_ФО/ветвей)
            if not (self.proj.reports_static / "Перечень_ФО(процедур_функций).csv").exists():
                self.log.append("⏳ Создаю отчёты статики (нужны инструментатору)…")
                pr.generate_static_reports(self.proj, log=self.log.append)
            # Копируем в orig-sources только файлы нужного языка (иерархия сохраняется)
            if Path(self.src_zone.path) != orig:
                sys.path.insert(0, str(ROOT / "dynamic"))
                from src_copy import copy_src_files, LANG_EXTS
                exts = LANG_EXTS.get(lang, set())
                n = copy_src_files(Path(self.src_zone.path), orig, lang)
                self.log.append(f"ℹ Скопировано {n} файлов ({', '.join(sorted(exts)) or 'все'}) → orig-sources")
        else:
            # Отчёты статики нужны инструментатору (Перечень_ФО/ветвей)
            if not (self.proj.reports_static / "Перечень_ФО(процедур_функций).csv").exists():
                self.log.append("⏳ Создаю отчёты статики (нужны инструментатору)…")
                pr.generate_static_reports(self.proj, log=self.log.append)
        build = self.buildsys_cb.isChecked()
        # C++ со своей сборкой → instrument_c_make.py (single-header рантайм)
        if lang == "cpp":
            script = "instrument_c_make.py" if build else "instrument_cpp.py"
        elif lang == "php":
            script = "instrument_php.py"
        else:
            script = {"python": "instrument_py.py", "javascript": "instrument_js.py",
                      "java": "instrument_java.py"}[lang]
        branches = self.branches_cb.isChecked()
        if lang == "php":
            cmd = [sys.executable, str(ROOT / "dynamic" / script),
                   "--project", str(orig), "--db", meta["codeql_db_path"],
                   "--reports", str(self.proj.reports_static),
                   "--out", str(self.proj.src_instrumented),
                   "--joern", _joern(), "--lang", lang,
                   "--pattern", meta.get("pattern", "")]
        elif lang in ("cpp", "java"):
            # Каталог исходников не передаём — instrument_c_make.py/
            # instrument_cpp.py/instrument_java.py извлекают дерево прямо из
            # src.zip БД. Белый/чёрный список файлов — тот же, что
            # использовался для статического анализа (см.
            # apply_file_filters/set_file_filters), чтобы оба этапа видели
            # одно и то же подмножество файлов. Тег трасс = имя проекта +
            # язык: несколько кодовых баз/проектов пишут трассы в один $HOME,
            # префикс не даёт им перепутаться при последующем разборе (см.
            # cqtrace/CQ_LANG для C/C++, LANG в Cqtrace.java для Java).
            _proj_tag = re.sub(r"[^\w.-]+", "_", meta.get("name", "") or lang)
            trace_tag = _proj_tag if _proj_tag.endswith(f"-{lang}") else f"{_proj_tag}-{lang}"
            cmd = [sys.executable, str(ROOT / "dynamic" / script),
                   "--db", meta["codeql_db_path"],
                   "--reports", str(self.proj.reports_static),
                   "--out", str(self.proj.src_instrumented),
                   "--codeql", _codeql(), "--lang", lang,
                   "--trace-tag", trace_tag,
                   "--pattern", meta.get("pattern", "")]
            # Геометрия точек вставки — из сырых данных project.db (раздел
            # 'probe'), без отдельного запроса probe_points.ql к CodeQL-БД.
            # instrument_c_make.py — свой рантайм, эту опцию не принимает.
            if script in ("instrument_cpp.py", "instrument_java.py"):
                cmd += ["--project-db", str(self.proj.db_path)]
            flt = self.proj.get_file_filters()
            if flt.get("include_list"):
                p = self.proj.root / "work" / "include_list.txt"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(flt["include_list"]), encoding="utf-8")
                cmd += ["--include-list", str(p)]
            if flt.get("exclude_list"):
                p = self.proj.root / "work" / "exclude_list.txt"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(flt["exclude_list"]), encoding="utf-8")
                cmd += ["--exclude-list", str(p)]
            # У C/C++ "своя сборка" переключает СКРИПТ (instrument_c_make.py
            # вообще не делает standalone-проверку синтаксиса — её роль
            # выполняет make). instrument_java.py — один скрипт на оба
            # случая, поэтому здесь та же галочка просто гасит javac-проверку:
            # плоский javac по подмножеству файлов после прунинга НЕ может
            # резолвить символы из НЕинструментированных классов того же
            # проекта (см. gosjava: gen_profile_2/3 — намеренные дубликаты
            # профилей JDK-сборки, JDWP.java — модуль не входит в текущий
            # --pattern) — это false positive синтаксис-чекера, а не
            # реальная ошибка вставки датчиков; настоящую сборку выполнит
            # сборочная система проекта (make/Maven/JDK build).
            if lang == "java" and build:
                cmd.append("--no-syntax-check")
        else:
            cmd = [sys.executable, str(ROOT / "dynamic" / script),
                   "--project", str(orig), "--db", meta["codeql_db_path"],
                   "--reports", str(self.proj.reports_static),
                   "--out", str(self.proj.src_instrumented),
                   "--codeql", _codeql(), "--lang", lang,
                   "--pattern", meta.get("pattern", "")]
        if not branches:
            cmd.append("--no-branches")
        if self.extra_cb.isChecked() and self.extra_edit.text().strip():
            cmd += self.extra_edit.text().strip().split()

        self.proj.set_dynamic_state(branches_enabled=branches,
                                    extra_args=self.extra_edit.text().strip())
        self.instrument_btn.setEnabled(False)
        self.log.append("")
        self.log.append("⏳ Инструментация…")
        self._run_subprocess(cmd, self._instrument_done)

    def _instrument_done(self, ok, msg):
        self.instrument_btn.setEnabled(True)
        if ok:
            self.proj.set_dynamic_state(instrumented=True)
            self.log.append(f"✅ Инструментировано → {self.proj.src_instrumented}")
        else:
            self.log.append(f"❌ Ошибка инструментации: {msg}")

    def add_traces(self, files: List[str]):
        self.proj.traces_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            dst = self.proj.traces_dir / Path(f).name
            try:
                shutil.copy2(f, dst)
                lc = sum(1 for _ in open(dst, encoding="utf-8", errors="ignore"))
            except Exception:
                lc = 0
            self.proj.add_trace(Path(f).name, lc)
        self.log.append(f"➕ Добавлено трасс: {len(files)} (всего {self.proj.trace_count()})")
        self._refresh_counts()

    def _reset_coverage(self):
        if self.proj.trace_count() == 0 and self.proj.coverage_totals()["fo_total"] == 0:
            QMessageBox.information(self, "Обнуление покрытия", "Покрытие уже пустое.")
            return
        if QMessageBox.question(
                self, "Обнулить покрытие",
                "Удалить все добавленные трассы и отчёты покрытия?\n\n"
                "Инструментация проекта (src-instrumented) НЕ затрагивается — "
                "повторно инструментировать не нужно, можно сразу добавлять новые трассы.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.proj.clear_dynamic_coverage()
        self.win.refresh_stats()
        self._refresh_counts()
        self.log.append("🗑 Покрытие обнулено: трассы и отчёты покрытия удалены.")

    def build_coverage(self):
        traces = list(self.proj.traces_dir.glob("*"))
        if not traces:
            QMessageBox.warning(self, "Нет трасс", "Сначала добавьте трассы выполнения.")
            return
        sensor_map = self.proj.src_instrumented / "Карта_датчиков.csv"
        if not sensor_map.exists():
            QMessageBox.warning(self, "Нет карты датчиков",
                                "Сначала выполните инструментацию.")
            return
        cmd = [sys.executable, str(ROOT / "dynamic" / "coverage_report.py"),
               "--traces"] + [str(t) for t in traces] + [
               "--reports", str(self.proj.reports_static),
               "--sensor-map", str(sensor_map),
               "--out", str(self.proj.reports_dynamic)]
        self.coverage_btn.setEnabled(False)
        self.log.append("⏳ Построение покрытия…")
        self._run_subprocess(cmd, self._coverage_done)

    def _coverage_done(self, ok, msg):
        if not ok:
            self.coverage_btn.setEnabled(True)
            self.log.append(f"❌ Ошибка покрытия: {msg}")
            return
        self._import_coverage()
        self.proj.set_dynamic_state(status="done")
        self.win.refresh_stats()
        self._refresh_counts()
        self.log.append(f"✅ Отчёты покрытия: {self.proj.reports_dynamic}")
        # Сопоставление фактических маршрутов выполнения со статическими
        traces = [str(t) for t in self.proj.traces_dir.glob("*")]
        cmd = [sys.executable, str(ROOT / "dynamic" / "route_match_report.py"),
               "--traces"] + traces + [
               "--reports", str(self.proj.reports_static),
               "--out", str(self.proj.reports_dynamic)]
        self.log.append("⏳ Сопоставление маршрутов (факт vs статика)…")
        self._run_subprocess(cmd, self._routematch_done)

    def _routematch_done(self, ok, msg):
        self.coverage_btn.setEnabled(True)
        if ok:
            self.log.append(
                "✅ Сопоставление маршрутов: Сопоставление_маршрутов(функций_процедур).csv"
                " + (ветвей).csv (если есть статика и динамика по ветвям) в "
                f"{self.proj.reports_dynamic}")
        else:
            self.log.append(f"⚠ Сопоставление маршрутов не выполнено: {msg}")

    def _import_coverage(self):
        """Импортирует 3 CSV покрытия из reports/dynamic обратно в project.db."""
        import csv
        d = self.proj.reports_dynamic

        def read(name):
            p = d / name
            if not p.exists():
                return []
            with open(p, encoding="utf-8-sig", newline="") as f:
                return list(csv.reader(f, delimiter=";"))[1:]  # без заголовка

        fo = [(r[0], r[1], r[2]) for r in read("Покрытие_ФО.csv") if len(r) >= 3]
        br = [(r[1], r[3], r[4], r[5], r[6], r[7]) for r in read("Покрытие_ветвей.csv") if len(r) >= 8]
        summ = [(r[0], r[1], r[2], r[3], r[4]) for r in read("Сводка_покрытия.csv") if len(r) >= 5]
        self.proj.save_coverage(fo, br, summ)

    # ── subprocess-обёртка в потоке ──────────────────────────────────────────
    def _run_subprocess(self, cmd, on_done):
        def task(emit, prog=None, table_cb=None):
            env = dict(os.environ)
            env["_JAVA_OPTIONS"] = ""
            # Дочерний Python должен печатать/декодировать в UTF-8, иначе
            # русские буквы и символ «→» падают на cp1251-консоли Windows.
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            # Стримим построчно (а не одним capture_output блоком в конце) —
            # инструментация на крупном проекте идёт минуты, без стрима лог
            # молчал бы всё это время; stderr слит в stdout, чтобы сохранить
            # реальный порядок строк относительно друг друга.
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace",
                                  env=env, bufsize=1)
            for line in p.stdout:
                emit(line.rstrip("\n"))
            p.wait()
            if p.returncode != 0:
                raise RuntimeError(f"exit {p.returncode}")
        self._worker = _Worker(task)
        attach_pipeline_table(self.log, self._worker)
        self._worker.done.connect(on_done)
        self._worker.start()


# ─────────────────────────────────────────────────────────────────────────────
# Главное окно проекта
# ─────────────────────────────────────────────────────────────────────────────
class ProjectWindow(QMainWindow):
    exit_to_picker = pyqtSignal()

    def __init__(self, proj: ProjectDB):
        super().__init__()
        self.proj = proj
        meta = proj.get_project()
        self.setWindowTitle(f"CodeQL Analyzer — проект «{meta.get('name','')}»")
        self.resize(900, 760)

        central = QWidget(); self.setCentralWidget(central)
        lay = QVBoxLayout(central)

        # Шапка: имя проекта + статистика + выход
        top = QHBoxLayout()
        self.stats_lbl = QLabel("")
        top.addWidget(self.stats_lbl); top.addStretch()
        exit_btn = QPushButton("⏏ Выход из проекта")
        exit_btn.clicked.connect(self._exit)
        top.addWidget(exit_btn)
        lay.addLayout(top)

        self.tabs = QTabWidget()
        self.static_tab = StaticTab(self)
        self.dynamic_tab = DynamicTab(self)
        self.tabs.addTab(self.static_tab, "Статический анализ")
        self.tabs.addTab(self.dynamic_tab, "Динамический анализ")
        lay.addWidget(self.tabs)
        install_disabled_tab_cursor(self.tabs)

        self.refresh_stats()
        self.refresh_dynamic_tab_state()

    def refresh_dynamic_tab_state(self):
        """Вкладка «Динамический анализ» активна после выполнения статического
        анализа (данные есть в project.db). Недостающий отчёт «Перечень ФО»
        создаётся автоматически при инструментации."""
        idx = self.tabs.indexOf(self.dynamic_tab)
        static_done = self.proj.get_static_state()["status"] == "done"
        self.tabs.setTabEnabled(idx, static_done)
        self.tabs.setTabToolTip(
            idx, "" if static_done else
            "Сначала выполните статический анализ на вкладке «Статический анализ»")
        if static_done:
            self.dynamic_tab.refresh_gating()

    def refresh_stats(self):
        s = self.proj.get_stats()
        parts = []
        if s.get("fo_total"): parts.append(f"ФО: {s['fo_total']}")
        if s.get("io_total"): parts.append(f"ИО: {s['io_total']}")
        if s.get("branches_total"): parts.append(f"ветвей: {s['branches_total']}")
        cov = self.proj.coverage_totals()
        if cov["fo_total"]:
            parts.append(f"покрытие ФО: {cov['fo_covered']}/{cov['fo_total']}")
        self.stats_lbl.setText("   ".join(parts) or "Статистика появится после анализа")

    def _exit(self):
        self.proj.close()
        self.exit_to_picker.emit()
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────
class AppController:
    def __init__(self, app):
        self.app = app
        self.picker = None
        self.window = None
        self.show_picker()

    def show_picker(self):
        self.picker = ProjectPicker()
        self.picker.project_opened.connect(self.open_window)
        self.picker.show()

    def open_window(self, proj):
        self.picker.close()
        self.window = ProjectWindow(proj)
        self.window.exit_to_picker.connect(self.show_picker)
        self.window.show()


def main():
    # Снимаем глобальный лимит памяти JVM, иначе он ограничивает CodeQL 512 МБ
    # и крупные анализы падают по нехватке памяти.
    os.environ.pop("_JAVA_OPTIONS", None)
    # GUI не должен сыпать в консоль: весь пользовательский вывод идёт в виджет
    # журнала через колбэк log/progress. Перенаправляем stdout в «никуда» — это
    # подавляет любые print() из модулей анализа (DEBUG, «Saved: …» и т.п.) и
    # заодно устраняет падение под pythonw (где sys.stdout == None). stderr
    # оставляем, чтобы реальные трейсбеки не терялись.
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
    app = QApplication(sys.argv)
    enable_dragdrop_under_uac()  # разрешить drag-and-drop при запуске от админа (Windows UIPI)
    gui_styles.apply_dark_theme(app)
    # Ссылку на контроллер нужно удержать на всё время работы цикла событий,
    # иначе сборщик мусора уничтожит его вместе с окном и ничего не откроется.
    controller = AppController(app)
    app._controller = controller  # дополнительная страховка от GC
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
