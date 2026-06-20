"""Регрессионные тесты работы с ветвями (small-projects/test-project-cpp-branches).

Проверяют ИМЕННО то, что дорабатывалось/чинилось по ветвям:
  • определение ветвей в Перечень_ветвей.csv:
      - цепочка else-if разворачивается в отдельные if (баг #2);
      - switch: каждая метка case/default — отдельная пронумерованная ветвь;
      - пустой then, одиночные и однострочные формы — отслеживаются;
      - негативы (range-for, ?:, &&/||, if из макроса) — НЕ отслеживаются;
  • карта датчиков Карта_датчиков.csv:
      - датчики case/default вставлены и пронумерованы (баг #6 — вставка «direct»);
      - у каждого ФО есть датчик входа(0)/выхода(-1);
  • покрытие Покрытие_ветвей.csv: все ветви исполняются (94/94).

Золотые отчёты: reports/small-projects/cpp-branches/ (Файл нормализован до basename).
"""
import pytest

ALLOWED_TYPES = {"if", "else", "for", "while", "do", "try", "catch", "case", "default"}


def _short(fo: str) -> str:
    return fo.rsplit("::", 1)[-1]


def branches_of(inv, name):
    """Все ветви ФО по короткому имени (else_if_chain, Pipeline::process → process)."""
    return [r for r in inv if _short(r.get("ФО", "")) == name]


def types_of(rows):
    return [r.get("Тип", "") for r in rows]


def nums_of(rows):
    return [r.get("№ ветви", "") for r in rows]


# ── Определение ветвей ───────────────────────────────────────────────────────

class TestBranchDetection:

    def test_total_branches(self, cpp_branches_inventory):
        """В проекте ровно 94 отслеживаемые ветви."""
        assert len(cpp_branches_inventory) == 94, (
            f"Ожидалось 94 ветви, получено {len(cpp_branches_inventory)}")

    def test_else_if_chain_unrolled(self, cpp_branches_inventory):
        """Баг #2: цепочка else-if = 4 отдельных if, пронумерованных 1..4."""
        rows = branches_of(cpp_branches_inventory, "else_if_chain")
        assert len(rows) == 4, f"else_if_chain: ожидалось 4 ветви, {len(rows)}"
        assert set(types_of(rows)) == {"if"}, f"типы: {types_of(rows)}"
        assert sorted(nums_of(rows)) == ["1", "2", "3", "4"], nums_of(rows)

    def test_switch_cases_numbered(self, cpp_branches_inventory):
        """switch: 7 case + 1 default, пронумерованы 1..8 (нумерация меток)."""
        rows = branches_of(cpp_branches_inventory, "weekday_kind")
        assert len(rows) == 8, f"weekday_kind: ожидалось 8 ветвей, {len(rows)}"
        t = types_of(rows)
        assert t.count("case") == 7 and t.count("default") == 1, t
        assert sorted(nums_of(rows), key=int) == [str(i) for i in range(1, 9)]

    def test_empty_then_tracked(self, cpp_branches_inventory):
        """Пустой then (`if (x>0) ; else ...`) отслеживается как if-ветвь."""
        rows = branches_of(cpp_branches_inventory, "classify_empty")
        assert any(r.get("Тип") == "if" for r in rows), rows

    @pytest.mark.parametrize("fn,btype", [
        ("if_single", "if"), ("for_single", "for"),
        ("while_single", "while"), ("do_single", "do"),
    ])
    def test_single_statement_forms(self, cpp_branches_inventory, fn, btype):
        """Одиночный оператор без {} в теле ветви — отслеживается."""
        rows = branches_of(cpp_branches_inventory, fn)
        assert any(r.get("Тип") == btype for r in rows), (fn, types_of(rows))

    @pytest.mark.parametrize("fn", [
        "if_oneline_nobrace", "if_oneline_brace", "for_oneline_nobrace",
        "while_oneline_brace", "do_oneline_brace", "try_oneline_brace",
    ])
    def test_oneline_forms_present(self, cpp_branches_inventory, fn):
        """Заголовок и тело на одной строке (с {} и без) — отслеживается."""
        assert branches_of(cpp_branches_inventory, fn), f"{fn}: нет ветвей"

    def test_function_try_block(self, cpp_branches_inventory):
        """function-try-block (`int f(...) try {...} catch`) даёт ветвь try."""
        rows = branches_of(cpp_branches_inventory, "safe_div")
        assert any(r.get("Тип") == "try" for r in rows), types_of(rows)

    def test_goto_controlling_if_tracked(self, cpp_branches_inventory):
        """В retry_goto сам goto не ветвь, но управляющий им if — отслеживается."""
        rows = branches_of(cpp_branches_inventory, "retry_goto")
        assert types_of(rows) == ["if"], types_of(rows)

    @pytest.mark.parametrize("fn", ["sum_range", "sign_and_flags", "macro_control"])
    def test_negatives_not_tracked(self, cpp_branches_inventory, fn):
        """range-for / тернарный ?: / &&|| / if из макроса — НЕ ветви."""
        assert branches_of(cpp_branches_inventory, fn) == [], (
            f"{fn}: ожидалось 0 ветвей")

    def test_all_branch_types_valid(self, cpp_branches_inventory):
        """Все типы ветвей — из множества отслеживаемых конструкций."""
        bad = {r.get("Тип") for r in cpp_branches_inventory} - ALLOWED_TYPES
        assert not bad, f"неожиданные типы ветвей: {bad}"


# ── Карта датчиков ───────────────────────────────────────────────────────────

class TestSensorMap:

    def test_case_sensors_inserted_and_numbered(self, cpp_branches_sensors):
        """Баг #6: датчики case/default размещены и пронумерованы 1..8."""
        rows = [r for r in cpp_branches_sensors
                if r.get("Файл") == "negative_demo.cpp"
                and r.get("Тип") in ("case", "default")]
        assert len(rows) == 8, f"датчиков case/default: {len(rows)} (ожидалось 8)"
        nums = sorted((r.get("Запись (br)", "") for r in rows), key=int)
        assert nums == [str(i) for i in range(1, 9)], nums

    def test_every_fo_has_entry_and_exit(self, cpp_branches_sensors):
        """У каждого ФО есть датчик входа (0) и выхода (-1)."""
        entries, exits = {}, {}
        for r in cpp_branches_sensors:
            fo = r.get("№ ФО", "")
            br = r.get("Запись (br)", "")
            if br == "0":
                entries[fo] = True
            elif br == "-1":
                exits[fo] = True
        assert entries and entries.keys() == exits.keys(), (
            f"вход без выхода или наоборот: {set(entries) ^ set(exits)}")


# ── Покрытие ─────────────────────────────────────────────────────────────────

class TestCoverage:

    def test_all_branches_covered(self, cpp_branches_coverage):
        """Все 94 ветви исполняются (Покрыта = да) — main прогоняет все пути."""
        assert len(cpp_branches_coverage) == 94
        not_covered = [r for r in cpp_branches_coverage
                       if r.get("Покрыта", "").strip() != "да"]
        assert not not_covered, (
            f"не покрыты: {[(r.get('ФО'), r.get('№ ветви')) for r in not_covered]}")
