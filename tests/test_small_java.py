"""Регрессионные тесты для малого Java-проекта (small-projects/test-project-java)."""
import pytest
from pathlib import Path
from conftest import (
    find_function, find_functions_by_name, fo_names,
    get_declared_line, get_sig_line, source_line, load_report, ROOT,
    flowcharts_dir,
)


# ── Перечень функциональных объектов ────────────────────────────────────────

class TestFunctionalObjects:

    # Точные строки объявления из отчёта (Calculator.java)
    CALCULATOR_LINES = {
        "Calculator": 7,
        "add":        11,
        "sub":        17,
        "mul":        23,
        "div":        29,
        "power":      38,
        "mod":        47,
        "storeResult": 56,
    }

    def test_calculator_methods_present(self, java_fo):
        names = fo_names(java_fo)
        for m in self.CALCULATOR_LINES:
            assert m in names, f"Calculator.{m} not found"

    @pytest.mark.parametrize("method,expected_line",
                             list(CALCULATOR_LINES.items()))
    def test_calculator_method_exact_line(self, java_fo, java_src, method, expected_line):
        """Каждый метод Calculator объявлен на ожидаемой строке."""
        rows = [r for r in java_fo
                if "Calculator" in r.get("Объявлен в", "")
                and r.get("Объект", "").endswith(f".{method}")]
        assert rows, f"testproject.Calculator.{method} not found"
        line = get_declared_line(rows[0])
        assert line == expected_line, (
            f"Calculator.{method}: expected line {expected_line}, got {line}"
        )
        src = source_line(java_src / "Calculator.java", line)
        assert method in src, f"Line {line} of Calculator.java: {src!r}"

    def test_utils_methods_present(self, java_fo):
        names = fo_names(java_fo)
        for m in ("factorial", "isEven", "sumArray", "isPrime", "gcd"):
            assert m in names

    def test_utils_factorial_line(self, java_fo, java_src):
        rows = [r for r in java_fo if r.get("Объект", "").endswith(".factorial")]
        assert rows
        line = get_declared_line(rows[0])
        src = source_line(java_src / "Utils.java", line)
        assert "factorial" in src.lower(), f"Line {line}: {src!r}"

    def test_main_class_present(self, java_fo):
        assert "main" in fo_names(java_fo)

    def test_counter_methods_present(self, java_fo):
        names = fo_names(java_fo)
        for m in ("increment", "reset", "getValue", "setValue"):
            assert m in names


# ── Сигнатурный анализ ───────────────────────────────────────────────────────

class TestSignatureAnalysis:
    """UnsafeDemo.java: два вызова Runtime.exec на строках 10 и 13."""

    def test_runtime_exec_found(self, java_sig):
        execs = [r for r in java_sig if r.get("Сигнатура", "") == "Runtime.exec"]
        assert len(execs) >= 2, f"Expected ≥2 Runtime.exec, got {len(execs)}"

    def test_runtime_exec_cwe_078(self, java_sig):
        for r in java_sig:
            if r.get("Сигнатура", "") == "Runtime.exec":
                assert r.get("CWE", "") == "CWE-078"

    def test_runtime_exec_line_10(self, java_sig, java_src):
        lines = [get_sig_line(r) for r in java_sig
                 if r.get("Сигнатура", "") == "Runtime.exec"]
        assert 10 in lines, f"Expected Runtime.exec at line 10, got {lines}"
        src = source_line(java_src / "UnsafeDemo.java", 10)
        assert "exec" in src, f"Line 10 of UnsafeDemo.java: {src!r}"

    def test_runtime_exec_line_13(self, java_sig, java_src):
        lines = [get_sig_line(r) for r in java_sig
                 if r.get("Сигнатура", "") == "Runtime.exec"]
        assert 13 in lines, f"Expected Runtime.exec at line 13, got {lines}"
        src = source_line(java_src / "UnsafeDemo.java", 13)
        assert "exec" in src, f"Line 13 of UnsafeDemo.java: {src!r}"

    def test_no_sig_in_calculator(self, java_sig):
        calc_sigs = [r for r in java_sig
                     if "Calculator" in r.get("Модуль", "")]
        assert not calc_sigs


# ── Маршруты выполнения ──────────────────────────────────────────────────────

class TestRoutes:

    def test_div_has_branch(self, java_routes):
        div = [r for r in java_routes
               if r.get("Функциональный объект", "").endswith(".div")]
        assert div, "No routes for Calculator.div"
        routes = {r.get("№ маршрута", "") for r in div}
        assert len(routes) >= 2, f"Calculator.div: expected ≥2 routes, got {routes}"

    def test_factorial_has_branches(self, java_routes):
        fact = [r for r in java_routes
                if r.get("Функциональный объект", "").endswith(".factorial")]
        assert fact, "No routes for factorial"
        routes = {r.get("№ маршрута", "") for r in fact}
        assert len(routes) >= 4, f"factorial: expected ≥4 routes, got {routes}"

    def test_factorial_route_content(self, java_routes):
        """Один из маршрутов factorial должен содержать несколько if-веток."""
        fact = [r for r in java_routes
                if r.get("Функциональный объект", "").endswith(".factorial")]
        route_texts = [r.get("Маршрут", "") for r in fact]
        multi_branch = [t for t in route_texts if "if #2" in t]
        assert multi_branch, f"No multi-branch route in factorial. Routes: {route_texts}"

    def test_main_has_try_branch(self, java_routes):
        main_rows = [r for r in java_routes
                     if r.get("Функциональный объект", "").endswith(".main")]
        assert main_rows, "No routes for main"
        # main имеет try/catch → должна быть ≥1 ветка
        routes = {r.get("№ маршрута", "") for r in main_rows}
        assert len(routes) >= 1


# ── Блок-схемы ───────────────────────────────────────────────────────────────

class TestFlowcharts:

    @pytest.fixture(autouse=True)
    def fc_dir(self):
        return flowcharts_dir("java")

    def test_flowcharts_generated(self, fc_dir):
        svgs = list(fc_dir.glob("*.svg"))
        assert len(svgs) >= 15, f"Expected ≥15 Java SVGs, got {len(svgs)}"

    def test_div_flowchart_exists(self, fc_dir):
        div_svgs = [f for f in fc_dir.glob("*.svg")
                    if "Calculator" in f.name and "div" in f.name]
        assert div_svgs, "No flowchart for Calculator.div"

    def test_factorial_flowchart_exists(self, fc_dir):
        fact_svgs = [f for f in fc_dir.glob("*.svg") if "factorial" in f.name]
        assert fact_svgs, "No flowchart for factorial"

    def test_main_flowchart_exists(self, fc_dir):
        main_svgs = [f for f in fc_dir.glob("*.svg")
                     if f.name.endswith("main.svg") or "Main.main" in f.name]
        assert main_svgs, "No flowchart for Main.main"

    def test_flowchart_not_empty(self, fc_dir):
        for svg in list(fc_dir.glob("*.svg"))[:5]:
            assert svg.stat().st_size > 100, f"{svg.name} appears empty"
