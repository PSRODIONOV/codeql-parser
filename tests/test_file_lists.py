"""Тесты core/file_lists.py::sensor_filter_factory — доп. пользовательский
белый/чёрный список ВСТАВКИ ДАТЧИКОВ (вкладка «Динамический анализ»),
настраиваемая альтернатива/дополнение к жёстко заданным в коде исключениям
(напр. _is_bootstrap_path в dynamic/instrument_java.py)."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.file_lists import sensor_filter_factory  # noqa: E402


def test_no_patterns_allows_everything():
    f = sensor_filter_factory(None, None)
    assert f("java/lang/String.java") is True
    assert f("any/random/path.cpp") is True


def test_exclude_pattern_blocks_match():
    f = sensor_filter_factory(None, ["java/lang/ref/*"])
    assert f("java/lang/ref/Reference.java") is False
    assert f("java/lang/String.java") is True


def test_include_pattern_restricts_to_match():
    f = sensor_filter_factory(["*/com/example/*"], None)
    assert f("src/com/example/Foo.java") is True
    assert f("src/org/other/Bar.java") is False


def test_exclude_takes_priority_over_include():
    f = sensor_filter_factory(["*/com/example/*"], ["*/com/example/Bad.java"])
    assert f("src/com/example/Good.java") is True
    assert f("src/com/example/Bad.java") is False
