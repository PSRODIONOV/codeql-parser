"""Регрессионные тесты для малого C++-проекта (small-projects/test-project-cpp).

Каждый тест проверяет конкретный аспект отчётов: имена ФО, точные строки объявления,
наличие ПОК на конкретных строках, маршруты выполнения и наличие блок-схем.
"""
import pytest
from pathlib import Path
from conftest import (
    find_function, find_functions_by_name, fo_names,
    get_declared_line, get_sig_line, source_line, load_report, ROOT,
    flowcharts_dir,
)


# ── Перечень функциональных объектов ────────────────────────────────────────

class TestFunctionalObjects:

    def test_calculator_methods_present(self, cpp_fo):
        names = fo_names(cpp_fo)
        for method in ("add", "sub", "mul", "div", "power", "mod"):
            assert method in names, f"Calculator::{method} not found"

    def test_calculator_add_declared_line(self, cpp_fo, cpp_src):
        """Calculator::add объявлен на строке, содержащей 'add' в calculator.cpp."""
        rows = find_functions_by_name(cpp_fo, "add")
        calc_rows = [r for r in rows if "calculator" in r.get("Объявлен в", "").lower()]
        assert calc_rows, "Calculator::add not found in cpp FO report"
        line = get_declared_line(calc_rows[0])
        assert line > 0
        src = source_line(cpp_src / "calculator.cpp", line)
        assert "add" in src.lower(), f"Line {line} of calculator.cpp: {src!r}"

    def test_calculator_div_declared_line(self, cpp_fo, cpp_src):
        """Calculator::div должен быть строкой с 'div' или 'int div'."""
        rows = find_functions_by_name(cpp_fo, "div")
        calc_rows = [r for r in rows if "calculator" in r.get("Объявлен в", "").lower()]
        assert calc_rows
        line = get_declared_line(calc_rows[0])
        src = source_line(cpp_src / "calculator.cpp", line)
        assert "div" in src.lower(), f"Line {line}: {src!r}"

    def test_utils_functions_present(self, cpp_fo):
        names = fo_names(cpp_fo)
        # C++ small project uses sumVector (not sumArray, unlike Java/JS/Python)
        for fn in ("factorial", "isEven", "sumVector", "isPrime", "gcd"):
            assert fn in names, f"utils::{fn} not found"

    def test_string_processor_methods_present(self, cpp_fo):
        names = fo_names(cpp_fo)
        for m in ("toUpper", "toLower", "reverse", "isPalindrome", "contains"):
            assert m in names, f"StringProcessor::{m} not found"

    def test_unsafe_demo_present(self, cpp_fo):
        rows = find_functions_by_name(cpp_fo, "runUnsafeDemo")
        assert rows, "runUnsafeDemo not found"

    def test_file_storage_methods_present(self, cpp_fo):
        names = fo_names(cpp_fo)
        for m in ("saveCounter", "loadCounter", "appendLog", "readLog"):
            assert m in names, f"FileStorage::{m} not found"


# ── Сигнатурный анализ (ПОК) ────────────────────────────────────────────────

class TestSignatureAnalysis:
    """unsafe_demo.cpp: strcpy/sprintf/system/printf на конкретных строках."""

    EXPECTED = [
        ("strcpy",  "CWE-120", 11),
        ("sprintf", "CWE-120", 14),
        ("system",  "CWE-078", 16),
        ("printf",  "CWE-134", 18),
    ]

    def test_sig_count(self, cpp_sig):
        assert len(cpp_sig) >= 4, f"Expected ≥4 ПОК, got {len(cpp_sig)}"

    @pytest.mark.parametrize("sig,cwe,expected_line", EXPECTED)
    def test_sig_exact_line(self, cpp_sig, cpp_src, sig, cwe, expected_line):
        """Каждый ПОК найден на строке, содержащей его сигнатуру в источнике."""
        matches = [r for r in cpp_sig
                   if r.get("Сигнатура", "") == sig and r.get("CWE", "") == cwe]
        assert matches, f"ПОК {sig}/{cwe} not found"
        lines = [get_sig_line(r) for r in matches]
        assert expected_line in lines, (
            f"{sig}/{cwe}: expected line {expected_line}, got {lines}"
        )
        src = source_line(cpp_src / "unsafe_demo.cpp", expected_line)
        assert sig in src, f"Line {expected_line} of unsafe_demo.cpp: {src!r}"

    def test_no_sig_in_calculator(self, cpp_sig):
        """calculator.cpp не должен содержать ПОК."""
        calc_sigs = [r for r in cpp_sig if "calculator" in r.get("Модуль", "").lower()]
        assert not calc_sigs, f"Unexpected ПОК in calculator: {calc_sigs}"


# ── Маршруты выполнения ──────────────────────────────────────────────────────

class TestRoutes:

    def test_calculator_div_has_branch(self, cpp_routes):
        """Calculator::div имеет ветку (b==0)."""
        div_routes = [r for r in cpp_routes
                      if "div" in r.get("Функциональный объект", "")
                      and "Calculator" in r.get("Функциональный объект", "")]
        assert div_routes, "No routes for Calculator::div"
        route_count = len(set(r.get("№ маршрута", "") for r in div_routes))
        assert route_count >= 2, f"Calculator::div should have ≥2 routes, got {route_count}"

    def test_factorial_has_branches(self, cpp_routes):
        """factorial имеет ≥2 маршрута (n<0, n<=1, цикл)."""
        rows = [r for r in cpp_routes if "factorial" in r.get("Функциональный объект", "")]
        assert rows
        route_count = len(set(r.get("№ маршрута", "") for r in rows))
        assert route_count >= 2


# ── Блок-схемы ───────────────────────────────────────────────────────────────

class TestFlowcharts:

    def test_flowcharts_dir_not_empty(self):
        fc_dir = flowcharts_dir("cpp")
        svgs = list(fc_dir.glob("*.svg"))
        assert svgs, "No SVG flowcharts generated for C++"

    def test_div_flowchart_exists(self):
        fc_dir = flowcharts_dir("cpp")
        div_svgs = [f for f in fc_dir.glob("*.svg") if "div" in f.name.lower()]
        assert div_svgs, "No flowchart for Calculator::div"

    def test_factorial_flowchart_exists(self):
        fc_dir = flowcharts_dir("cpp")
        fact_svgs = [f for f in fc_dir.glob("*.svg") if "factorial" in f.name.lower()]
        assert fact_svgs, "No flowchart for factorial"
