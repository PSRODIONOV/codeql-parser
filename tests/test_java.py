"""Регресс Java-инструментатора (small-projects/test-project-java-branches).

Минимальная фикстура для доводки instrument_java.py до инфраструктурной
параллели с C/C++ (--trace-tag, --project-db, --include-list/--exclude-list,
извлечение исходников прямо из src.zip БД, дисамбигуация одноимённых
методов по файлу+строке, dropped_sids). Покрывает:
  • определение ветвей (Перечень_ветвей.csv): if/else, for, while, try;
  • дисамбигуация перегрузки helper()/helper(int) — общий qname
    "branches.BranchDemo.helper", разные № ФО (см. _lookup_fo);
  • датчики (Карта_датчиков.csv): вход/выход у каждого ФО, явный super();
  • покрытие (Покрытие_ветвей.csv): все ветви исполняются.

Золотые отчёты: reports/small-projects/java-branches/ (пути → basename).
"""
import re


def _short(fo: str) -> str:
    return fo.rsplit(".", 1)[-1]


def branches_of(inv, name):
    return [r for r in inv if _short(r.get("ФО", "")) == name]


def types_of(rows):
    return [r.get("Тип", "") for r in rows]


TOTAL_BRANCHES = 5


class TestBranchDetection:

    def test_total_branches(self, java_branches_inventory):
        assert len(java_branches_inventory) == TOTAL_BRANCHES, (
            f"ожидалось {TOTAL_BRANCHES} ветвей, получено {len(java_branches_inventory)}")

    def test_if_else_tracked(self, java_branches_inventory):
        rows = branches_of(java_branches_inventory, "ifBranch")
        assert sorted(types_of(rows)) == ["else", "if"]

    def test_for_while_try_tracked(self, java_branches_inventory):
        assert types_of(branches_of(java_branches_inventory, "forBranch")) == ["for"]
        assert types_of(branches_of(java_branches_inventory, "whileBranch")) == ["while"]
        assert types_of(branches_of(java_branches_inventory, "tryBranch")) == ["try"]

    def test_overloaded_helper_has_no_branches(self, java_branches_inventory):
        """helper()/helper(int) — без веток (тернарный оператор не
        отслеживается); коллизия имён проверяется на уровне ФО, не ветвей."""
        assert branches_of(java_branches_inventory, "helper") == []


class TestSensorMap:

    def test_overloaded_methods_get_distinct_fo_numbers(self, java_branches_fo, java_branches_sensors):
        """Баг-класс инструментатора: helper() и helper(int) делят один
        qname ('branches.BranchDemo.helper') в Перечень_ФО — наивное
        сопоставление "по первому совпадению" присвоило бы датчики ОБОИХ
        методов одному и тому же № ФО. _lookup_fo (по файлу+строке
        декларации) должен различить их — см. instrument_java.py."""
        rows = [r for r in java_branches_fo if r.get("Объект") == "branches.BranchDemo.helper"]
        assert len(rows) == 2, "фикстура должна содержать 2 перегрузки helper"
        fo_nums = {r.get("№ п/п") for r in rows}
        assert len(fo_nums) == 2, "обе перегрузки должны иметь РАЗНЫЕ № ФО"
        for fo_num in fo_nums:
            entries = [r for r in java_branches_sensors
                       if r.get("№ ФО") == fo_num and r.get("Запись (br)") == "0"]
            exits = [r for r in java_branches_sensors
                     if r.get("№ ФО") == fo_num and r.get("Запись (br)") == "-1"]
            assert len(entries) == 1 and len(exits) == 1, (
                f"№ ФО {fo_num}: ожидался ровно один вход и один выход")

    def test_every_fo_has_entry_and_exit(self, java_branches_sensors):
        entries, exits = set(), set()
        for r in java_branches_sensors:
            if r.get("Запись (br)") == "0":
                entries.add(r.get("№ ФО"))
            elif r.get("Запись (br)") == "-1":
                exits.add(r.get("№ ФО"))
        assert entries and entries == exits

    def test_branch_sensors_numbered(self, java_branches_sensors):
        branch_rows = [r for r in java_branches_sensors if r.get("Запись (br)") not in ("0", "-1")]
        assert len(branch_rows) == TOTAL_BRANCHES - 1, (
            "5 ветвей в статике, но 'else' без отдельного датчика (см. probe_points.ql) "
            "-> 4 датчика ветвей")


class TestCoverage:

    def test_all_branches_covered(self, java_branches_coverage):
        assert len(java_branches_coverage) == TOTAL_BRANCHES
        not_covered = [r for r in java_branches_coverage if r.get("Покрыта", "").strip() != "да"]
        assert not not_covered, (
            f"не покрыты: {[(r.get('ФО'), r.get('№ ветви')) for r in not_covered]}")


class TestInstrumentorRegressionBugs:

    def test_overloaded_methods_not_split(self, java_branches_instrumented_src):
        """Перегруженные helper()/helper(int) должны остаться синтаксически
        корректными и получить РАЗНЫЕ номера ФО в датчиках (см.
        TestSensorMap.test_overloaded_methods_get_distinct_fo_numbers — здесь
        проверяется побайтово, что вставка не разрезала код)."""
        src = (java_branches_instrumented_src / "branches" / "BranchDemo.java").read_text(encoding="utf-8")
        m1 = re.search(r'public String helper\(\) \{ Cqtrace\.hit\((\d+), 0\); try \{\s*'
                       r'return "no-arg";\s*\} finally \{ Cqtrace\.hit\(\1, -1\); \} \}', src)
        m2 = re.search(r'public String helper\(int x\) \{ Cqtrace\.hit\((\d+), 0\); try \{\s*'
                       r'return x > 0 \? "positive" : "non-positive";\s*'
                       r'\} finally \{ Cqtrace\.hit\(\1, -1\); \} \}', src)
        assert m1, "helper() не инструментирован корректно"
        assert m2, "helper(int) не инструментирован корректно"
        assert m1.group(1) != m2.group(1), "перегрузки получили ОДИНАКОВЫЙ № ФО"

    def test_explicit_super_call_wraps_after_it(self, java_branches_instrumented_src):
        """Баг-класс: конструктор с явным super() — датчик входа должен
        встать ПОСЛЕ super(), а не до него (вызов super() ВСЕГДА должен
        оставаться первым оператором тела конструктора в Java)."""
        src = (java_branches_instrumented_src / "branches" / "OtherDemo.java").read_text(encoding="utf-8")
        assert re.search(r"super\(\);\s*Cqtrace\.hit\(\d+, 0\); try \{", src), (
            "датчик входа не сразу после super()")
        assert not re.search(r"Cqtrace\.hit\(\d+, 0\);.*super\(\);", src, re.S), (
            "датчик входа вставлен ДО super()"
        )

    def test_braces_balanced(self, java_branches_instrumented_src):
        for fname in ("BranchDemo.java", "Main.java", "OtherDemo.java"):
            src = (java_branches_instrumented_src / "branches" / fname).read_text(encoding="utf-8")
            assert src.count("{") == src.count("}"), f"{fname}: несбалансированные {{}}"

    def test_sensor_call_uses_simple_name_not_qualified_path(self, java_branches_instrumented_src):
        """Баг (реальный проект, gen_profile/gosjava-класс): датчик НЕ должен
        вставляться как полный путь '<pkg>.Cqtrace.hit(...)' — первый сегмент
        пакета (com/sun/se/spi и т.п.) резолвится Java как ОБЫЧНОЕ простое
        имя, и если в области видимости есть локальная переменная/параметр с
        этим же именем (частый случай: 'String com = ...;'), компилятор
        трактует 'com.sun....' как доступ к полю на этой переменной, а не
        как путь к пакету — гарантированная ошибка компиляции (см.
        ConstantSetNode.java: 'String com = constantMap.get(key); if (com ==
        null) { com.sun....hit(...)'). Вместо этого должен использоваться
        import + простое имя типа 'Cqtrace.hit(...)' — оно не подменяется
        переменной с другим именем."""
        for fname in ("BranchDemo.java", "Main.java", "OtherDemo.java"):
            src = (java_branches_instrumented_src / "branches" / fname).read_text(encoding="utf-8")
            assert "import branches.Cqtrace;" in src, f"{fname}: нет import Cqtrace"
            assert "Cqtrace.hit(" in src, f"{fname}: не найден вызов Cqtrace.hit(...)"
            assert "branches.Cqtrace.hit(" not in src, (
                f"{fname}: датчик вставлен полным путём branches.Cqtrace.hit(...) "
                f"— риск коллизии с локальной переменной 'branches'")
