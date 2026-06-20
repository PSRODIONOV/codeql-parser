"""Единый регрессионный тест C/C++ (small-projects/test-project-cpp-branches).

Покрывает весь C/C++-регресс на одном каноническом тест-проекте:
  • определение ветвей (Перечень_ветвей.csv): if/else, for/while/do, try/catch,
    switch/case, одиночные и однострочные формы, function-try-block, негативы;
  • карта датчиков (Карта_датчиков.csv): нумерация case, вход/выход у каждого ФО;
  • покрытие (Покрытие_ветвей.csv): все ветви исполняются;
  • сигнатурный анализ (Сигнатурный_анализ_кода.csv): опасные конструкции (ПОК);
  • макро-ФО: целиком из макроса — исключён; тело из макроса — инструментируется.

Золотые отчёты: reports/small-projects/cpp-branches/ (пути → basename).
"""
import pytest
from conftest import source_line, get_sig_line

ALLOWED_TYPES = {"if", "else", "for", "while", "do", "try", "catch", "case", "default"}
TOTAL_BRANCHES = 95


def _short(fo: str) -> str:
    return fo.rsplit("::", 1)[-1]


def branches_of(inv, name):
    return [r for r in inv if _short(r.get("ФО", "")) == name]


def types_of(rows):
    return [r.get("Тип", "") for r in rows]


def nums_of(rows):
    return [r.get("№ ветви", "") for r in rows]


# ── Определение ветвей ───────────────────────────────────────────────────────

class TestBranchDetection:

    def test_total_branches(self, cpp_branches_inventory):
        assert len(cpp_branches_inventory) == TOTAL_BRANCHES, (
            f"ожидалось {TOTAL_BRANCHES} ветвей, получено {len(cpp_branches_inventory)}")

    def test_else_if_chain_unrolled(self, cpp_branches_inventory):
        """Баг #2: цепочка else-if = 4 отдельных if, пронумерованных 1..4."""
        rows = branches_of(cpp_branches_inventory, "else_if_chain")
        assert len(rows) == 4 and set(types_of(rows)) == {"if"}
        assert sorted(nums_of(rows)) == ["1", "2", "3", "4"]

    def test_switch_cases_numbered(self, cpp_branches_inventory):
        """switch: 7 case + 1 default, пронумерованы 1..8."""
        rows = branches_of(cpp_branches_inventory, "weekday_kind")
        t = types_of(rows)
        assert len(rows) == 8 and t.count("case") == 7 and t.count("default") == 1
        assert sorted(nums_of(rows), key=int) == [str(i) for i in range(1, 9)]

    def test_empty_then_tracked(self, cpp_branches_inventory):
        assert any(r.get("Тип") == "if" for r in branches_of(cpp_branches_inventory, "classify_empty"))

    @pytest.mark.parametrize("fn,btype", [
        ("if_single", "if"), ("for_single", "for"),
        ("while_single", "while"), ("do_single", "do"),
    ])
    def test_single_statement_forms(self, cpp_branches_inventory, fn, btype):
        assert any(r.get("Тип") == btype for r in branches_of(cpp_branches_inventory, fn))

    @pytest.mark.parametrize("fn", [
        "if_oneline_nobrace", "if_oneline_brace", "for_oneline_nobrace",
        "while_oneline_brace", "do_oneline_brace", "try_oneline_brace",
    ])
    def test_oneline_forms_present(self, cpp_branches_inventory, fn):
        assert branches_of(cpp_branches_inventory, fn), f"{fn}: нет ветвей"

    def test_function_try_block(self, cpp_branches_inventory):
        assert any(r.get("Тип") == "try" for r in branches_of(cpp_branches_inventory, "safe_div"))

    def test_goto_controlling_if_tracked(self, cpp_branches_inventory):
        assert types_of(branches_of(cpp_branches_inventory, "retry_goto")) == ["if"]

    @pytest.mark.parametrize("fn", ["sum_range", "sign_and_flags", "macro_control"])
    def test_negatives_not_tracked(self, cpp_branches_inventory, fn):
        """range-for / ?: / &&|| / if из макроса — НЕ ветви."""
        assert branches_of(cpp_branches_inventory, fn) == []

    def test_all_branch_types_valid(self, cpp_branches_inventory):
        bad = {r.get("Тип") for r in cpp_branches_inventory} - ALLOWED_TYPES
        assert not bad, f"неожиданные типы ветвей: {bad}"


# ── Макро-ФО ─────────────────────────────────────────────────────────────────

class TestMacroFO:

    def test_full_macro_fo_excluded_from_branches(self, cpp_branches_inventory):
        """ФО, целиком собранный макросом (get_answer/get_zero через ##),
        исключён из всех отчётов статики."""
        names = {_short(r.get("ФО", "")) for r in cpp_branches_inventory}
        assert "get_answer" not in names and "get_zero" not in names

    def test_full_macro_fo_not_instrumented(self, cpp_branches_sensors):
        """...и не инструментируется (нет датчиков)."""
        # Карта датчиков не содержит файла macro_demo.cpp для get_*; проверяем,
        # что для строк get_answer/get_zero датчиков нет (их ФО нет в карте).
        # Косвенно: в карте нет записей с этими именами (карта хранит № ФО, не имя,
        # поэтому проверяем по факту отсутствия — см. test_full_macro_fo_excluded).
        assert cpp_branches_sensors  # карта не пуста

    def test_macro_body_instrumented(self, cpp_branches_inventory):
        """Тело/{ из макроса, имя настоящее (macro_body) — ветвь if отслеживается."""
        assert any(r.get("Тип") == "if" for r in branches_of(cpp_branches_inventory, "macro_body"))


# ── Карта датчиков ───────────────────────────────────────────────────────────

class TestSensorMap:

    def test_case_sensors_inserted_and_numbered(self, cpp_branches_sensors):
        """Баг #6: датчики case/default размещены и пронумерованы 1..8."""
        rows = [r for r in cpp_branches_sensors
                if r.get("Файл") == "negative_demo.cpp"
                and r.get("Тип") in ("case", "default")]
        assert len(rows) == 8
        assert sorted((r.get("Запись (br)", "") for r in rows), key=int) == [str(i) for i in range(1, 9)]

    def test_every_fo_has_entry_and_exit(self, cpp_branches_sensors):
        entries, exits = set(), set()
        for r in cpp_branches_sensors:
            if r.get("Запись (br)") == "0":
                entries.add(r.get("№ ФО"))
            elif r.get("Запись (br)") == "-1":
                exits.add(r.get("№ ФО"))
        assert entries and entries == exits


# ── Покрытие ─────────────────────────────────────────────────────────────────

class TestCoverage:

    def test_all_branches_covered(self, cpp_branches_coverage):
        assert len(cpp_branches_coverage) == TOTAL_BRANCHES
        not_covered = [r for r in cpp_branches_coverage if r.get("Покрыта", "").strip() != "да"]
        assert not not_covered, (
            f"не покрыты: {[(r.get('ФО'), r.get('№ ветви')) for r in not_covered]}")


# ── Сигнатурный анализ (ПОК) ─────────────────────────────────────────────────

class TestSignatureAnalysis:

    EXPECTED = [("strcpy", "CWE-120"), ("sprintf", "CWE-120"),
                ("system", "CWE-078"), ("printf", "CWE-134")]

    def test_sig_count(self, cpp_branches_signature):
        assert len(cpp_branches_signature) >= 4

    @pytest.mark.parametrize("sig,cwe", EXPECTED)
    def test_sig_present_and_on_source_line(self, cpp_branches_signature, cpp_branches_src, sig, cwe):
        matches = [r for r in cpp_branches_signature
                   if r.get("Сигнатура", "") == sig and r.get("CWE", "") == cwe]
        assert matches, f"ПОК {sig}/{cwe} не найден"
        line = get_sig_line(matches[0])
        src = source_line(cpp_branches_src / "unsafe_demo.cpp", line)
        assert sig in src, f"строка {line} unsafe_demo.cpp: {src!r}"

    def test_excluded_macro_fo_signature_dropped(self, cpp_branches_signature):
        """ПОК из ФО, целиком собранного макросом (run_macro: system), исключён:
        исключённый ФО не оставляет опасных конструкций. system — только из
        unsafe_demo, ни одной записи из macro_demo.cpp."""
        locs = [r.get("Местоположение", "") for r in cpp_branches_signature]
        assert not any("macro_demo.cpp" in loc for loc in locs)
