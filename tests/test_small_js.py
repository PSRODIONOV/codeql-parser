"""Регрессионные тесты для малого JavaScript-проекта (small-projects/test-project-js)."""
import pytest
from pathlib import Path
from conftest import (
    find_functions_by_name, fo_names,
    get_declared_line, get_sig_line, source_line, load_report, ROOT,
    flowcharts_dir,
)


# ── Перечень функциональных объектов ────────────────────────────────────────

class TestFunctionalObjects:

    # Точные строки из отчёта (calculator.js)
    CALCULATOR_LINES = {
        "constructor":    7,
        "add":           11,
        "sub":           17,
        "mul":           23,
        "div":           29,
        "power":         38,
        "mod":           47,
        "_storeResult":  56,
    }

    def test_calculator_methods_present(self, js_fo):
        names = fo_names(js_fo)
        for m in ("add", "sub", "mul", "div", "power", "mod"):
            assert m in names, f"Calculator.{m} not found"

    @pytest.mark.parametrize("method,expected_line",
                             list(CALCULATOR_LINES.items()))
    def test_calculator_method_exact_line(self, js_fo, js_src, method, expected_line):
        """Каждый метод Calculator объявлен на ожидаемой строке."""
        rows = [r for r in js_fo
                if r.get("Объявлен в", "").endswith(f"calculator.js({expected_line})")
                and (r.get("Объект", "").endswith(f".{method}")
                     or r.get("Объект", "") == method)]
        assert rows, f"Calculator.{method} not at line {expected_line}"
        src = source_line(js_src / "calculator.js", expected_line)
        assert method in src, f"Line {expected_line} of calculator.js: {src!r}"

    def test_string_processor_methods_present(self, js_fo):
        names = fo_names(js_fo)
        for m in ("toUpper", "toLower", "reverse", "isPalindrome",
                  "contains", "countChars", "wordCount"):
            assert m in names

    def test_word_count_line(self, js_fo, js_src):
        rows = [r for r in js_fo
                if r.get("Объект", "").endswith(".wordCount")]
        assert rows
        line = get_declared_line(rows[0])
        src = source_line(js_src / "stringProcessor.js", line)
        assert "wordCount" in src, f"Line {line}: {src!r}"

    def test_run_unsafe_demo_present(self, js_fo):
        rows = [r for r in js_fo
                if "runUnsafeDemo" in r.get("Объект", "")]
        assert rows, "runUnsafeDemo not found"
        line = get_declared_line(rows[0])
        assert line == 9, f"Expected runUnsafeDemo at line 9, got {line}"

    def test_counter_methods_present(self, js_fo):
        names = fo_names(js_fo)
        # JS Counter uses 'value' (getter) instead of 'getValue'
        for m in ("increment", "reset", "value", "setValue"):
            assert m in names, f"Counter.{m} not found"


# ── Сигнатурный анализ ───────────────────────────────────────────────────────

class TestSignatureAnalysis:
    """unsafeDemo.js: eval (строка 18), new Function (строка 21)."""

    def test_eval_found(self, js_sig):
        evals = [r for r in js_sig if r.get("Сигнатура", "") == "eval"]
        assert evals, "eval not found in JS sig analysis"

    def test_eval_cwe_095(self, js_sig):
        for r in js_sig:
            if r.get("Сигнатура", "") == "eval":
                assert r.get("CWE", "") == "CWE-095"

    def test_eval_exact_line(self, js_sig, js_src):
        evals = [r for r in js_sig if r.get("Сигнатура", "") == "eval"]
        assert evals
        line = get_sig_line(evals[0])
        assert line == 18, f"Expected eval at line 18, got {line}"
        src = source_line(js_src / "unsafeDemo.js", 18)
        assert "eval" in src, f"Line 18 of unsafeDemo.js: {src!r}"

    def test_new_function_found(self, js_sig):
        nf = [r for r in js_sig if r.get("Сигнатура", "") == "new Function"]
        assert nf, "new Function not found"

    def test_new_function_exact_line(self, js_sig, js_src):
        nf = [r for r in js_sig if r.get("Сигнатура", "") == "new Function"]
        assert nf
        line = get_sig_line(nf[0])
        assert line == 21, f"Expected new Function at line 21, got {line}"
        src = source_line(js_src / "unsafeDemo.js", 21)
        assert "Function" in src, f"Line 21 of unsafeDemo.js: {src!r}"

    def test_no_sig_in_calculator(self, js_sig):
        calc_sigs = [r for r in js_sig if "calculator" in r.get("Модуль", "").lower()]
        assert not calc_sigs


# ── Маршруты выполнения ──────────────────────────────────────────────────────

class TestRoutes:

    def test_div_has_branch(self, js_routes):
        div = [r for r in js_routes
               if r.get("Функциональный объект", "").endswith(".div")]
        assert div, "No routes for Calculator.div"
        routes = {r.get("№ маршрута", "") for r in div}
        assert len(routes) >= 2, f"Calculator.div: expected ≥2 routes, got {routes}"

    def test_factorial_has_branches(self, js_routes):
        fact = [r for r in js_routes
                if r.get("Функциональный объект", "") == "factorial"]
        assert fact, "No routes for factorial"
        routes = {r.get("№ маршрута", "") for r in fact}
        assert len(routes) >= 2, f"factorial: expected ≥2 routes, got {routes}"


# ── Блок-схемы ───────────────────────────────────────────────────────────────

class TestFlowcharts:

    @pytest.fixture(autouse=True)
    def fc_dir(self):
        return flowcharts_dir("js")

    def test_flowcharts_generated(self, fc_dir):
        svgs = list(fc_dir.glob("*.svg"))
        assert len(svgs) >= 30, f"Expected ≥30 JS SVGs, got {len(svgs)}"

    def test_div_flowchart_exists(self, fc_dir):
        div_svgs = [f for f in fc_dir.glob("*.svg")
                    if "Calculator" in f.name and "div" in f.name]
        assert div_svgs, "No flowchart for Calculator.div"

    def test_run_unsafe_demo_flowchart_exists(self, fc_dir):
        ud_svgs = [f for f in fc_dir.glob("*.svg")
                   if "runUnsafeDemo" in f.name or "unsafe" in f.name.lower()]
        assert ud_svgs, "No flowchart for runUnsafeDemo"

    def test_flowchart_not_empty(self, fc_dir):
        for svg in list(fc_dir.glob("*.svg"))[:5]:
            assert svg.stat().st_size > 100, f"{svg.name} is suspiciously small"
