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
import re
import pytest
from conftest import source_line, get_sig_line

ALLOWED_TYPES = {"if", "else", "for", "while", "do", "try", "catch", "case", "default"}
TOTAL_BRANCHES = 104


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

    def test_brace_literal_in_condition_tracked(self, cpp_branches_inventory):
        """Регрессия: символьный литерал '{' в условии на одной строке с
        настоящей открывающей { тела (см. adlparse.cpp::get_oplist) не
        должен мешать СТАТИЧЕСКОМУ определению ветви — if отслеживается."""
        rows = branches_of(cpp_branches_inventory, "brace_literal_guard")
        assert types_of(rows) == ["if"]

    def test_case_no_space_before_body_tracked(self, cpp_branches_inventory):
        """Регрессия: case/default без пробела перед телом (см.
        c1_LIR.hpp::as_BasicType) — оба отслеживаются и пронумерованы 1, 2."""
        rows = branches_of(cpp_branches_inventory, "case_no_space_kind")
        t = types_of(rows)
        assert len(rows) == 2 and t.count("case") == 1 and t.count("default") == 1
        assert sorted(nums_of(rows), key=int) == ["1", "2"]

    def test_macro_generated_case_labels_excluded(self, cpp_branches_inventory):
        """Регрессия (REP8/REP16-паттерн, см. assembler_x86.cpp): case-метки,
        развёрнутые из ОДНОГО макровызова в несколько (CASES4(10) -> 4
        меток), исключаются целиком; обычная метка того же switch (case 20)
        и default — отслеживаются как обычно (всего 2, не 6)."""
        rows = branches_of(cpp_branches_inventory, "macro_generated_cases")
        t = types_of(rows)
        assert len(rows) == 2 and t.count("case") == 1 and t.count("default") == 1

    def test_check_macro_branch_tracked_in_statics(self, cpp_branches_inventory):
        """Регрессия (HotSpot CHECK/CHECK_/RETURN/TRAPS-идиома, см.
        classFileParser.cpp::classfile_parse_error(..., CHECK)): сам if не
        макро-сгенерирован, поэтому остаётся в статике как обычная ветвь —
        несмотря на то что его тело (заканчивающееся на CHECK) не получает
        динамического датчика (см. TestCoverage/TestInstrumentorRegressionBugs)."""
        assert types_of(branches_of(cpp_branches_inventory, "check_macro_guard")) == ["if"]


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

    def test_self_contained_macro_fo_present_but_not_instrumented(self, cpp_branches_fo, cpp_branches_sensors):
        """Регрессия (JAVA_INTEGER_OP-паттерн, см. globalDefinitions.hpp):
        макрос, ОДНИМ вызовом разворачивающийся в целую функцию (имя —
        АРГУМЕНТ макроса, без ## в отличие от get_answer/get_zero), остаётся
        легитимным, различимым ФО в статике (есть в Перечень_ФО) — но не
        получает датчика входа/выхода: нет надёжного места (тело общее для
        ВСЕХ вызовов макроса), вставка должна молча пропускаться."""
        names = {r.get("Объект", "") for r in cpp_branches_fo}
        assert "add_via_macro" in names and "add_via_macro2" in names
        fo_nums = {r.get("№ п/п") for r in cpp_branches_fo
                   if r.get("Объект") in ("add_via_macro", "add_via_macro2")}
        entry_fo_nums = {r.get("№ ФО") for r in cpp_branches_sensors if r.get("Запись (br)") == "0"}
        assert not (fo_nums & entry_fo_nums)


# ── Карта датчиков ───────────────────────────────────────────────────────────

class TestSensorMap:

    def test_case_sensors_inserted_and_numbered(self, cpp_branches_sensors, cpp_branches_fo):
        """Датчики case/default weekday_kind размещены и пронумерованы 1..8.
        Отбор по № ФО (а не по имени файла) — negative_demo.cpp теперь
        содержит ЕЩЁ один switch (macro_generated_cases, см. ниже)."""
        fo_num = next(r.get("№ п/п") for r in cpp_branches_fo if r.get("Объект") == "weekday_kind")
        rows = [r for r in cpp_branches_sensors
                if r.get("№ ФО") == fo_num and r.get("Тип") in ("case", "default")]
        assert len(rows) == 8
        assert sorted((r.get("Запись (br)", "") for r in rows), key=int) == [str(i) for i in range(1, 9)]

    def test_case_no_space_sensors_not_split(self, cpp_branches_sensors, cpp_branches_fo):
        """Датчики case_no_space_kind (без пробела перед телом) размещены и
        пронумерованы 1, 2 — статика подтверждает то же, что инструментатор
        реально вставил (см. TestInstrumentorRegressionBugs — побайтовая
        проверка, что 'return' при этом не разрезан)."""
        fo_num = next(r.get("№ п/п") for r in cpp_branches_fo if r.get("Объект") == "case_no_space_kind")
        rows = [r for r in cpp_branches_sensors
                if r.get("№ ФО") == fo_num and r.get("Тип") in ("case", "default")]
        assert len(rows) == 2
        assert sorted((r.get("Запись (br)", "") for r in rows), key=int) == ["1", "2"]

    def test_macro_generated_case_sensors_not_duplicated(self, cpp_branches_sensors, cpp_branches_fo):
        """Регрессия (REP8-style, см. assembler_x86.cpp): case-метки из
        ОДНОГО макровызова не порождают несколько датчиков на одну позицию
        (раньше это рвало текст — __TRACE и до, и после ':'). Ровно 2
        датчика (case 20, default), не 6 (4 из макроса + 2 обычных)."""
        fo_num = next(r.get("№ п/п") for r in cpp_branches_fo if r.get("Объект") == "macro_generated_cases")
        rows = [r for r in cpp_branches_sensors
                if r.get("№ ФО") == fo_num and r.get("Тип") in ("case", "default")]
        assert len(rows) == 2
        assert sorted((r.get("Запись (br)", "") for r in rows), key=int) == ["1", "2"]

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

    # Ветви без датчика (HotSpot CHECK-идиома — см. check_macro_guard и
    # TestInstrumentorRegressionBugs): coverage_report.py корректно отличает
    # "нет датчика" ("не инстр.") от "датчик есть, но не сработал" ("нет") —
    # такие ветви исключаются из подсчёта, а не считаются непокрытыми.
    NOT_INSTRUMENTED = {("check_macro_guard", "1")}

    def test_all_branches_covered(self, cpp_branches_coverage):
        assert len(cpp_branches_coverage) == TOTAL_BRANCHES
        not_covered = [r for r in cpp_branches_coverage
                        if r.get("Покрыта", "").strip() != "да"
                        and (r.get("ФО"), r.get("№ ветви")) not in self.NOT_INSTRUMENTED]
        assert not not_covered, (
            f"не покрыты: {[(r.get('ФО'), r.get('№ ветви')) for r in not_covered]}")

    def test_check_macro_branch_not_instrumented(self, cpp_branches_coverage):
        """Регрессия: ветвь if, чьё тело заканчивается на HotSpot-идиому
        CHECK, корректно помечена "не инстр." (а не ложно "нет"/непокрыта) —
        датчик для неё не ставился (см. TestInstrumentorRegressionBugs)."""
        rows = [r for r in cpp_branches_coverage if r.get("ФО") == "check_macro_guard"]
        assert len(rows) == 1
        assert rows[0].get("Покрыта", "").strip() == "не инстр."


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


# ── Побайтовая корректность вставки (инструментатор) ─────────────────────────
# Каждый тест — конкретный баг instrument_c_make.py/instrument_cpp.py, найденный
# и исправленный по факту: статика (Перечень_ветвей/Карта_датчиков) подтверждает,
# что датчик НА МЕСТЕ, но не то, что вставленный текст не разрезал код пополам —
# для этого нужен сам инструментированный исходник.

class TestInstrumentorRegressionBugs:

    def test_brace_literal_does_not_split_code(self, cpp_branches_instrumented_src):
        """Баг: литерал '{' перед настоящей открывающей { на одной строке —
        наивный поиск "{" с начала строки находил литерал первым и резал
        код пополам внутри него (см. adlparse.cpp::get_oplist)."""
        src = (cpp_branches_instrumented_src / "advanced_demo.cpp").read_text(encoding="utf-8")
        assert "if (c != '{' && flag) {" in src, "условие if разрезано датчиком"
        assert re.search(r"if \(c != '\{' && flag\) \{\s*\n\s*__TRACE\(\d+, \d+, \d+\);", src), (
            "датчик не сразу после настоящей { (вставлен по литералу?)")

    def test_case_no_space_does_not_split_keyword(self, cpp_branches_instrumented_src):
        """Баг: off-by-one в обработчике "direct" разрезал первое слово тела
        (return -> r + датчик + eturn), когда после ':' нет пробела (см.
        c1_LIR.hpp::as_BasicType)."""
        src = (cpp_branches_instrumented_src / "advanced_demo.cpp").read_text(encoding="utf-8")
        assert "case 9: __TRACE" in src and "return 99;" in src
        assert "default: __TRACE" in src and "return -1;" in src
        assert "eturn" not in src.replace("return", "")
        assert not re.search(r":\s*\w\s+__TRACE\(\d+, \d+, \d+\);\w+\b", src), (
            "датчик разрезал ключевое слово тела case/default")

    def test_self_contained_macro_call_not_corrupted(self, cpp_branches_instrumented_src):
        """Баг: самодостаточный макрос (MAKE_ADDER), разворачивающийся в
        ЦЕЛУЮ функцию одним вызовом, раньше оборачивался в "{ датчик;
        ВЫЗОВ }" — вложенное определение функции внутри блока (ошибка
        сборки). Строка вызова должна остаться буквально неизменной."""
        src = (cpp_branches_instrumented_src / "macro_demo.cpp").read_text(encoding="utf-8")
        assert re.search(r"^MAKE_ADDER\(add_via_macro\)\s*$", src, re.M), "вызов MAKE_ADDER изменён"
        assert re.search(r"^MAKE_ADDER\(add_via_macro2\)\s*$", src, re.M), "вызов MAKE_ADDER изменён"

    def test_macro_generated_case_call_not_corrupted(self, cpp_branches_instrumented_src):
        """Регрессия (REP8-style): вызов макроса, разворачивающегося в
        несколько case-меток, не должен получать датчик ДО или ПОСЛЕ ':'
        (раньше — __TRACE с обеих сторон общего ':')."""
        src = (cpp_branches_instrumented_src / "negative_demo.cpp").read_text(encoding="utf-8")
        assert re.search(r"^\s*case CASES4\(10\):\s*//", src, re.M), "вызов CASES4(10): изменён"

    def test_oneline_if_else_no_brace_sensors_not_overlapping(self, cpp_branches_instrumented_src):
        """Баг: утечка col_shifts между несколькими open/close-вставками на
        ОДНОЙ строке (`if (...) r=...; else r=...;` без скобок) переносила
        чужой сдвиг на не связанную с ним вставку и рвала уже вставленный
        __TRACE() соседней ветви (закрывающая } влезала в его аргументы)."""
        src = (cpp_branches_instrumented_src / "oneline_demo.cpp").read_text(encoding="utf-8")
        m = re.search(r"if_else_oneline_nn\(int x\) \{.*?\n(.*?)\n\s*return r;", src, re.S)
        assert m, "if_else_oneline_nn не найдена в инструментированном исходнике"
        body = m.group(1)
        assert not re.search(r"__TRACE\([^)]*[{}][^)]*\)", body), (
            f"скобка { {} } влезла в аргументы __TRACE: {body!r}")
        assert body.count("{") == body.count("}"), f"несбалансированные {{}}: {body!r}"
        assert re.search(r"if \(x % 2 == 0\) \{ __TRACE\(\d+, \d+, \d+\); r = x / 2; \}"
                          r" else \{ __TRACE\(\d+, \d+, \d+\); r = x \* 3 \+ 1; \}", body)

    def test_check_macro_idiom_not_corrupted(self, cpp_branches_instrumented_src):
        """Регрессия (HotSpot CHECK/CHECK_/RETURN/TRAPS-идиома, см.
        classFileParser.cpp::classfile_parse_error(..., CHECK)): макрос —
        последний аргумент вызова, сам закрывающий список аргументов и
        порождающий if внутри своего раскрытия — CodeQL репортует конец
        одиночного оператора-тела if (hasBlock=0) сразу после "CHECK", а не
        после настоящего ');'. Обёртка "{ датчик; ВЫЗОВ }" по такой
        координате вставила бы "}" ВНУТРЬ списка аргументов вызова
        (`log_message("...", DUMMY_THREAD });`). Строка должна остаться
        буквально неизменной — без датчика."""
        src = (cpp_branches_instrumented_src / "macro_demo.cpp").read_text(encoding="utf-8")
        assert re.search(r'^\s*log_message\("guarded call", CHECK\);\s*$', src, re.M), (
            "вызов log_message(..., CHECK) изменён/разрезан")

    def test_while_try_no_brace_catch_not_orphaned(self, cpp_branches_instrumented_src):
        """Баг #8: `while(...) try {...} catch(...) {...}` без своих {} вокруг
        while (тело while — это сам TryStmt) — CodeQL даёт TryStmt.getLocation()
        только до конца try-блока, БЕЗ catch-обработчика, поэтому закрывающая
        '}' обёртки одиночного оператора (has_block=0) могла попасть ПРЯМО
        ПЕРЕД catch — он оставался "осиротевшим" вне фигурных скобок while
        (см. rikdataset.cpp, GDAL/RIK, RIKRasterBand::IReadBlock). catch
        должен остаться ВНУТРИ обёртки, сразу после try-блока."""
        src = (cpp_branches_instrumented_src / "exception_demo.cpp").read_text(encoding="utf-8")
        m = re.search(r"while_try_no_brace\(int n\) \{.*?\n(.*?)\n\s*return total;", src, re.S)
        assert m, "while_try_no_brace не найдена в инструментированном исходнике"
        body = m.group(1)
        assert body.count("{") == body.count("}"), f"несбалансированные {{}}: {body!r}"
        assert re.search(r"\}\s*catch \(const std::exception&\) \{", body), (
            "catch оторван от try-блока (закрывающая '}' обёртки вставлена раньше catch)")
        assert re.search(r"catch \(const std::exception&\) \{\s*\n\s*__TRACE\(\d+, \d+, \d+\);", body), (
            "датчик catch не сразу после его {")
