"""
Стили и темы для GUI приложения
"""

# Тёмная тема
DARK_THEME = """
QMainWindow {
    background-color: #1e1e1e;
    color: #e0e0e0;
}

QGroupBox {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 10px;
    color: #e0e0e0;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px 0 3px;
}

QLineEdit, QTextEdit {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
}

QPushButton {
    background-color: #0d47a1;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #1565c0;
}

QPushButton:pressed {
    background-color: #0d3a8f;
}

QPushButton:disabled {
    background-color: #555555;
    color: #aaaaaa;
}

QCheckBox, QLabel, QRadioButton {
    color: #e0e0e0;
}

QProgressBar {
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    text-align: center;
    background-color: #2d2d2d;
}

QProgressBar::chunk {
    background-color: #4CAF50;
    border-radius: 3px;
}

QSlider::groove:horizontal {
    background-color: #3e3e3e;
    height: 8px;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background-color: #0d47a1;
    width: 18px;
    margin: -5px 0;
    border-radius: 9px;
}

QSlider::handle:horizontal:hover {
    background-color: #1565c0;
}

QComboBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
}

QComboBox::drop-down {
    border: none;
}

QComboBox::down-arrow {
    image: url(:/arrow);
}

QListWidget {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
}

QListWidget::item:selected {
    background-color: #0d47a1;
}

QTabWidget::pane {
    border: 1px solid #3e3e3e;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #e0e0e0;
    padding: 6px 20px;
    border: 1px solid #3e3e3e;
}

QTabBar::tab:selected {
    background-color: #0d47a1;
    color: white;
}

QStatusBar {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border-top: 1px solid #3e3e3e;
}

QDialog {
    background-color: #1e1e1e;
    color: #e0e0e0;
}

QMessageBox {
    background-color: #1e1e1e;
}

QMessageBox QLabel {
    color: #e0e0e0;
}

QMessageBox QPushButton {
    min-width: 60px;
    min-height: 30px;
}

/* Состояние «заблокировано» (set_locked из gui_widgets): блеклый вид.
   Виджет остаётся enabled — поэтому показывает тултип-причину и курсор-запрет. */
QPushButton[locked="true"] {
    background-color: #3a3a3a;
    color: #777777;
}
QPushButton[locked="true"]:hover {
    background-color: #3a3a3a;
}
*[locked="true"] {
    color: #777777;
}
QTabBar::tab[locked="true"] {
    color: #777777;
}

/* ── Принцип контраста для ВСЕХ элементов: на тёмном фоне — светлый шрифт.
   Закрываем места, где Qt по умолчанию рисует светлый фон (и светлый текст
   на нём пропадал бы): выпадающие списки, подсказки, области прокрутки. ── */
QWidget {
    color: #e0e0e0;
}
QToolTip {
    color: #e0e0e0;
    background-color: #2d2d2d;
    border: 1px solid #555555;
    padding: 4px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    selection-background-color: #0d47a1;
    selection-color: #ffffff;
    border: 1px solid #3e3e3e;
}
QScrollArea, QScrollArea > QWidget, QAbstractScrollArea {
    background-color: #1e1e1e;
    color: #e0e0e0;
}
QListWidget::item {
    color: #e0e0e0;
}
QListWidget::item:selected {
    color: #ffffff;
}
QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 3px;
}
QInputDialog, QInputDialog QLabel {
    color: #e0e0e0;
}
QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3e3e3e;
}
QMenu::item:selected {
    background-color: #0d47a1;
    color: #ffffff;
}
"""

# Светлая тема
LIGHT_THEME = """
QMainWindow {
    background-color: #f5f5f5;
    color: #212121;
}

QGroupBox {
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 10px;
    color: #212121;
    font-weight: bold;
}

QLineEdit, QTextEdit {
    background-color: white;
    color: #212121;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 5px;
}

QPushButton {
    background-color: #0d47a1;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #1565c0;
}

QProgressBar {
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    background-color: white;
}

QProgressBar::chunk {
    background-color: #4CAF50;
}
"""

def apply_dark_theme(app):
    """Применить тёмную тему"""
    app.setStyle('Fusion')
    app.setStyleSheet(DARK_THEME)

def apply_light_theme(app):
    """Применить светлую тему"""
    app.setStyle('Fusion')
    app.setStyleSheet(LIGHT_THEME)
