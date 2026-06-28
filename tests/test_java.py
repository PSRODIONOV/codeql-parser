"""Регресс Java-инструментатора (small-projects/test-project-java-branches).

Паритет по охвату с test-project-cpp-branches (см. docs/PRINCIPLES_C_CPP.md):
if/else, for/while/do, switch case/default (fallthrough-группы),
try/catch/finally, вложенность, и негативы — enhanced-for, тернарный ?:,
&& / || (не дают ветвей). Покрывает:
  • определение ветвей (Перечень_ветвей.csv): if/else/for/while/do/try/
    catch/case/default — паритет типов с C++ (см. queries/cpp/function_flow.ql);
  • дисамбигуация перегрузки helper()/helper(int) — общий qname
    "branches.BranchDemo.helper", разные № ФО (см. _lookup_fo);
  • датчики (Карта_датчиков.csv): вход/выход у каждого ФО, явный super(),
    else и catch — отдельные датчики со своими номерами ветвей;
  • покрытие (Покрытие_ветвей.csv): все ветви исполняются (Main.java
    вызывает каждый метод так, чтобы сработала каждая ветвь).

Золотые отчёты: reports/small-projects/java-branches/ (пути → basename).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dynamic"))
from instrument_java import (  # noqa: E402
    dedupe_probe_points, _insertion_is_valid,
    match_file_by_base, match_file_by_relpath, _find_jdk_tool,
)
from conftest import load_csv  # noqa: E402


def _short(fo: str) -> str:
    return fo.rsplit(".", 1)[-1]


def branches_of(inv, name):
    return [r for r in inv if _short(r.get("ФО", "")) == name]


def types_of(rows):
    return [r.get("Тип", "") for r in rows]


# catch — обычная строка Перечень_ветвей.csv (Тип=catch) со своим номером
# ветви, не общим с try. 81 "обычных" ветвей + 10 catch-клауз (simpleTry:1,
# tryMultipleCatch:3, nestedTry:2, tryWithLoop:1, BranchDemo.tryBranch:1,
# AdvancedDemo.safeDiv:1, Pipeline.process:1; tryFinally — без catch, 0) = 91.
TOTAL_BRANCHES = 91
TOTAL_CATCH_SENSORS = 10


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
        # try и его catch — обе обычные строки инвентаря, со своими номерами.
        assert types_of(branches_of(java_branches_inventory, "tryBranch")) == ["try", "catch"]

    def test_overloaded_helper_has_no_branches(self, java_branches_inventory):
        """helper()/helper(int) — без веток (тернарный оператор не
        отслеживается); коллизия имён проверяется на уровне ФО, не ветвей."""
        assert branches_of(java_branches_inventory, "helper") == []

    def test_do_while_distinct_from_while(self, java_branches_inventory):
        """do-while должен классифицироваться как 'do', а не как 'while' —
        паритет с C++, где это отдельный тип."""
        assert types_of(branches_of(java_branches_inventory, "doWhileDemo")) == ["do"]
        assert types_of(branches_of(java_branches_inventory, "countDownWhile")) == ["while"]

    def test_switch_case_default_tracked(self, java_branches_inventory):
        """Каждая case-метка (включая участников fallthrough-группы) и
        default — отдельная ветвь, паритет с C++ (см.
        queries/cpp/function_flow.ql: caseBtype/hasBlock=2)."""
        rows = branches_of(java_branches_inventory, "weekdayKind")
        assert types_of(rows) == ["case"] * 7 + ["default"]
        rows2 = branches_of(java_branches_inventory, "fallthroughSum")
        assert types_of(rows2) == ["case", "case", "default"]

    def test_try_catch_finally_nesting(self, java_branches_inventory):
        """try получает свою ветвь на каждый уровень вложенности; catch —
        тоже отдельная ветвь со своим номером; finally — не ветвь
        (нет точки решения, см. getInCatchMarker)."""
        assert types_of(branches_of(java_branches_inventory, "nestedTry")) == \
            ["try", "try", "if", "catch", "catch"]
        assert types_of(branches_of(java_branches_inventory, "tryFinally")) == ["try"]

    def test_enhanced_for_and_logical_ops_are_negatives(self, java_branches_inventory):
        """enhanced-for (for-each), тернарный ?: и && / || — НЕ дают
        ветвей: паритет с C++ (range-based for/?:/&&/||, см.
        negative_demo.cpp в test-project-cpp-branches)."""
        assert branches_of(java_branches_inventory, "sumRange") == []
        assert branches_of(java_branches_inventory, "signAndFlags") == []

    def test_else_if_chain_each_if_is_own_branch(self, java_branches_inventory):
        """Цепочка else-if (паритет с if_demo.cpp::else_if_chain): каждый
        вложенный if в позиции else — самостоятельная ветвь со своим
        номером, а не часть одной 'else'-записи родителя."""
        rows = branches_of(java_branches_inventory, "elseIfChain")
        assert types_of(rows) == ["if", "if", "if", "if"]
        assert [r.get("№ ветви") for r in rows] == ["1", "2", "3", "4"]

    def test_nested_if_without_else(self, java_branches_inventory):
        """Вложенные if без else (паритет с if_demo.cpp::nested_if) —
        внешний + два вложенных, без 'else'-записей."""
        assert types_of(branches_of(java_branches_inventory, "nestedIf")) == ["if", "if", "if"]

    def test_pipeline_call_routes(self, java_branches_inventory):
        """Класс с маршрутами вызовов между методами (паритет с
        pipeline.cpp): aboveThreshold/classify/normalize/process — каждый
        со своим набором ветвей, независимо от вызовов друг друга."""
        assert types_of(branches_of(java_branches_inventory, "aboveThreshold")) == ["if"]
        assert types_of(branches_of(java_branches_inventory, "classify")) == ["for", "if"]
        assert types_of(branches_of(java_branches_inventory, "normalize")) == ["while", "do"]
        assert types_of(branches_of(java_branches_inventory, "process")) == \
            ["try", "if", "if", "catch"]


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
        """Число branch-датчиков (не вход/выход) ровно совпадает с
        Перечень_ветвей.csv — у каждой физической позиции свой номер и своя
        строка, лишних датчиков без строки инвентаря не остаётся."""
        branch_rows = [r for r in java_branches_sensors if r.get("Запись (br)") not in ("0", "-1")]
        assert len(branch_rows) == TOTAL_BRANCHES

    def test_else_sensor_has_own_branch_num_distinct_from_if(self, java_branches_sensors):
        """else не должен делить № ветви с if: Cqtrace.hit(fo,br) должен
        быть разным для then- и else-блока, иначе Покрытие_ветвей.csv/
        маршруты не отличат, какой из них выполнился."""
        ifs = [r for r in java_branches_sensors if r.get("Тип") == "if"]
        elses = [r for r in java_branches_sensors if r.get("Тип") == "else"]
        assert ifs and elses
        if_branch = next(r for r in ifs if r.get("№ ФО") == elses[0].get("№ ФО"))
        assert if_branch.get("Запись (br)") != elses[0].get("Запись (br)"), (
            "else не должен делить № ветви с if")

    def test_catch_sensor_has_own_branch_num_and_own_inventory_row(
            self, java_branches_sensors, java_branches_inventory):
        """Каждая catch-клауза должна иметь свой номер и свою строку
        инвентаря — try может иметь несколько catch (см. tryMultipleCatch),
        и у всех номера разные."""
        catches = [r for r in java_branches_sensors if r.get("Тип") == "catch"]
        assert len(catches) == TOTAL_CATCH_SENSORS
        inv_catches = [r for r in java_branches_inventory if r.get("Тип") == "catch"]
        assert len(inv_catches) == TOTAL_CATCH_SENSORS, (
            "catch должен иметь собственную строку в Перечень_ветвей")
        tries = {r.get("№ ФО"): r.get("Запись (br)")
                 for r in java_branches_sensors if r.get("Тип") == "try"}
        for c in catches:
            try_num = tries.get(c.get("№ ФО"))
            assert try_num is not None
            assert c.get("Запись (br)") != try_num, (
                "catch не должен делить № ветви с try")
        # tryMultipleCatch — несколько catch на один try, у всех РАЗНЫЕ номера
        nums_by_fo: dict = {}
        for c in catches:
            nums_by_fo.setdefault(c.get("№ ФО"), set()).add(c.get("Запись (br)"))
        assert any(len(v) >= 3 for v in nums_by_fo.values()), (
            "tryMultipleCatch (3 catch) должен дать 3 РАЗНЫХ номера ветви")


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
        """Датчик не должен вставляться как полный путь
        '<pkg>.Cqtrace.hit(...)' — первый сегмент пакета (com/sun/se/spi и
        т.п.) резолвится Java как обычное простое имя, и если в области
        видимости есть локальная переменная/параметр с этим же именем
        (напр. 'String com = ...;'), компилятор трактует 'com.sun....' как
        доступ к полю на этой переменной, а не как путь к пакету — ошибка
        компиляции. Вместо этого должен использоваться
        import + простое имя типа 'Cqtrace.hit(...)' — оно не подменяется
        переменной с другим именем."""
        for fname in ("BranchDemo.java", "Main.java", "OtherDemo.java"):
            src = (java_branches_instrumented_src / "branches" / fname).read_text(encoding="utf-8")
            assert "import branches.Cqtrace;" in src, f"{fname}: нет import Cqtrace"
            assert "Cqtrace.hit(" in src, f"{fname}: не найден вызов Cqtrace.hit(...)"
            assert "branches.Cqtrace.hit(" not in src, (
                f"{fname}: датчик вставлен полным путём branches.Cqtrace.hit(...) "
                f"— риск коллизии с локальной переменной 'branches'")

    def test_recommended_bootstrap_blacklist_via_sensor_filter(self):
        """Датчик в java.lang/java.util.concurrent вызывается на раннем
        bootstrap JVM, до готовности VM диспетчеризовать вызов метода —
        нативный SIGSEGV (тело Cqtrace.hit() не успевает начать
        исполняться). java/lang/ref/* (Reference/Finalizer/WeakReference —
        управление GC/финализацией) особенно чувствителен.

        Настраиваемый чёрный список вставки датчиков (вкладка «Динамический
        анализ», sensor_filter_factory в core/file_lists.py): этот тест
        документирует рекомендуемые шаблоны для проектов, собирающих сам
        JDK (как gosjava)."""
        from core.file_lists import sensor_filter_factory
        recommended_exclude = ["java/lang/*", "java/util/concurrent/*"]
        f = sensor_filter_factory(None, recommended_exclude)
        excluded = [
            "java/lang/Object.java",
            "some/build/path/java/lang/String.java",
            "java/lang/invoke/LambdaForm.java",
            "java/lang/reflect/Method.java",
            "java/lang/ref/WeakReference.java",
            "java/lang/ref/Finalizer.java",
            "java/lang/management/ManagementFactory.java",
            "java/util/concurrent/ConcurrentHashMap.java",
            "java/util/concurrent/atomic/AtomicLong.java",
        ]
        kept = [
            "java/util/HashMap.java",
            "java/io/File.java",
            "java/nio/Buffer.java",
            "java/util/regex/Pattern.java",
            "java/nio/channels/Channel.java",
            "com/sun/corba/se/spi/activation/Foo.java",
            "branches/BranchDemo.java",
        ]
        for p in excluded:
            assert not f(p), f"{p}: должен быть исключён (bootstrap)"
        for p in kept:
            assert f(p), f"{p}: НЕ должен быть исключён"

    def test_dedupe_probe_points_drops_identical_geometry(self):
        """Две разные Callable-сущности с полностью идентичной геометрией
        (не пара <clinit>/<obinit> — см. отдельный тест ниже) — настоящая
        аномалия. Без дедупликации лишняя строка добавила бы ещё одну
        вставку в ту же позицию (напр. один try получил бы два finally —
        невалидный синтаксис); дубль должен попадать в лог "Дубликатов
        отброшено"."""
        pts = [
            {"kind": "entry", "func": "a.B.m", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 15, "close_col": 5, "btype": "-"},
            {"kind": "entry", "func": "a.B$Raw.m", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 15, "close_col": 5, "btype": "-"},
            {"kind": "branch", "func": "a.B.m", "file": "B.java", "ref_line": 11,
             "open_line": 11, "open_col": 8, "close_line": 0, "close_col": 0, "btype": "if"},
        ]
        logged = []
        out = dedupe_probe_points(pts, log=logged.append)
        assert len(out) == 2, "дубликат с идентичной геометрией должен быть отброшен"
        assert sorted(o["kind"] for o in out) == ["branch", "entry"]
        assert logged, "настоящая аномалия дублирования ДОЛЖНА попадать в лог"

    def test_dedupe_probe_points_silently_drops_clinit_obinit_collision(self):
        """Класс без явного static{}/instance-блока в исходнике (напр.
        только static final поля-константы) получает синтетическую пару
        <clinit>+<obinit> с одной и той же вырожденной геометрией
        (привязанной к открывающей скобке класса). Ни один из них не
        присутствует в исходнике в явном виде — такой дубль дропается
        молча, не засоряя "Дубликатов отброшено" ложной тревогой."""
        pts = [
            {"kind": "entry", "func": "a.B.<clinit>", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 10, "close_col": 21, "btype": "-"},
            {"kind": "entry", "func": "a.B.<obinit>", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 10, "close_col": 21, "btype": "-"},
        ]
        logged = []
        out = dedupe_probe_points(pts, log=logged.append)
        assert len(out) == 1, "одна из пары <clinit>/<obinit> должна быть отброшена"
        assert not logged, "коллизия <clinit>/<obinit> НЕ должна попадать в лог"

    def test_jar_build_survives_stale_directory_at_target_path(self, tmp_path):
        """При повторной инструментации в тот же --out без очистки
        workspace на месте jar-файла может остаться каталог (если
        предыдущий прогон прервался на шаге `jar -cf`) — `jar` падает
        'Cannot create a file when that file already exists' на каждом
        следующем прогоне. Проверяет ту же логику очистки, что
        instrument_java.py делает перед вызовом `jar -cf` (см. main()) —
        реальный вызов `jar`, без мока."""
        if shutil.which("jar") is None or shutil.which("javac") is None:
            pytest.skip("jar/javac не найдены в PATH")
        classes = tmp_path / "classes"
        classes.mkdir()
        (tmp_path / "Dummy.java").write_text("class Dummy {}", encoding="utf-8")
        subprocess.run(["javac", "-d", str(classes), str(tmp_path / "Dummy.java")], check=True)

        target = tmp_path / "cqtrace-runtime.jar"
        # Симулируем оставшийся от прерванного прогона каталог на месте jar.
        (target / "leftover").mkdir(parents=True)
        assert target.is_dir()

        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
        res = subprocess.run(["jar", "-cf", str(target), "-C", str(classes), "."],
                             capture_output=True, text=True)
        assert res.returncode == 0, f"jar не пересобрался после очистки: {res.stderr}"
        assert target.is_file(), "целевой путь должен стать обычным файлом jar"

    def test_insertion_validity_catches_token_split(self):
        """Недостоверная геометрия CodeQL может подставить позицию внутри
        идентификатора — вставка датчика разрезала бы "getFields" на
        "getField" + код + "s()". Без проверки границы токена датчик
        вставлялся бы без валидации, портя синтаксис файла."""
        sig = "    public ObjectStreamField[] getFields() {"
        # Открывающая вставка должна идти сразу после '{' сигнатуры метода.
        brace_idx = sig.index("{")
        assert _insertion_is_valid(sig, brace_idx + 1, prio=0)
        # Координата CodeQL указывает внутрь "getFields" (после "getField").
        bad_open = sig.index("getFields") + len("getField")
        assert not _insertion_is_valid(sig, bad_open, prio=0)

        body_line = "        if (fields.length > 0) {"
        # Закрывающая вставка ДОЛЖНА указывать точно на '}' тела метода —
        # эта строка вообще не содержит закрывающую скобку тела getFields(),
        # поэтому ЛЮБАЯ позиция здесь для prio=1 недостоверна.
        bad_close = body_line.index("length") + 1
        assert not _insertion_is_valid(body_line, bad_close, prio=1)
        # Контрольный пример валидного закрытия: позиция указывает на '}'.
        closer = "    }"
        assert _insertion_is_valid(closer, closer.index("}"), prio=1)

    def test_match_file_rejects_basename_collision_with_excluded_file(self):
        """java/lang/CharacterData.java (исключён из охвата извлечения
        фильтром) и org/w3c/dom/CharacterData.java (обычный файл, входит в
        охват) — разные файлы с одинаковым basename. При единственном
        кандидате по basename обязательна проверка совпадения хвоста пути —
        несовпадение должно возвращать None (точка пропускается), а не
        чужой файл."""
        by_base = {
            "CharacterData.java": [
                ("proj/jaxp/src/org/w3c/dom/CharacterData.java", Path("/out/proj/jaxp/src/org/w3c/dom/CharacterData.java")),
            ],
        }
        # java/lang/CharacterData.java исключён из --out фильтром, его
        # реального кандидата в by_base нет — единственный кандидат по
        # basename физически НЕ относится к этому пути.
        probe_path = "/tmp/java_build.X/proj/jdk/src/share/classes/java/lang/CharacterData.java"
        assert match_file_by_base(probe_path, by_base) is None

        # Контрольный пример: путь действительно совпадает хвостом —
        # единственный кандидат должен находиться.
        real_path = "/tmp/java_build.X/proj/jaxp/src/org/w3c/dom/CharacterData.java"
        assert match_file_by_base(real_path, by_base) == Path(
            "/out/proj/jaxp/src/org/w3c/dom/CharacterData.java")

    def test_match_file_by_relpath_resolves_basename_collision_directly(self):
        """Устраняет САМУ ПРИЧИНУ коллизии (а не только её симптом, как
        match_file_by_base): при ТОЧНОМ совпадении relative-path (тот же
        prefix, что extract_project_sources обрезал при извлечении, см.
        core/file_lists.py::detect_db_prefix) однозначно находится нужный
        файл, даже если basename совпадает с другим, физически НЕ связанным
        файлом — никакой эвристики "единственный кандидат" вообще не
        требуется, коллизия по имени не возникает в принципе."""
        prefix = "tmp/java_build.X/"
        by_relpath = {
            "proj/jaxp/src/org/w3c/dom/CharacterData.java":
                Path("/out/proj/jaxp/src/org/w3c/dom/CharacterData.java"),
            "proj/jdk/src/share/classes/java/lang/CharacterData.java":
                Path("/out/proj/jdk/src/share/classes/java/lang/CharacterData.java"),
        }
        by_base = {
            "CharacterData.java": [
                (k, v) for k, v in by_relpath.items()
            ],
        }
        dom_probe = "/tmp/java_build.X/proj/jaxp/src/org/w3c/dom/CharacterData.java"
        lang_probe = "/tmp/java_build.X/proj/jdk/src/share/classes/java/lang/CharacterData.java"
        assert match_file_by_relpath(dom_probe, prefix, by_relpath, by_base) == Path(
            "/out/proj/jaxp/src/org/w3c/dom/CharacterData.java")
        assert match_file_by_relpath(lang_probe, prefix, by_relpath, by_base) == Path(
            "/out/proj/jdk/src/share/classes/java/lang/CharacterData.java")

    def test_match_file_by_relpath_falls_back_when_file_not_extracted(self):
        """java/lang/CharacterData.java bootstrap-исключён — в by_relpath его
        нет вовсе (физически не извлекался). Точное совпадение не находит
        ничего -> откат на match_file_by_base, который должен корректно
        вернуть None, а не чужой org/w3c/dom/CharacterData.java."""
        prefix = "tmp/java_build.X/"
        by_relpath = {
            "proj/jaxp/src/org/w3c/dom/CharacterData.java":
                Path("/out/proj/jaxp/src/org/w3c/dom/CharacterData.java"),
        }
        by_base = {
            "CharacterData.java": [
                ("proj/jaxp/src/org/w3c/dom/CharacterData.java",
                 Path("/out/proj/jaxp/src/org/w3c/dom/CharacterData.java")),
            ],
        }
        lang_probe = "/tmp/java_build.X/proj/jdk/src/share/classes/java/lang/CharacterData.java"
        assert match_file_by_relpath(lang_probe, prefix, by_relpath, by_base) is None

    def test_macro_filter_resolves_basename_collision(self, tmp_path):
        """Два файла с одинаковым basename (StringSeqHelper.java) в разных
        каталогах src.zip. read_source_snapshot индексирует по
        относительному пути, не только по basename — иначе
        filter_macro_synthesized_fo сверял бы имя настоящих методов
        (insert/extract/read) со строкой чужого файла и ложно решал, что
        имя "собрано макросом". Этот фильтр для Java не запускается (нет
        макросов), но read_source_snapshot/filter_macro_synthesized_fo
        общий с cpp/c, поэтому проверяется независимо от языка."""
        import sys, zipfile
        from pathlib import Path as _Path
        sys.path.insert(0, str(_Path(__file__).parent.parent))
        from core.fo_filters import read_source_snapshot, filter_macro_synthesized_fo

        db_dir = tmp_path / "fake-db"
        db_dir.mkdir()
        with zipfile.ZipFile(db_dir / "src.zip", "w") as z:
            # "Чужой" StringSeqHelper.java — другой пакет, другое тело.
            z.writestr(
                "tmp/build/proj/com/sun/corba/StringSeqHelper.java",
                "package com.sun.corba;\n"
                "class StringSeqHelper {\n"
                "  static void unrelated() {}\n"
                "}\n",
            )
            # Реальный StringSeqHelper.java — другой пакет, тот же basename.
            z.writestr(
                "tmp/build/proj/org/omg/CORBA/StringSeqHelper.java",
                "package org.omg.CORBA;\n"
                "abstract public class StringSeqHelper {\n"
                "  public static void insert (org.omg.CORBA.Any a) {}\n"
                "}\n",
            )
        snapshot = read_source_snapshot(str(db_dir))
        func_data = [{
            "qualified_name": "org.omg.CORBA.StringSeqHelper.insert",
            "name": "insert",
            "file": "/tmp/build/proj/org/omg/CORBA/StringSeqHelper.java",
            "line": "3",
        }]
        out = filter_macro_synthesized_fo(func_data, snapshot, log=None)
        assert len(out) == 1, (
            "реальный метод insert НЕ должен быть исключён из-за коллизии "
            "basename с одноимённым файлом в другом пакете")


class TestCoveragePrecision:
    """else и catch имеют свой номер ветви, не общий с if/try —
    Cqtrace.hit(fo,br) должен быть разным для физически разных позиций.

    Эти тесты прогоняют два разных сценария выполнения (только if-ветвь /
    только else-ветвь) через реально скомпилированный и запущенный
    инструментированный код и проверяют, что Покрытие_ветвей.csv корректно
    различает, что произошло — статический разбор кода тут не доказателен."""

    @staticmethod
    def _compile_and_run(java_branches_instrumented_src, tmp_path, javac, java, arg):
        classes = tmp_path / "classes"
        if not classes.exists():
            classes.mkdir()
            java_files = [str(p) for p in java_branches_instrumented_src.rglob("*.java")]
            subprocess.run([javac, "-d", str(classes), "-encoding", "utf-8"] + java_files,
                          check=True, capture_output=True, text=True)
            driver = tmp_path / "Driver.java"
            driver.write_text(
                "package branches;\n"
                "public class Driver {\n"
                "    public static void main(String[] a) {\n"
                "        AdvancedDemo ad = new AdvancedDemo();\n"
                "        if (a.length > 0 && a[0].equals(\"A\")) ad.classifyEmpty(5);\n"
                "        else ad.classifyEmpty(-5);\n"
                "    }\n"
                "}\n",
                encoding="utf-8")
            subprocess.run([javac, "-d", str(classes), "-cp", str(classes),
                            "-encoding", "utf-8", str(driver)], check=True, capture_output=True, text=True)
        home = tmp_path / f"home_{arg}"
        home.mkdir()
        subprocess.run([java, f"-Duser.home={home}", "-cp", str(classes), "branches.Driver", arg],
                       check=True, capture_output=True, text=True)
        return home

    @staticmethod
    def _branch_status(out_dir, branch_type):
        rows = load_csv(out_dir / "Покрытие_ветвей.csv")
        row = next(r for r in rows if r.get("ФО", "").endswith("classifyEmpty")
                   and r.get("Тип") == branch_type)
        return row.get("Покрыта", "").strip()

    def test_if_else_coverage_distinguishes_scenarios(
            self, java_branches_instrumented_src, tmp_path):
        javac, java = _find_jdk_tool("javac"), _find_jdk_tool("java")
        if not javac or not java:
            pytest.skip("javac/java не найдены (нет JDK в third-party/jdk*/PATH)")
        reports_static = java_branches_instrumented_src.parent / "reports" / "static"
        sensor_map = java_branches_instrumented_src / "Карта_датчиков.csv"
        if not (reports_static / "Перечень_ветвей.csv").exists() or not sensor_map.exists():
            pytest.skip("нет статических отчётов/карты датчиков рядом с instrumented-sources")

        home_a = self._compile_and_run(java_branches_instrumented_src, tmp_path, javac, java, "A")
        home_b = self._compile_and_run(java_branches_instrumented_src, tmp_path, javac, java, "B")

        cov_a, cov_b = tmp_path / "cov_a", tmp_path / "cov_b"
        for home, out in ((home_a, cov_a), (home_b, cov_b)):
            subprocess.run([sys.executable, str(Path(__file__).parent.parent / "dynamic" / "coverage_report.py"),
                            "--traces", str(home), "--reports", str(reports_static),
                            "--sensor-map", str(sensor_map), "--out", str(out)],
                           check=True, capture_output=True, text=True)

        # Сценарий A: classifyEmpty(5) -> ТОЛЬКО if. Сценарий B: classifyEmpty(-5) -> ТОЛЬКО else.
        assert self._branch_status(cov_a, "if") == "да"
        assert self._branch_status(cov_a, "else") == "нет", (
            "сценарий A не должен покрывать else — если покрывает, "
            "if/else всё ещё делят № ветви (регрессия)")
        assert self._branch_status(cov_b, "if") == "нет", (
            "сценарий B не должен покрывать if — если покрывает, "
            "if/else всё ещё делят № ветви (регрессия)")
        assert self._branch_status(cov_b, "else") == "да"
