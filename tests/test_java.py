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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dynamic"))
from instrument_java import _is_bootstrap_path, dedupe_probe_points, _insertion_is_valid  # noqa: E402


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

    def test_bootstrap_packages_excluded_from_extraction(self):
        """Баг (реальный проект, full-coverage JDK): датчик в java.lang/
        java.util/java.io/java.nio/java.lang.invoke вызывается на раннем
        bootstrap JVM, до готовности VM диспетчеризовать вызов метода —
        нативный SIGSEGV (не лечится re-entrancy guard / catch(Throwable) в
        Cqtrace.hit() — тело не успевает начать исполняться). Эти ПРЯМЫЕ
        члены пакетов (без подпакетов — java.lang.reflect/ref/annotation и
        т.п. безопасны и должны остаться в охвате) исключаются из
        извлечения исходников по умолчанию (см. --no-exclude-bootstrap)."""
        excluded = [
            "java/lang/Object.java",
            "some/build/path/java/lang/String.java",
            "java/lang/invoke/LambdaForm.java",
            "java/util/HashMap.java",
            "java/io/File.java",
            "java/nio/Buffer.java",
        ]
        kept = [
            "java/lang/reflect/Method.java",
            "java/lang/ref/WeakReference.java",
            "java/util/concurrent/ConcurrentHashMap.java",
            "java/util/regex/Pattern.java",
            "java/nio/channels/Channel.java",
            "com/sun/corba/se/spi/activation/Foo.java",
            "branches/BranchDemo.java",
        ]
        for p in excluded:
            assert _is_bootstrap_path(p), f"{p}: должен быть исключён (bootstrap)"
        for p in kept:
            assert not _is_bootstrap_path(p), f"{p}: НЕ должен быть исключён"

    def test_dedupe_probe_points_drops_identical_geometry(self):
        """Баг (реальный проект, full-coverage JDK): CodeQL вернул несколько
        Callable-сущностей (generic-инстанцирование/raw-типы) для ОДНОЙ
        физической точки исходника — разный 'func', но идентичная позиция
        вставки. Без дедупликации каждая лишняя строка добавляла ЕЩЁ ОДНУ
        вставку в ту же позицию -> один try получал два finally (невалидный
        синтаксис; 412 файлов/7600 дублей, сконцентрировано в java.io.*:
        BufferedReader, BufferedInputStream, Bits)."""
        pts = [
            {"kind": "entry", "func": "a.B.m", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 15, "close_col": 5, "btype": "-"},
            {"kind": "entry", "func": "a.B$Raw.m", "file": "B.java", "ref_line": 10,
             "open_line": 10, "open_col": 20, "close_line": 15, "close_col": 5, "btype": "-"},
            {"kind": "branch", "func": "a.B.m", "file": "B.java", "ref_line": 11,
             "open_line": 11, "open_col": 8, "close_line": 0, "close_col": 0, "btype": "if"},
        ]
        out = dedupe_probe_points(pts, log=None)
        assert len(out) == 2, "дубликат с идентичной геометрией должен быть отброшен"
        assert sorted(o["kind"] for o in out) == ["branch", "entry"]

    def test_jar_build_survives_stale_directory_at_target_path(self, tmp_path):
        """Баг (реальный проект, повторная инструментация в тот же --out без
        очистки workspace): если предыдущий прогон упал РОВНО на шаге `jar
        -cf cqtrace-runtime.jar` (исключение из check=True прерывает скрипт
        ДО финальной чистки .cqtrace_jar_build), на месте jar-файла может
        остаться каталог — `jar` падает 'Cannot create a file when that
        file already exists' на КАЖДОМ следующем прогоне. Сюда вынесена та
        же логика очистки, что в instrument_java.py перед вызовом `jar -cf`
        (см. main()) — реальный вызов `jar`, без мока."""
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
        """Баг (реальный проект, corba/.../ObjectStreamClass.getFields()):
        недостоверная геометрия CodeQL подставила позицию ВНУТРИ идентификатора
        — вставка датчика разрезала "getFields" на "getField" + код + "s()",
        а закрывающая — "length" на "l" + код + "ength" (внутри ДРУГОГО
        оператора if глубоко в теле метода). Без проверки на границу токена
        датчик вставлялся БЕЗ ВАЛИДАЦИИ, портя синтаксис файла."""
        sig = "    public ObjectStreamField[] getFields() {"
        # Открывающая вставка ДОЛЖНА идти сразу после '{' сигнатуры метода.
        brace_idx = sig.index("{")
        assert _insertion_is_valid(sig, brace_idx + 1, prio=0)
        # Координата CodeQL указывает внутрь "getFields" (после "getField") —
        # ровно воспроизводит реальный кейс ("getField" + датчик + "s()").
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
