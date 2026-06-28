#!/usr/bin/env python3
"""
Инструментатор датчиков динамического анализа для Java.

Вставляет:
  - вход/выход ФО: тело метода/конструктора оборачивается
        { Pkg.Cqtrace.hit(fo,0); try { <тело> } finally { Pkg.Cqtrace.hit(fo,-1); } }
    (в конструкторе с super()/this() — обёртка ПОСЛЕ него);
  - ветвь: Pkg.Cqtrace.hit(fo,#N) первым оператором блока ветви.

Рантайм Cqtrace.java генерится в пакете проекта; ссылка — полное имя
<Pkg>.Cqtrace.hit(...) (импорт не нужен). Номера ФО/ветвей — из статики (1:1).
Проверка синтаксиса — javac (все файлы вместе).

Дерево исходников извлекается прямо из src.zip внутри CodeQL БД (как и для
C/C++, см. core/file_lists.py) — отдельно передавать --project не нужно.

Геометрия вставки (позиция входа/выхода ФО, позиция ветви, включая catch —
обычные строки Перечень_ветвей.csv со своим номером) читается прямо из
отчётов статики (Перечень_ФО/Перечень_ветвей.csv), считается в
queries/java/functional_objects.ql/function_flow.ql/catch_points.ql.

Использование:
  python3 instrument_java.py --db <codeql-db> --reports <static-dir>
      --out <work-dir> [--codeql codeql] [--lang java]
      [--include-list files.txt] [--exclude-list files.txt]
      [--trace-tag <tag>]
"""
import argparse, csv, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"


def _tool_runs(path: str) -> bool:
    """True, если инструмент реально запускается (CreateProcess не падает).
    Защищает от битой папки/репарс-точки third-party (WinError 1392
    ERROR_FILE_CORRUPT) и прочих OSError: такой кандидат существует на диске
    (Path.exists()=True), но не исполняется — его надо пропустить, а не
    падать трейсбеком на реальном вызове."""
    try:
        subprocess.run([path, "-version"], capture_output=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _find_jdk_tool(tool: str):
    """Путь к инструменту JDK (javac/jar/java): сначала бандл-JDK из
    third-party/jdk* (как codeql резолвится через _find_codeql), затем PATH.
    Кандидат должен и существовать, и РЕАЛЬНО запускаться (_tool_runs) —
    битый JDK (повреждённая junction → WinError 1392) пропускается в пользу
    следующего/PATH. Возвращает None, если рабочего нет нигде — вызывающий
    деградирует мягко, а не падает FileNotFoundError/OSError на вызове.
    Симметрично резолву JDK в core/joern_analyzer.py и instrument_php.py."""
    exe = tool + (".exe" if os.name == "nt" else "")
    tp = HERE.parent / "third-party"
    names = (["jdk25-win", "jdk11-win"] if os.name == "nt"
             else ["jdk25-linux", "jdk11-linux", "jdk11"])
    cands = [str(tp / name / "bin" / exe) for name in names]
    on_path = shutil.which(tool)
    if on_path:
        cands.append(on_path)
    for c in cands:
        try:
            if Path(c).exists() and _tool_runs(c):
                return c
        except OSError:
            continue
    return None

def read_fo_numbers(reports_dir: Path):
    """Перечень_ФО → {qualified_name: [(fo_num, file, line), ...]} — СПИСОК,
    а не один номер: одинаковые имена методов в разных классах (toString,
    equals и т.п.) — обычный случай в Java. Дисамбигуация — по файлу/строке,
    см. _lookup_fo (тот же подход, что у instrument_cpp.py)."""
    fo = {}
    p = reports_dir / "Перечень_ФО(процедур_функций).csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                name = row[1].strip()
                file, line = None, None
                if len(row) > 2 and row[2].strip():
                    m = re.match(r'^(.*)\((\d+)\)$', row[2].strip())
                    if m:
                        file, line = m.group(1), int(m.group(2))
                fo.setdefault(name, []).append((int(row[0]), file, line))
    return fo


def read_branch_numbers(reports_dir: Path):
    """Перечень_ветвей → {(qualified_name, line): [(branch_num, file, ins_col), ...]}.
    ins_col (из "Позиция вставки") — дисамбигуация if/else ОДНОСТРОЧНОЙ формы
    (`if (x) { a(); } else { b(); }` на одной строке): у обоих одна "Строка",
    различаются только колонкой вставки (см. _pick_by_branch в
    instrument_cpp.py — тот же класс коллизии)."""
    br = {}
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                key = (row[2].strip(), int(row[6]))
                file = row[5].strip() if len(row) > 5 and row[5].strip() else None
                ins_col = None
                if len(row) > 7 and ":" in row[7]:
                    try:
                        ins_col = int(row[7].rsplit(":", 1)[1])
                    except ValueError:
                        pass
                br.setdefault(key, []).append((int(row[3]), file, ins_col))
    return br


def _parse_pos(s: str):
    """'line:col' -> (line, col); пусто/мусор -> (0, 0)."""
    if s and ":" in s:
        a, b = s.split(":", 1)
        try:
            return int(a), int(b)
        except ValueError:
            pass
    return 0, 0


def read_fo_geometry(reports_dir: Path):
    """Геометрия входа/выхода ФО — из Перечень_ФО(процедур_функций).csv
    (колонки "Позиция входа"/"Позиция выхода", считаются в
    functional_objects.ql). Формат результата: kind/func/file/ref_line/
    open_line/open_col/has_block/close_line/close_col/btype — это и
    ожидает main()."""
    pts = []
    p = reports_dir / "Перечень_ФО(процедур_функций).csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if not (row and row[0].strip() and len(row) > 5 and row[1].strip()):
                continue
            name = row[1].strip()
            m = re.match(r'^(.*)\((\d+)\)$', row[2].strip()) if row[2].strip() else None
            if not m:
                continue
            file, ref_line = m.group(1), int(m.group(2))
            open_line, open_col = _parse_pos(row[4].strip())
            close_line, close_col = _parse_pos(row[5].strip())
            pts.append({"kind": "entry", "func": name, "file": file, "ref_line": ref_line,
                        "open_line": open_line, "open_col": open_col, "has_block": 0,
                        "close_line": close_line, "close_col": close_col, "btype": "-"})
    return pts


def read_branch_geometry(reports_dir: Path):
    """Геометрия ветвей — из Перечень_ветвей.csv (колонка "Позиция вставки",
    считается в function_flow.ql/viz/flowchart_generator.py). catch — обычные
    строки этого же отчёта (Тип=catch), со своим номером ветви (не общим с
    try)."""
    pts = []
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if not (len(row) >= 8 and row[2].strip() and row[6].strip()):
                continue
            func, btype, file, ref_line = row[2].strip(), row[4].strip(), row[5].strip(), int(row[6])
            open_line, open_col = _parse_pos(row[7].strip())
            has_block = 2 if btype in ("case", "default") else 1
            pts.append({"kind": "branch", "func": func, "file": file, "ref_line": ref_line,
                        "open_line": open_line, "open_col": open_col, "has_block": has_block,
                        "close_line": 0, "close_col": 0, "btype": btype})
    return pts


def _file_matches(a, b) -> bool:
    if not a or not b:
        return False
    from core.file_lists import path_matches_list
    return path_matches_list(a, [b]) or path_matches_list(b, [a])


def _pick_by_file(cands, file, line=None):
    """cands — список (номер, файл[, строка]) для одного имени. Один
    кандидат — однозначно он. При коллизии (одноимённые методы в разных
    классах/файлах) — сначала файл+строка точно (различает перегрузки в
    одном файле), затем только файл; иначе — первый кандидат."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0][0]
    if file and line:
        for cand in cands:
            cline = cand[2] if len(cand) > 2 else None
            if cline == line and _file_matches(cand[1], file):
                return cand[0]
    if file:
        for cand in cands:
            if _file_matches(cand[1], file):
                return cand[0]
    return cands[0][0]


def _lookup_fo(fn: str, file: str, line, fo_num: dict) -> int | None:
    return _pick_by_file(fo_num.get(fn), file, line)


def _pick_by_branch(cands, file, ins_col):
    """См. instrument_cpp.py::_pick_by_branch — точное совпадение колонки
    вставки различает if/else однострочной формы (одна "Строка", разный
    ins_col), затем файл, иначе первый кандидат."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0][0]
    if ins_col:
        for num, cfile, ccol in cands:
            if ccol == ins_col and (not file or not cfile or _file_matches(cfile, file)):
                return num
    if file:
        for num, cfile, _ in cands:
            if _file_matches(cfile, file):
                return num
    return cands[0][0]


def _lookup_br(fn: str, ref_line: int, file: str, ins_col, br_num: dict) -> int | None:
    for d in (0, 1, -1, 2, -2):
        cands = br_num.get((fn, ref_line + d))
        if cands:
            return _pick_by_branch(cands, file, ins_col)
    return None




_SYNTHETIC_INIT_SUFFIXES = (".<clinit>", ".<obinit>")


def dedupe_probe_points(pts, log=print):
    """Убирает точки вставки с полностью совпадающей геометрией (kind/file/
    open_line/open_col/close_line/close_col).

    Для класса без явного static{}/instance-блока в исходнике CodeQL всё
    равно синтезирует и <clinit>, и <obinit>, и у обоих "тело" вырождено в
    одну и ту же позицию сразу после `{` объявления класса. Такая пара
    отбрасывается без счёта в "Дубликатов отброшено" — это не аномалия,
    а штатное расхождение модели CodeQL с реальным исходником.
    getLocation() у <clinit>/<obinit> почти всегда указывает на класс
    независимо от того, есть явный блок или нет, поэтому различить
    синтетическую пару от настоящей на уровне .ql-запроса нельзя.

    Любая другая дублирующаяся геометрия (другой kind, либо не пара
    <clinit>/<obinit>) — настоящая аномалия, считается и логируется."""
    seen = {}
    out = []
    dup = 0
    for pt in pts:
        key = (pt["kind"], pt["file"], pt["open_line"], pt["open_col"],
               pt["close_line"], pt["close_col"])
        if key in seen:
            kept_func = seen[key]
            if not (pt["kind"] == "entry"
                     and pt["func"].endswith(_SYNTHETIC_INIT_SUFFIXES)
                     and kept_func.endswith(_SYNTHETIC_INIT_SUFFIXES)):
                dup += 1
            continue
        seen[key] = pt["func"]
        out.append(pt)
    if dup and log:
        log(f"[3] Дубликатов геометрии точек вставки отброшено: {dup} "
            f"(одна и та же позиция вставки пришла от нескольких CodeQL-сущностей)")
    return out


def _insertion_is_valid(ln: str, eff: int, prio: int, has_block: int = 1) -> bool:
    """Геометрия из CodeQL иногда не попадает на границу токена (вставка
    приходится внутрь имени метода/переменной, разрезая идентификатор
    пополам). Открывающая вставка с has_block=1 (prio=0: вход ФО или ветвь
    if/for/while/do/try/catch/else) всегда должна идти сразу после '{',
    закрывающая (prio=1: выход ФО) — строго на месте '}' тела (см.
    add_ins/ins_col в main: открытие — ins_col как 0-based индекс после '{',
    закрытие — close_col-1 как 0-based индекс самого '}'). has_block=2
    (case/default метка switch) — датчик ставится сразу после ':' без
    обёртки в {} (см. instrument_cpp.py: op "direct"), поэтому символьной
    проверки тут нет — только границы строки. has_block=0 (вход ФО) —
    символ перед позицией либо '{' (обычное тело), либо ';' (явный
    super()/this() в конструкторе, см. explicitCtorCall — вставка ставится
    сразу после этого оператора). Если это не так — позиция недостоверна,
    и лучше пропустить датчик (см. dropped_sids), чем испортить синтаксис."""
    if prio == 1:
        return eff < len(ln) and ln[eff] == "}"
    if has_block == 2:
        return 0 <= eff <= len(ln)
    if has_block == 0:
        return eff > 0 and ln[eff - 1] in ("{", ";")
    return eff > 0 and ln[eff - 1] == "{"


def detect_package(files):
    rx = re.compile(r"^\s*package\s+([\w.]+)\s*;")
    from collections import Counter
    c = Counter()
    for f in files:
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
            m = rx.match(line)
            if m:
                c[m.group(1)] += 1
                break
    return c.most_common(1)[0][0] if c else ""


def match_file_by_base(probe_path: str, by_base: dict):
    """Сопоставляет абсолютный путь probe (build-машина) извлечённому файлу
    по СОВПАДЕНИЮ ХВОСТА пути, а не только по basename. by_base — индекс
    basename -> [(relpath_к_out, Path), ...] (см. main()).

    Два разных файла могут делить один basename (напр.
    java/lang/CharacterData.java, исключённый фильтром извлечения, и
    org/w3c/dom/CharacterData.java, обычный) — endswith-проверка обязательна
    даже для единственного кандидата по basename, иначе геометрия одного
    файла может применится к другому: лучше не найти позицию (см. add_ins в
    main(): fpath is None -> точка пропускается), чем испортить чужой файл."""
    pp = probe_path.replace("\\", "/")
    cands = by_base.get(pp.rsplit("/", 1)[-1], [])
    best = None
    for rel, p in cands:
        if pp.endswith("/" + rel) and (best is None or len(rel) > len(best[0])):
            best = (rel, p)
    return best[1] if best else None


def match_file_by_relpath(probe_path: str, prefix: str, by_relpath: dict, by_base: dict):
    """Сопоставляет probe-путь файлу УСТРАНЯЯ САМУ ПРИЧИНУ коллизии по
    basename (см. match_file_by_base), а не только её симптом: probe_path —
    абсолютный путь build-машины, prefix — тот же общий префикс, который
    extract_project_sources() (core/file_lists.py::detect_db_prefix) обрезал
    при извлечении в --out, поэтому probe_path с обрезанным prefix даёт
    РОВНО ТОТ ЖЕ относительный путь, что и реальный файл на диске — точное
    совпадение по словарю {relpath: Path}, без эвристик и без риска, что
    два разных файла с одинаковым именем (java/lang/CharacterData.java —
    bootstrap-исключён, и org/w3c/dom/CharacterData.java — обычный) будут
    спутаны. Если точного совпадения нет (probe ссылается на файл, который
    не был извлечён вообще — напр. bootstrap-исключённый, или иной фильтр)
    — откатывается на basename+endswith (match_file_by_base) для
    устойчивости к редким расхождениям нормализации путей."""
    norm = probe_path.replace("\\", "/").lstrip("/")
    rel = norm[len(prefix):] if prefix and norm.startswith(prefix) else norm
    exact = by_relpath.get(rel)
    if exact is not None:
        return exact
    return match_file_by_base(probe_path, by_base)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="java")
    ap.add_argument("--trace-tag", default="",
                    help="Префикс имени файла трасс (LANG в Cqtrace.java), напр. <project>-java — "
                         "чтобы трассы разных проектов не путались в общем $HOME. "
                         "По умолчанию = --lang.")
    ap.add_argument("--pattern", default="", help="Паттерн пути проекта для isProjectFile")
    ap.add_argument("--include-list", default="", help="Текстовый файл — белый список путей (по одному на строку)")
    ap.add_argument("--exclude-list", default="", help="Текстовый файл — чёрный список путей (по одному на строку)")
    ap.add_argument("--no-branches", action="store_true",
                    help="инструментировать только вход/выход ФО, без датчиков ветвей")
    ap.add_argument("--no-syntax-check", action="store_true",
                    help="пропустить проверку javac (для Maven/Gradle — её роль выполнит сборка; "
                         "javac всех файлов сразу всё равно требует classpath/зависимости).")
    ap.add_argument("--cqtrace-package", default="",
                    help="Java-пакет класса рантайма Cqtrace; ссылка везде <пакет>.Cqtrace.hit(). "
                         "По умолч. автоопределение берёт самый частый пакет — в БОЛЬШИХ проектах "
                         "это тестовый (src/test), и main его не видит. Для Maven задайте ОБЩИЙ "
                         "корень, напр. org.h2.")
    ap.add_argument("--cqtrace-dir", default="",
                    help="каталог для Cqtrace.java (относительно копии); должен соответствовать "
                         "пакету и компилироваться в MAIN-фазе, напр. src/main/org/h2 "
                         "(вместе с --cqtrace-package org.h2).")
    ap.add_argument("--sensor-include-list", default="",
                    help="Текстовый файл — белый список шаблонов/путей ВСТАВКИ ДАТЧИКОВ "
                         "(по одному на строку, см. core/file_lists.py). Доп. к --pattern/ "
                         "--include-list (область проекта); пусто = не сужает.")
    ap.add_argument("--sensor-exclude-list", default="",
                    help="Текстовый файл — чёрный список шаблонов/путей, которые НЕ получат "
                         "датчиков (напр. пакеты раннего bootstrap JVM — java/lang/**, "
                         "java/util/concurrent/** — датчик там вызывается до готовности VM "
                         "диспетчеризовать вызов метода и валит нативный SIGSEGV; без правки "
                         "кода инструментатора под конкретный проект).")
    args = ap.parse_args()
    # Резолвим codeql как статический анализатор (локальный codeql-win/codeql-linux)
    import sys as _sys
    _sys.path.insert(0, str(HERE.parent))
    try:
        from core.codeql_analyzer import _find_codeql
        args.codeql = _find_codeql(args.codeql)
        print(f"[codeql] {args.codeql}")
    except Exception:
        pass
    from core.file_lists import extract_project_sources, read_file_list, sensor_filter_factory

    db_path = Path(args.db).resolve()
    out = Path(args.out).resolve()
    reports = Path(args.reports).resolve()

    include_list = read_file_list(args.include_list) if args.include_list else None
    exclude_list = read_file_list(args.exclude_list) if args.exclude_list else None
    sensor_include = read_file_list(args.sensor_include_list) if args.sensor_include_list else None
    sensor_exclude = read_file_list(args.sensor_exclude_list) if args.sensor_exclude_list else None
    _sensor_counts: dict = {}
    _sensor_filter = sensor_filter_factory(sensor_include, sensor_exclude, counters=_sensor_counts)

    # 1. Дерево исходников — прямо из src.zip БД (точный снэпшот того, что
    # реально анализировал CodeQL), как у C/C++ (см. core/file_lists.py).
    print(f"[1] Извлекаю дерево исходников из src.zip БД -> {out} ...")
    from instrument_c_make import _pattern_filter_factory
    _base_filter = _pattern_filter_factory(args.pattern)
    if sensor_exclude or sensor_include:
        print(f"    Доп. фильтр вставки датчиков: белый список "
              f"{len(sensor_include or [])} шабл., чёрный {len(sensor_exclude or [])} шабл.")

    # Базовый --pattern проверяем ПЕРВЫМ, а не вместе с _sf: иначе счётчики
    # sensor_filter_factory засорялись бы файлами, которые в любом случае
    # вне области проекта (--pattern) — счёт должен отражать именно то,
    # что реально вырезали белый/чёрный списки датчиков, а не общий шум.
    def _extract_filter(zip_path, _base=_base_filter, _sf=_sensor_filter):
        if _base and not _base(zip_path):
            return False
        return _sf(zip_path)

    extract_res = extract_project_sources(
        db_path, out,
        pattern_filter=_extract_filter,
        include_patterns=include_list, exclude_patterns=exclude_list,
        include_list=include_list, exclude_list=exclude_list, log=print)
    if extract_res["generated_skipped"]:
        print(f"    Внимание: {extract_res['generated_skipped']} сгенерированных во время "
              f"сборки файлов потенциально доступны в БД, но отсеяны текущим фильтром "
              f"(--pattern/--include-list/--exclude-list).")
    if sensor_exclude or sensor_include:
        print(f"[1.1] Фильтр вставки датчиков: исключено чёрным списком "
              f"{_sensor_counts.get('excluded', 0)}, не подошло белому списку "
              f"{_sensor_counts.get('not_in_whitelist', 0)}")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    # 3. Точки вставки — геометрия считана прямо в статике
    # (functional_objects.ql/function_flow.ql/catch_points.ql). Читаем её из
    # тех же CSV, из которых уже взяты fo_num/br_num выше — один источник
    # истины.
    pts = read_fo_geometry(reports) + read_branch_geometry(reports)
    print(f"[3] Точек вставки: {len(pts)} (из отчётов статики)")
    pts = dedupe_probe_points(pts)

    all_java = list(out.rglob("*.java"))
    pkg = args.cqtrace_package or detect_package(all_java)
    # Ссылка на датчик — простое имя "Cqtrace.hit(...)", не полный путь
    # "<pkg>.Cqtrace.hit(...)". При полном пути первый сегмент пакета (com,
    # sun, se, spi, java, org) резолвится Java как обычное простое имя: если
    # в зоне видимости есть локальная переменная/параметр/поле с этим же
    # именем, компилятор трактует "com.sun...." как доступ к полю на этой
    # переменной, а не как путь пакета — ошибка компиляции. Простое имя
    # класса такой проблемы не создаёт: вызов метода `hit(...)` резолвится
    # Java только среди методов (отдельное пространство имён от переменных —
    # JLS 6.5.5/6.5.6). Используем import + простое имя типа, а не import
    # static: static-импорт рискует столкнуться с собственным методом класса
    # по имени "hit" (member-функции приоритетнее static-импорта при
    # разрешении вызова без квалификатора). Импорт вставляется в каждый
    # инструментированный файл отдельным проходом ниже (после применения
    # вставок датчиков, чтобы не сдвигать номера строк геометрии).
    ref = "Cqtrace"
    print(f"    Пакет Cqtrace: {pkg or '(default)'} → ссылка {ref}.hit(...) "
          f"(+ import {pkg}.Cqtrace; в каждый инструментированный файл)" if pkg
          else f"    Пакет Cqtrace: (default) → ссылка {ref}.hit(...)")

    # Индекс по basename → [(relpath, Path)] — фоллбэк-эвристика
    # (match_file_by_base), и точный индекс по relpath (тот же prefix, что
    # extract_project_sources обрезал при извлечении) — основной путь
    # сопоставления, см. match_file_by_relpath.
    from collections import defaultdict
    by_base = defaultdict(list)
    by_relpath = {}
    for p in all_java:
        rel = p.relative_to(out).as_posix()
        by_base[p.name].append((rel, p))
        by_relpath[rel] = p
    _extract_prefix = extract_res.get("prefix", "")

    def match_file(probe_path):
        return match_file_by_relpath(probe_path, _extract_prefix, by_relpath, by_base)

    ins = {}; sensor_map = []; skipped = []; touched = set()
    dropped_sids = set()

    # prio: при совпадении (строка, позиция) — вставка «перед }» (prio=1) идёт
    # раньше «после {» (prio=0). Нужно для пустых тел `{}`, где обе позиции совпадают.
    # has_block передаётся в _insertion_is_valid: =2 (case/default) — без
    # проверки символа '{' перед позицией (см. _insertion_is_valid).
    def add_ins(fpath, line, eff_index, prio, text, sid, has_block=1):
        ins.setdefault(fpath, []).append((line, eff_index, prio, text, sid, has_block)); touched.add(fpath)

    sid = 1
    no_file_match = 0
    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue  # отключена инструментация ветвей
        fpath = match_file(pt["file"])
        if fpath is None:
            # Точка геометрии указывает на файл, которого нет в --out (не
            # извлечён вообще — отфильтрован --pattern/include-list/
            # exclude-list/sensor-фильтром, или просто не нашёлся basename-
            # резолвером). РАНЬШЕ эта потеря не попадала ни в `skipped`, ни в
            # один лог — "[4] Датчиков (потенциально)" её не учитывал вовсе,
            # хотя она часть общего разрыва между геометрией и итогом.
            no_file_match += 1
            continue
        base = fpath.relative_to(out).as_posix()
        fn = pt["func"]
        fo = _lookup_fo(fn, pt["file"], pt["ref_line"], fo_num)
        if fo is None:
            skipped.append((fn, pt["kind"], "ФО нет в Перечень_ФО")); continue
        if pt["kind"] == "entry":
            if pt["open_col"] <= 0 or pt["close_col"] <= 0:
                skipped.append((fn, "entry", "нет позиции тела")); continue
            se, sx = sid, sid + 1; sid += 2
            # has_block=0: вход ФО — открывающая вставка ставится либо сразу
            # после '{' тела (обычный случай), либо сразу после super()/
            # this() (явный вызов в конструкторе, см. explicitCtorCall) —
            # там перед позицией ';', а не '{'. Оба случая легитимны для
            # kind="entry", поэтому _insertion_is_valid
            # принимает любой из двух символов (в отличие от has_block=1,
            # где ветвь однозначно начинается строго после '{').
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, 0); try {{", se, has_block=0)
            add_ins(fpath, pt["close_line"], pt["close_col"] - 1, 1,
                    f"}} finally {{ {ref}.hit({fo}, -1); }} ", sx)
            sensor_map.append((se, fo, 0, base, pt["open_line"], "вход"))
            sensor_map.append((sx, fo, -1, base, pt["close_line"], "выход"))
        else:
            bn = _lookup_br(fn, pt["ref_line"], pt["file"], pt["open_col"], br_num)
            if bn is None:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей")); continue
            if pt["open_col"] <= 0:
                skipped.append((fn, "branch", "нет позиции блока")); continue
            s = sid; sid += 1
            if pt.get("has_block") == 2:
                # case/default: ins_col — 1-based позиция символа после ':';
                # -1 переводит её в 0-based индекс (мирроринг instrument_cpp.py,
                # op "direct").
                add_ins(fpath, pt["open_line"], pt["open_col"] - 1, 0,
                        f" {ref}.hit({fo}, {bn});", s, has_block=2)
            else:
                add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, {bn});", s)
            sensor_map.append((s, fo, bn, base, pt["open_line"], pt["btype"]))

    print(f"[4] Датчиков (потенциально): {sid - 1} (пропущено точек: {len(skipped)})")
    if no_file_match:
        print(f"[3.1] Точек геометрии без файла в --out (не извлечён — "
              f"--pattern/include-list/exclude-list/чёрный список датчиков, "
              f"или basename не резолвится): {no_file_match}")

    for fp in touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        for line, eff, prio, text, sid_, has_block in sorted(ins[fp], key=lambda x: (x[0], x[1], x[2]), reverse=True):
            idx = line - 1
            if idx < 0 or idx >= len(lines):
                dropped_sids.add(sid_); continue
            ln = lines[idx]; nl = ""
            if ln.endswith("\r\n"): ln, nl = ln[:-2], "\r\n"
            elif ln.endswith("\n"): ln, nl = ln[:-1], "\n"
            if eff < 0 or eff > len(ln):
                dropped_sids.add(sid_); continue
            if not _insertion_is_valid(ln, eff, prio, has_block):
                dropped_sids.add(sid_); continue
            lines[idx] = ln[:eff] + text + ln[eff:] + nl
        fp.write_text("".join(lines), encoding="utf-8")

    # import <pkg>.Cqtrace; в каждый инструментированный файл — отдельным
    # проходом после применения вставок датчиков (геометрия выше привязана
    # к исходной нумерации строк; вставка лишней строки до этого момента
    # сдвинула бы все последующие координаты).
    # Без пакета (default package) импорт не нужен и невозможен (классы
    # default package не импортируются) — там ref="Cqtrace" работает только
    # если вызывающий файл САМ в default package (см. ref/print выше).
    if pkg:
        _pkg_re = re.compile(r'^\s*package\s+[\w.]+\s*;', re.M)
        _import_line = f"import {pkg}.Cqtrace;\n"
        for fp in touched:
            text = fp.read_text(encoding="utf-8", errors="ignore")
            m = _pkg_re.search(text)
            if m:
                nl_idx = text.find("\n", m.end())
                pos = nl_idx + 1 if nl_idx != -1 else len(text)
            else:
                pos = 0
            fp.write_text(text[:pos] + _import_line + text[pos:], encoding="utf-8")

    if dropped_sids:
        sensor_map = [sm for sm in sensor_map if sm[0] not in dropped_sids]
        print(f"[4.1] Датчиков не вставлено (вне границ файла или вне границы "
              f"токена — недостоверная геометрия CodeQL): {len(dropped_sids)}")

    # Рантайм Cqtrace.java — в КАТАЛОГ пакета (для Maven: src/main/org/h2/Cqtrace.java).
    tmpl = (RUNTIME / "Cqtrace.java.tmpl").read_text(encoding="utf-8")
    cq = tmpl.replace("@PACKAGE@", pkg if pkg else "")
    cq = cq.replace("@LANG@", args.trace_tag or args.lang)
    if not pkg:
        cq = cq.replace("package ;\n", "")     # default package — без объявления
    cq_dir = out                                # каталог для Cqtrace.java
    if args.cqtrace_dir:
        cq_dir = out / args.cqtrace_dir
        cq_dir.mkdir(parents=True, exist_ok=True)
    elif pkg:
        # находим каталог любого файла, объявляющего ровно пакет pkg
        pat = re.compile(r"^\s*package\s+" + re.escape(pkg) + r"\s*;", re.M)
        for p in all_java:
            try:
                if pat.search(p.read_text(encoding="utf-8", errors="ignore")[:400]):
                    cq_dir = p.parent; break
            except Exception:
                pass
    (cq_dir / "Cqtrace.java").write_text(cq, encoding="utf-8")
    print(f"[5.1] Рантайм (исходник): {(cq_dir / 'Cqtrace.java').relative_to(out)}")

    # cqtrace-runtime.jar — для legacy-сборок с НЕСКОЛЬКИМИ независимыми
    # корнями исходников на один и тот же пакет (типично для многомодульных
    # Ant/autotools-сборок вида OpenJDK: jdk/corba/langtools и т.п., каждый
    # со своим javac-вызовом и своим sourcepath). Единственная физическая
    # копия .java видна ТОЛЬКО тому javac-вызову, чей sourcepath включает её
    # каталог — поэтому для других корней та же ссылка <pkg>.Cqtrace.hit(...)
    # даёт "cannot find symbol". .jar в CLASSPATH резолвится независимо от
    # sourcepath/каталога — единая копия видна всем javac-вызовам сборки.
    # Класть .java-копию ВО ВСЕ каталоги пакета не годится: при рекурсивной
    # сборке (wildcard/find по дереву) несколько копий в одном javac-вызове
    # дают "duplicate class" (тот же класс багов, что и sun.misc.Version в
    # gen_profile_2/3/gensrc), а если они всё же компилируются РАЗНО по
    # разным выходным деревьям — состояние датчиков (счётчики, маршруты
    # R:/C:) расщепляется по экземплярам класса вместо одного общего.
    # javac/jar резолвим как codeql (_find_codeql): сначала бандл-JDK из
    # third-party/jdk*, затем PATH. Без этого на типичной GUI-поставке (JDK не
    # в PATH, JAVA_HOME не задан) шаг падал FileNotFoundError на голом "javac".
    javac = _find_jdk_tool("javac")
    jar_tool = _find_jdk_tool("jar")

    cqtrace_jar = None
    if not javac:
        print("[5.2] !!! javac не найден (ни в third-party/jdk*, ни в PATH) — "
              "cqtrace-runtime.jar не собран. Датчики уже вставлены; чтобы собрать "
              "jar и проверить синтаксис, поставьте JDK (напр. third-party/jdk25-win) "
              "или добавьте javac в PATH.")
    else:
        jar_build = out / ".cqtrace_jar_build"
        jar_build.mkdir(exist_ok=True)
        jar_src = jar_build / "src" / (Path(*pkg.split(".")) if pkg else Path("."))
        jar_src.mkdir(parents=True, exist_ok=True)
        (jar_src / "Cqtrace.java").write_text(cq, encoding="utf-8")
        jar_classes = jar_build / "classes"; jar_classes.mkdir(exist_ok=True)
        # -encoding utf-8 обязателен: Cqtrace.java.tmpl содержит кириллические
        # комментарии, а javac без явной кодировки берёт платформную (cp1251 на
        # русской Windows) и падает "unmappable character for encoding Cp1251" —
        # сборка jar отваливалась бы НА ЛЮБОЙ такой машине независимо от проекта.
        # --release 8: jar собирается бандл-JDK (часто свежий, напр. jdk25-win),
        # а cqtrace-runtime.jar потом грузится JVM ИНСТРУМЕНТИРУЕМОГО проекта —
        # она может быть Java 8 (как у gosjava-8u352). Class-файл, собранный без
        # --release под более новый JDK, новее версии байткода, чем умеет старая
        # JVM — UnsupportedClassVersionError при запуске. Сам Cqtrace.java не
        # использует API новее Java 8 (см. Cqtrace.java.tmpl), так что --release 8
        # ничего не ломает.
        rj = subprocess.run([javac, "-encoding", "utf-8", "--release", "8",
                            "-d", str(jar_classes),
                            str(jar_src / "Cqtrace.java")], capture_output=True, text=True)
        if rj.returncode != 0 and "--release" in (rj.stderr or ""):
            # javac < 9 не понимает --release (флаг появился в JDK 9) — откат
            # на компиляцию дефолтным таргетом самого javac.
            rj = subprocess.run([javac, "-encoding", "utf-8", "-d", str(jar_classes),
                                str(jar_src / "Cqtrace.java")], capture_output=True, text=True)
        if rj.returncode == 0 and jar_tool:
            cqtrace_jar = out / "cqtrace-runtime.jar"
            # Повторная инструментация в ТОТ ЖЕ --out (без очистки workspace
            # между прогонами — обычный случай при итеративной доводке большого
            # проекта): если предыдущий прогон упал РОВНО на этом шаге (см.
            # check=True ниже — исключение прерывает скрипт ДО финальной чистки
            # .cqtrace_jar_build), на диске может остаться объект с этим именем,
            # несовместимый с открытием на запись через FileOutputStream — `jar`
            # падает "Cannot create a file when that file already exists" (если
            # это каталог). Без явной чистки скрипт ломался на ЛЮБОМ повторном
            # запуске после первого сбоя именно тут.
            if cqtrace_jar.is_dir():
                shutil.rmtree(cqtrace_jar, ignore_errors=True)
            elif cqtrace_jar.exists():
                cqtrace_jar.unlink()
            subprocess.run([jar_tool, "-cf", str(cqtrace_jar), "-C", str(jar_classes), "."], check=True)
            print(f"[5.2] Рантайм (jar): {cqtrace_jar.relative_to(out)} — добавьте в CLASSPATH "
                  f"сборки (напр. export CLASSPATH=\"$CLASSPATH:{cqtrace_jar}\"), если "
                  f"пакет {pkg or '(default)'} компилируется НЕСКОЛЬКИМИ независимыми "
                  f"javac-вызовами с разным sourcepath (модульная/legacy-сборка).")
        elif rj.returncode == 0:
            print("[5.2] !!! Cqtrace.java скомпилирован, но jar не найден "
                  "(third-party/jdk*/PATH) — jar не собран, остаётся только исходник.")
        else:
            print(f"[5.2] !!! Не удалось собрать cqtrace-runtime.jar: "
                  f"{rj.stderr.strip().splitlines()[-1] if rj.stderr.strip() else rj.returncode} "
                  f"— остаётся только исходник, см. выше.")
        shutil.rmtree(jar_build, ignore_errors=True)

    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sid", "№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)

    # Проверка синтаксиса — javac всех плоских .java (только для мелких проектов).
    # Для проектов со своей сборкой (Maven/Gradle) её роль выполняет последующая сборка.
    if args.no_syntax_check or not javac:
        _why = ("--no-syntax-check; проверит сборка" if args.no_syntax_check
                else "javac недоступен (нет JDK в third-party/jdk*/PATH)")
        print(f"[6] Проверка синтаксиса пропущена ({_why}).")
    else:
        # Cqtrace резолвим через cqtrace_jar (-classpath), а не добавлением
        # исходника cq_dir/Cqtrace.java в файлы компиляции: если бы класс
        # пришлось РЕЗОЛВИТЬ через sourcepath (а не передать явным файлом),
        # touched-подмножество (только датчики, без полного дерева) не дало
        # бы javac найти cq_dir по относительному пакетному пути. С jar
        # резолюция не зависит от того, какие каталоги выжили после прунинга.
        # Если jar не собрался (см. выше) — откатываемся на старое поведение:
        # передаём исходник Cqtrace.java явным файлом компиляции.
        _check_set = touched if cqtrace_jar else (touched | {cq_dir / "Cqtrace.java"})
        java_files = [str(p.relative_to(out)) for p in sorted(_check_set)]
        print(f"[6] Проверка синтаксиса (javac, файлов: {len(java_files)})...")
        chk = out / ".syntax_check"; chk.mkdir(exist_ok=True)
        # @argfile — иначе при тысячах файлов командная строка превышает лимит
        # Windows CreateProcess (WinError 206 "имя файла или его расширение
        # имеет слишком большую длину"), даже когда каждый путь сам по себе
        # короткий: ограничение — на суммарную длину, а не на отдельный аргумент.
        argfile = out / ".javac_args.txt"
        with open(argfile, "w", encoding="utf-8") as fh:
            for jf in java_files:
                fh.write(f'"{jf}"\n' if " " in jf else jf + "\n")
        javac_cmd = [javac, "-encoding", "utf-8", "-d", str(chk)]
        if cqtrace_jar:
            javac_cmd += ["-classpath", str(cqtrace_jar)]
        javac_cmd.append(f"@{argfile.name}")
        try:
            r = subprocess.run(javac_cmd, cwd=out, capture_output=True, text=True)
        finally:
            argfile.unlink(missing_ok=True)
        shutil.rmtree(chk, ignore_errors=True)
        errors = [(ln.split(":")[0], ln) for ln in r.stderr.splitlines() if ": error:" in ln]
        if errors:
            with open(out / "Отчёт_об_ошибках_вставки.csv", "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, delimiter=";"); w.writerow(["Файл", "Ошибка"]); w.writerows(errors)
            print(f"[7] !!! Ошибок: {len(errors)} — см. Отчёт_об_ошибках_вставки.csv")
            sys.exit(2)
        print("[7] Синтаксис OK.")

    # Pruning: оставляем только инструментированные файлы + рантайм
    _runtime_java = cq_dir / "Cqtrace.java"
    _pruned = 0
    for _p in list(out.rglob("*.java")):
        if _p != _runtime_java and _p not in touched:
            _p.unlink()
            _pruned += 1
    for _d in sorted([_d for _d in out.rglob("*") if _d.is_dir()],
                     key=lambda x: len(x.parts), reverse=True):
        try:
            _d.rmdir()
        except OSError:
            pass
    if _pruned:
        print(f"[8] Удалено неинструментированных файлов: {_pruned}")
    print(f"[OK] Инструментировано. Датчиков: {len(sensor_map)}")


if __name__ == "__main__":
    main()
