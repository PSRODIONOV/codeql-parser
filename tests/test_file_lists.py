"""Тесты core/file_lists.py::sensor_filter_factory — пользовательский
белый/чёрный список ВСТАВКИ ДАТЧИКОВ (вкладка «Динамический анализ»),
настраиваемая замена прежним жёстко заданным в коде исключениям (см.
test_java.py::test_recommended_bootstrap_blacklist_via_sensor_filter)."""
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


def test_counters_track_exclude_and_whitelist_miss():
    """counters — то, что превращается в строку лога "[1.1] Фильтр вставки
    датчиков: исключено чёрным списком N, не подошло белому списку M"
    (см. dynamic/instrument_java.py/instrument_cpp.py/instrument_c_make.py),
    иначе пользователю не видно, сработали ли его шаблоны вообще."""
    counters: dict = {}
    f = sensor_filter_factory(["*/keep/*"], ["*/blocked/*"], counters=counters)
    assert f("src/keep/Foo.java") is True
    assert f("src/blocked/Bar.java") is False
    assert f("src/other/Baz.java") is False  # не попадает в белый список
    assert counters == {"excluded": 1, "not_in_whitelist": 1}


def test_counters_not_mutated_when_none():
    # counters=None (по умолчанию) — функция не должна падать без счётчика.
    f = sensor_filter_factory(None, ["*/blocked/*"])
    assert f("src/blocked/Bar.java") is False
