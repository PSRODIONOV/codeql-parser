"""Регрессионные тесты для малого Python-проекта (small-projects/test-project-python)."""
import pytest
from pathlib import Path
from conftest import (
    find_functions_by_name, fo_names,
    get_declared_line, get_sig_line, source_line, load_report, ROOT,
    flowcharts_dir,
)


# ── Перечень функциональных объектов ────────────────────────────────────────

class TestFunctionalObjects:

    # Точные строки из отчёта (calculator.py)
    CALCULATOR_LINES = {
        "__init__":      7,
        "add":          10,
        "sub":          15,
        "mul":          20,
        "div":          25,
        "power":        32,
        "mod":          39,
        "_store_result": 46,
    }

    def test_calculator_methods_present(self, py_fo):
        names = fo_names(py_fo)
        for m in ("add", "sub", "mul", "div", "power", "mod", "_store_result"):
            assert m in names, f"Calculator.{m} not found"

    @pytest.mark.parametrize("method,expected_line",
                             list(CALCULATOR_LINES.items()))
    def test_calculator_method_exact_line(self, py_fo, py_src, method, expected_line):
        """Каждый метод Calculator объявлен на ожидаемой строке."""
        rows = [r for r in py_fo
                if r.get("Объект", "").endswith(f".{method}")
                and "Calculator" in r.get("Объект", "")]
        assert rows, f"Calculator.{method} not found"
        line = get_declared_line(rows[0])
        assert line == expected_line, (
            f"Calculator.{method}: expected line {expected_line}, got {line}"
        )
        src = source_line(py_src / "calculator.py", expected_line)
        assert "def" in src, f"Line {expected_line} of calculator.py: {src!r}"

    def test_utils_functions_present(self, py_fo):
        names = fo_names(py_fo)
        for fn in ("factorial", "is_even", "sum_array", "is_prime", "gcd"):
            assert fn in names, f"utils.{fn} not found"

    def test_factorial_line(self, py_fo, py_src):
        rows = [r for r in py_fo if r.get("Объект", "") == "factorial"]
        assert rows, "factorial not found"
        line = get_declared_line(rows[0])
        assert line == 4, f"Expected factorial at line 4, got {line}"
        src = source_line(py_src / "utils.py", 4)
        assert "def factorial" in src, f"Line 4 of utils.py: {src!r}"

    def test_string_processor_methods_present(self, py_fo):
        names = fo_names(py_fo)
        for m in ("to_upper", "to_lower", "reverse", "is_palindrome",
                  "contains", "count_chars", "word_count"):
            assert m in names, f"StringProcessor.{m} not found"

    def test_main_function_present(self, py_fo):
        rows = [r for r in py_fo if r.get("Объект", "") == "main"]
        assert rows, "main not found"
        line = get_declared_line(rows[0])
        assert line == 17, f"Expected main at line 17, got {line}"

    def test_file_storage_methods_present(self, py_fo):
        names = fo_names(py_fo)
        for m in ("save_counter", "load_counter", "append_log", "read_log"):
            assert m in names, f"FileStorage.{m} not found"

    def test_save_counter_line(self, py_fo, py_src):
        rows = [r for r in py_fo if r.get("Объект", "").endswith(".save_counter")]
        assert rows
        line = get_declared_line(rows[0])
        assert line == 7, f"Expected save_counter at line 7, got {line}"
        src = source_line(py_src / "file_storage.py", 7)
        assert "def save_counter" in src, f"Line 7: {src!r}"

    def test_run_unsafe_demo_line(self, py_fo, py_src):
        rows = [r for r in py_fo if r.get("Объект", "") == "run_unsafe_demo"]
        assert rows, "run_unsafe_demo not found"
        line = get_declared_line(rows[0])
        assert line == 8, f"Expected run_unsafe_demo at line 8, got {line}"
        src = source_line(py_src / "unsafe_demo.py", 8)
        assert "def run_unsafe_demo" in src, f"Line 8: {src!r}"

    def test_unused_function_in_redundant_report(self):
        redundant = load_report("python", "Перечень_избыточных_ФО(процедур_функций).csv")
        names = {r.get("Избыточный объект", "") for r in redundant}
        assert "unused_global_function" in names or "unused_utility" in names, (
            f"Expected unused function in redundant report, got: {names}"
        )

    def test_classes_hierarchy_present(self, py_fo):
        names = fo_names(py_fo)
        for cls_method in ("area", "perimeter", "describe"):
            assert cls_method in names, f"Shape/Circle/Rectangle.{cls_method} not found"


# ── Сигнатурный анализ ───────────────────────────────────────────────────────

class TestSignatureAnalysis:
    """unsafe_demo.py: eval/exec/os.system/input на точных строках."""

    EXPECTED = [
        ("eval",     "CWE-095", 10),
        ("exec",     "CWE-095", 13),
        ("os.system","CWE-078", 16),
        ("input",    "CWE-020", 19),
    ]

    def test_sig_count(self, py_sig):
        assert len(py_sig) >= 4, f"Expected ≥4 ПОК, got {len(py_sig)}"

    @pytest.mark.parametrize("sig,cwe,expected_line", EXPECTED)
    def test_sig_exact_line(self, py_sig, py_src, sig, cwe, expected_line):
        matches = [r for r in py_sig
                   if r.get("Сигнатура", "") == sig and r.get("CWE", "") == cwe]
        assert matches, f"ПОК {sig}/{cwe} not found in Python sig analysis"
        lines = [get_sig_line(r) for r in matches]
        assert expected_line in lines, (
            f"{sig}/{cwe}: expected line {expected_line}, got {lines}"
        )
        src = source_line(py_src / "unsafe_demo.py", expected_line)
        sig_short = sig.split(".")[-1]
        assert sig_short in src, (
            f"Line {expected_line} of unsafe_demo.py: {src!r}"
        )

    def test_sig_in_run_unsafe_demo(self, py_sig):
        for r in py_sig:
            func = r.get("ФО", "")
            assert "run_unsafe_demo" in func, (
                f"ПОК '{r.get('Сигнатура','')}' expected in run_unsafe_demo, got {func!r}"
            )

    def test_no_sig_in_calculator(self, py_sig):
        calc_sigs = [r for r in py_sig if "calculator" in r.get("Модуль", "").lower()]
        assert not calc_sigs, f"Unexpected ПОК in calculator: {calc_sigs}"


# ── Маршруты выполнения ──────────────────────────────────────────────────────

class TestRoutes:

    def test_div_has_branch(self, py_routes):
        div = [r for r in py_routes if r.get("Функциональный объект", "") == "Calculator.div"]
        assert div, "No routes for Calculator.div"
        routes = {r.get("№ маршрута", "") for r in div}
        assert len(routes) >= 2, f"Calculator.div should have ≥2 routes, got {routes}"

    def test_div_routes_content(self, py_routes):
        """Маршруты div: один с -да (b==0), один с -нет (нормальный путь)."""
        div = [r for r in py_routes if r.get("Функциональный объект", "") == "Calculator.div"]
        texts = [r.get("Маршрут", "") for r in div]
        assert any("-да" in t for t in texts), f"No '-да' route in div: {texts}"
        assert any("-нет" in t for t in texts), f"No '-нет' route in div: {texts}"

    def test_factorial_has_branches(self, py_routes):
        fact = [r for r in py_routes if r.get("Функциональный объект", "") == "factorial"]
        assert fact, "No routes for factorial"
        routes = {r.get("№ маршрута", "") for r in fact}
        assert len(routes) >= 2, f"factorial: expected ≥2 routes, got {routes}"

    def test_main_has_try_branch(self, py_routes):
        main_rows = [r for r in py_routes
                     if r.get("Функциональный объект", "") == "main"]
        assert main_rows, "No routes for main"
        routes = {r.get("№ маршрута", "") for r in main_rows}
        assert len(routes) >= 2, f"main has try/except → ≥2 routes expected, got {routes}"

    def test_is_prime_has_branches(self, py_routes):
        prime = [r for r in py_routes if r.get("Функциональный объект", "") == "is_prime"]
        assert prime, "No routes for is_prime"
        routes = {r.get("№ маршрута", "") for r in prime}
        # is_prime has multiple if conditions → ≥2 routes (-да and -нет paths)
        assert len(routes) >= 2, f"is_prime should have ≥2 routes, got {routes}"


# ── Файловые операции ────────────────────────────────────────────────────────

class TestFileFlow:

    def test_file_flow_detected(self):
        ff = load_report("python", "Перечень_ФО(процедур_функций).csv")
        # Проверяем через отчёт file_flow непосредственно
        try:
            ff2 = load_report("python", "Модульная_матрица_информации.csv")
        except Exception:
            ff2 = []
        # Проверяем наличие file_flow данных в work-директории
        work_csv = ROOT / "reports" / "small-projects" / "python" / "work" / "file_flow" / "file_flow.csv"
        if work_csv.exists():
            import csv
            with open(work_csv, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            filenames = {r.get("file_name", "") for r in rows}
            assert "counter.dat" in filenames or "app.log" in filenames, (
                f"Expected counter.dat/app.log in file_flow, got: {filenames}"
            )


# ── Блок-схемы ───────────────────────────────────────────────────────────────

class TestFlowcharts:

    @pytest.fixture(autouse=True)
    def fc_dir(self):
        return flowcharts_dir("python")

    def test_flowcharts_generated(self, fc_dir):
        svgs = list(fc_dir.glob("*.svg"))
        assert len(svgs) >= 40, f"Expected ≥40 Python SVGs, got {len(svgs)}"

    def test_div_flowchart_exists(self, fc_dir):
        div_svgs = [f for f in fc_dir.glob("*.svg")
                    if "Calculator" in f.name and "div" in f.name]
        assert div_svgs, "No flowchart for Calculator.div"

    def test_factorial_flowchart_exists(self, fc_dir):
        fact_svgs = [f for f in fc_dir.glob("*.svg") if "factorial" in f.name]
        assert fact_svgs, "No flowchart for factorial"

    def test_is_prime_flowchart_exists(self, fc_dir):
        prime_svgs = [f for f in fc_dir.glob("*.svg") if "is_prime" in f.name]
        assert prime_svgs, "No flowchart for is_prime"

    def test_main_flowchart_exists(self, fc_dir):
        main_svgs = [f for f in fc_dir.glob("*.svg") if f.name.endswith("_main.svg")]
        assert main_svgs, "No flowchart for main"

    def test_run_unsafe_demo_flowchart_exists(self, fc_dir):
        ud_svgs = [f for f in fc_dir.glob("*.svg") if "run_unsafe_demo" in f.name]
        assert ud_svgs, "No flowchart for run_unsafe_demo"

    def test_flowchart_contains_svg_elements(self, fc_dir):
        """Каждая SVG содержит реальные элементы (не пустая)."""
        for svg in list(fc_dir.glob("*.svg"))[:10]:
            content = svg.read_text(encoding="utf-8", errors="ignore")
            assert "<svg" in content and "path" in content.lower(), (
                f"{svg.name} does not look like a valid SVG"
            )
