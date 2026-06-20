"""Общие фикстуры и вспомогательные функции для регрессионных тестов."""
import csv
import os
from pathlib import Path
import pytest

# ── Корень проекта ──────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent


def _first_existing(*candidates: Path) -> Path:
    """Возвращает первый существующий путь (поддержка реорганизации в examples/)."""
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def _reports_dir(lang: str) -> Path:
    return _first_existing(
        ROOT / "reports" / "small-projects" / lang,
        ROOT / "examples" / "reports" / "small-projects" / lang,
        ROOT / "workspace" / f"test-project-{lang}" / "reports" / "static",
    )


def flowcharts_dir(lang: str) -> Path:
    """Каталог блок-схем эталонного малого проекта (для TestFlowcharts)."""
    return _reports_dir(lang) / "flowcharts"


def _src_dir(lang_dir: str) -> Path:
    return _first_existing(
        ROOT / "test-projects" / "small-projects" / lang_dir,
        ROOT / "examples" / "test-projects" / "small-projects" / lang_dir,
        ROOT / "workspace" / lang_dir / "orig-sources",
    )


# ── CSV-загрузчик (разделитель «;», кодировка UTF-8-BOM) ────────────────────
def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        pytest.skip(f"Report not found: {path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def load_routes(lang: str) -> list[dict]:
    """Загрузить маршруты с forward-fill по имени функции.

    Отчёт 'Маршруты_выполнения_ФО(ветвей).csv' использует разреженный формат:
    имя функции ('Функциональный объект') заполняется только в первой строке;
    последующие маршруты той же функции имеют пустое значение.
    """
    path = _reports_dir(lang) / "Маршруты_выполнения_ФО(ветвей).csv"
    rows = load_csv(path)
    last_func = ""
    result = []
    for r in rows:
        func = r.get("Функциональный объект", "").strip()
        if func:
            last_func = func
        else:
            r = dict(r)
            r["Функциональный объект"] = last_func
        result.append(r)
    return result


def load_report(lang: str, filename: str) -> list[dict]:
    return load_csv(_reports_dir(lang) / filename)


# ── Вспомогательные функции поиска ─────────────────────────────────────────

def find_function(rows: list[dict], name: str) -> dict | None:
    """Найти ФО по точному имени (колонка 'Объект')."""
    for r in rows:
        obj = r.get("Объект", "")
        if obj == name or obj.endswith("." + name) or obj.endswith("::" + name):
            return r
    return None


def find_functions_by_name(rows: list[dict], name: str) -> list[dict]:
    """Все ФО, оканчивающиеся на указанное имя."""
    result = []
    for r in rows:
        obj = r.get("Объект", "")
        if obj == name or obj.endswith("." + name) or obj.endswith("::" + name):
            result.append(r)
    return result


def fo_names(rows: list[dict]) -> set[str]:
    """Множество коротких имён всех ФО."""
    names = set()
    for r in rows:
        obj = r.get("Объект", "")
        short = obj.rsplit(".", 1)[-1].rsplit("::", 1)[-1]
        names.add(short)
    return names


def source_line(path: Path, line_no: int) -> str:
    """Вернуть строку исходника (1-based). Пустая строка если файл недоступен."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return lines[line_no - 1].rstrip() if 0 < line_no <= len(lines) else ""
    except OSError:
        return ""


def get_declared_line(fo_row: dict) -> int:
    """Извлечь номер строки объявления из колонки 'Объявлен в': 'path(LINE)'."""
    declared = fo_row.get("Объявлен в", "")
    # Формат: "path/to/file.ext(LINE)"
    if "(" in declared and declared.endswith(")"):
        try:
            return int(declared.rsplit("(", 1)[1].rstrip(")"))
        except ValueError:
            pass
    return 0


def sig_findings(lang: str) -> list[dict]:
    """Загрузить строки сигнатурного анализа (без заголовка)."""
    return load_report(lang, "Сигнатурный_анализ_кода.csv")


def get_sig_line(sig_row: dict) -> int:
    """Номер строки из колонки 'Местоположение': 'path:LINE'."""
    loc = sig_row.get("Местоположение", "")
    if ":" in loc:
        try:
            return int(loc.rsplit(":", 1)[1])
        except ValueError:
            pass
    return 0


# ── Фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def cpp_fo():
    return load_report("cpp", "Перечень_ФО(процедур_функций).csv")

@pytest.fixture(scope="session")
def cpp_sig():
    return sig_findings("cpp")

@pytest.fixture(scope="session")
def cpp_routes():
    return load_routes("cpp")

@pytest.fixture(scope="session")
def cpp_src():
    return _src_dir("test-project-cpp")

# ── Проект ветвей (test-project-cpp-branches) ────────────────────────────────
# Золотые отчёты: reports/small-projects/cpp-branches/ (пути в колонке 'Файл'
# нормализованы до basename). Регрессия для работы с ветвями: определение
# (else-if, switch/case, пустой then, одиночные/однострочные формы, негативы),
# карта датчиков (нумерация case) и покрытие (все ветви исполняются).

@pytest.fixture(scope="session")
def cpp_branches_inventory():
    return load_report("cpp-branches", "Перечень_ветвей.csv")

@pytest.fixture(scope="session")
def cpp_branches_coverage():
    return load_report("cpp-branches", "Покрытие_ветвей.csv")

@pytest.fixture(scope="session")
def cpp_branches_sensors():
    return load_report("cpp-branches", "Карта_датчиков.csv")

@pytest.fixture(scope="session")
def cpp_branches_src():
    return _src_dir("test-project-cpp-branches")

@pytest.fixture(scope="session")
def java_fo():
    return load_report("java", "Перечень_ФО(процедур_функций).csv")

@pytest.fixture(scope="session")
def java_sig():
    return sig_findings("java")

@pytest.fixture(scope="session")
def java_routes():
    return load_routes("java")

@pytest.fixture(scope="session")
def java_src():
    return _src_dir("test-project-java")

@pytest.fixture(scope="session")
def js_fo():
    return load_report("js", "Перечень_ФО(процедур_функций).csv")

@pytest.fixture(scope="session")
def js_sig():
    return sig_findings("js")

@pytest.fixture(scope="session")
def js_routes():
    return load_routes("js")

@pytest.fixture(scope="session")
def js_src():
    return _src_dir("test-project-js")

@pytest.fixture(scope="session")
def py_fo():
    return load_report("python", "Перечень_ФО(процедур_функций).csv")

@pytest.fixture(scope="session")
def py_sig():
    return sig_findings("python")

@pytest.fixture(scope="session")
def py_routes():
    return load_routes("python")

@pytest.fixture(scope="session")
def py_src():
    return _src_dir("test-project-python")
