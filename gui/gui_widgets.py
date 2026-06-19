"""gui_widgets.py — переиспользуемые виджеты и помощники интерфейса.

1. FileDropZone — зона передачи файла/каталога: и перетаскиванием мышкой,
   и открытием проводника по клику ЛКМ.
2. set_locked(widget, locked, reason) — единый стиль «заблокировано»:
   блеклый вид, курсор-запрет при наведении, тултип с причиной. Действие
   гасится в обработчике (проверкой is_locked), а не через setEnabled —
   чтобы тултип и курсор продолжали работать.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout, QFileDialog


def enable_dragdrop_under_uac():
    """Разрешает drag-and-drop в окно, запущенное от администратора (Windows UIPI).

    Когда процесс работает с высоким уровнем целостности, Windows по умолчанию
    блокирует сообщения перетаскивания из обычного Проводника. Пропускаем
    WM_DROPFILES / WM_COPYDATA / WM_COPYGLOBALDATA через фильтр сообщений.
    Безопасно: на не-Windows или при ошибке — тихо ничего не делает.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        WM_DROPFILES = 0x0233
        WM_COPYDATA = 0x004A
        WM_COPYGLOBALDATA = 0x0049
        MSGFLT_ADD = 1
        user32 = ctypes.windll.user32
        for msg in (WM_DROPFILES, WM_COPYDATA, WM_COPYGLOBALDATA):
            user32.ChangeWindowMessageFilter(msg, MSGFLT_ADD)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Зона передачи файлов: drag-and-drop + клик-проводник
# ─────────────────────────────────────────────────────────────────────────────
class FileDropZone(QFrame):
    """Зона выбора пути. Перетащите файл/каталог мышкой ИЛИ кликните ЛКМ
    для выбора через проводник.

    Параметры:
      mode      — 'dir' | 'file' (что выбирать в проводнике и принимать в drop);
      multiple  — допускать несколько файлов (для трасс); сигнал filesAdded;
      caption   — заголовок диалога проводника;
      name_filter — фильтр файлов проводника, напр. "Трассы (*.log)".

    Сигналы:
      pathChanged(str)      — выбран один путь;
      filesAdded(list)      — добавлены файлы (multiple=True).
    """
    pathChanged = pyqtSignal(str)
    filesAdded = pyqtSignal(list)

    def __init__(self, label: str = "Перетащите сюда или нажмите для выбора",
                 mode: str = "file", multiple: bool = False,
                 caption: str = "", name_filter: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.multiple = multiple
        self.caption = caption or ("Выберите каталог" if mode == "dir" else "Выберите файл")
        self.name_filter = name_filter
        self._base_label = label
        self.path: Optional[str] = None

        self.setObjectName("fileDropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setFrameShape(QFrame.StyledPanel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self._lbl = QLabel(label)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setWordWrap(True)
        lay.addWidget(self._lbl)
        self._apply_style(active=False)

    # ── Внешний вид ──────────────────────────────────────────────────────────
    def _apply_style(self, active: bool):
        # При активном перетаскивании фон светлый (#eef5fc) → текст тёмный;
        # в покое фон прозрачный (тёмная тема) → текст светлый. Принцип:
        # на светлом фоне — тёмный шрифт, на тёмном — светлый.
        if active:
            border, bg, text = "#4a90d9", "#eef5fc", "#1a1a1a"
        else:
            border, bg, text = "#888", "transparent", "#e0e0e0"
        self.setStyleSheet(
            f"#fileDropZone {{ border: 2px dashed {border}; border-radius: 6px; "
            f"background: {bg}; }}"
        )
        if hasattr(self, "_lbl"):
            self._lbl.setStyleSheet(f"color: {text}; background: transparent;")

    def set_path_text(self, text: str):
        self._lbl.setText(text)

    # ── Клик ЛКМ → проводник ─────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.mode == "dir":
            d = QFileDialog.getExistingDirectory(self, self.caption)
            if d:
                self._set_single(d)
        elif self.multiple:
            files, _ = QFileDialog.getOpenFileNames(self, self.caption, "", self.name_filter or "Все файлы (*)")
            if files:
                self._add_files(files)
        else:
            f, _ = QFileDialog.getOpenFileName(self, self.caption, "", self.name_filter or "Все файлы (*)")
            if f:
                self._set_single(f)

    # ── Drag-and-drop ────────────────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_style(active=True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._apply_style(active=False)

    def dropEvent(self, event):
        self._apply_style(active=False)
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
        if not paths:
            return
        if self.multiple:
            # принимаем только файлы (для трасс)
            files = [p for p in paths if Path(p).is_file()]
            if files:
                self._add_files(files)
        else:
            p = paths[0]
            if self.mode == "dir" and not Path(p).is_dir():
                p = str(Path(p).parent)
            self._set_single(p)
        event.acceptProposedAction()

    # ── Внутреннее ───────────────────────────────────────────────────────────
    def _set_single(self, path: str):
        self.path = path
        self._lbl.setText(_elide(path))
        self.pathChanged.emit(path)

    def _add_files(self, files: List[str]):
        self.filesAdded.emit(files)
        self._lbl.setText(f"Добавлено файлов: {len(files)}")


def _elide(path: str, limit: int = 60) -> str:
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


# ─────────────────────────────────────────────────────────────────────────────
# Состояние «заблокировано»: блеклый вид + курсор-запрет + причина
# ─────────────────────────────────────────────────────────────────────────────
def set_locked(widget, locked: bool, reason: str = ""):
    """Включает/снимает визуальное состояние «заблокировано».

    В отличие от setEnabled(False), виджет остаётся включённым (получает hover,
    показывает тултип и курсор-запрет). Само действие должен гасить обработчик
    проверкой is_locked(widget).
    """
    widget.setProperty("locked", locked)
    if locked:
        widget.setCursor(Qt.ForbiddenCursor)
        widget.setToolTip(reason)
    else:
        widget.setCursor(Qt.ArrowCursor)
        widget.setToolTip("")
    # Перечитать QSS-свойство (нужно для динамических property-селекторов)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def is_locked(widget) -> bool:
    return bool(widget.property("locked"))
