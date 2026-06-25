"""Регресс: для Java --project-db в instrument_java.py молча читал ПУСТУЮ
таблицу q_probe (project_runner.py никогда не запрашивал probe_points.ql для
языка "java" — _needed.append("probe") был только для cpp/c), и даже если бы
запрашивал — выходные колонки queries/java/probe_points.ql были camelCase
(refLine/openLine/...), а RAW_SCHEMA["q_probe"] в core/project_db.py ждёт
ref_line/ins_line/... — все геометрические колонки сохранились бы как 0.

Эти два теста защищают оба инварианта на будущее, без поднятия реальной
CodeQL БД: 1) каждый язык с queries/<lang>/probe_points.ql действительно
запрашивается project_runner.py; 2) выходные колонки select этого .ql
совпадают (по именам и порядку) с RAW_SCHEMA["q_probe"]."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.project_db import RAW_SCHEMA  # noqa: E402

QUERIES_DIR = ROOT / "queries"
DYNAMIC_DIR = ROOT / "dynamic"
PROJECT_RUNNER_SRC = (ROOT / "core" / "project_runner.py").read_text(encoding="utf-8")


def _languages_reading_probe_from_db() -> list:
    """Языки, чьи инструментаторы умеют читать геометрию из СЫРЫХ ДАННЫХ
    project.db (read_probe_points_from_db) — то есть реально зависят от
    того, что project_runner.py собрал для них набор 'probe'. Сейчас это
    instrument_cpp.py (lang=cpp) и instrument_java.py (lang=java);
    instrument_js.py/instrument_py.py/instrument_php.py читать из project.db
    не умеют вовсе, поэтому их queries/*/probe_points.ql (если есть) пока
    НЕ обязаны совпадать с RAW_SCHEMA/быть собраны — это отдельная задача
    параллели с C++, не часть текущего бага."""
    langs = []
    for f in sorted(DYNAMIC_DIR.glob("instrument_*.py")):
        text = f.read_text(encoding="utf-8")
        if "def read_probe_points_from_db" not in text:
            continue
        m = re.search(r'--lang["\']?,\s*default=["\'](\w+)["\']', text)
        assert m, f"{f}: не нашёл default для --lang"
        langs.append(m.group(1))
    return langs


_LANGS_WITH_PROBE = _languages_reading_probe_from_db()


def _select_columns(ql_text: str) -> list:
    """Возвращает имена итоговых колонок последнего 'select ... order by'
    блока .ql-файла (учитывает алиасы 'X as y' — берёт хвост 'y')."""
    m = re.search(r"\bselect\s+(.*?)\border\s+by\b", ql_text, re.S)
    body = m.group(1) if m else re.search(r"\bselect\s+(.*)", ql_text, re.S).group(1)
    cols = []
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        cols.append(item.split()[-1])
    return cols


def test_every_language_with_probe_query_is_collected():
    """project_runner.py должен запрашивать набор 'probe' для КАЖДОГО языка,
    у которого есть queries/<lang>/probe_points.ql — иначе project.db для
    этого языка остаётся без геометрии, и --project-db в инструментаторе
    молча получает 0 точек вставки (см. gosjava-java: ФО 137365, точек 0)."""
    assert _LANGS_WITH_PROBE, "не нашлось ни одного queries/*/probe_points.ql"
    m = re.search(r'_needed\.append\("probe"\)', PROJECT_RUNNER_SRC)
    assert m, "core/project_runner.py больше не собирает набор 'probe' вовсе"
    gate_line = PROJECT_RUNNER_SRC[:m.start()].rsplit("\n", 1)[-1] + \
        PROJECT_RUNNER_SRC[m.start():].split("\n", 1)[0]
    for lang in _LANGS_WITH_PROBE:
        assert f'"{lang}"' in gate_line, (
            f"queries/{lang}/probe_points.ql существует, но project_runner.py "
            f"не запрашивает для него 'probe' (условие: {gate_line.strip()!r})"
        )


def test_probe_query_columns_match_raw_schema():
    """Колонки select в каждом probe_points.ql должны совпадать (имя и
    порядок) с RAW_SCHEMA['q_probe'] — это ЕДИНАЯ таблица project.db,
    общая для всех языков (см. core/project_db.py)."""
    expected = RAW_SCHEMA["q_probe"]
    for lang in _LANGS_WITH_PROBE:
        ql_path = QUERIES_DIR / lang / "probe_points.ql"
        cols = _select_columns(ql_path.read_text(encoding="utf-8"))
        assert cols == expected, (
            f"{ql_path}: колонки select {cols} != RAW_SCHEMA['q_probe'] {expected}"
        )
