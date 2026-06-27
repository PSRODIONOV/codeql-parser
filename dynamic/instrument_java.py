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

Использование:
  python3 instrument_java.py --db <codeql-db> --reports <static-dir>
      --out <work-dir> [--codeql codeql] [--lang java]
      [--include-list files.txt] [--exclude-list files.txt]
      [--project-db project.db] [--trace-tag <tag>]
"""
import argparse, tempfile, csv, os, re, shutil, subprocess, sys
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

# Пакеты раннего bootstrap JVM: на старте (System.initializeSystemClass и
# раньше) методы этих классов исполняются ДО того, как VM способна
# диспетчеризовать вызов Cqtrace.hit(...) — попытка такого вызова уходит в
# нулевой нативный code-entry и валит JVM SIGSEGV (нативный краш на уровне
# ниже байткода: его не лечит ни re-entrancy guard, ни catch(Throwable) в
# самом hit() — тело hit() просто не успевает начать исполняться). Только
# ПРЯМЫЕ члены пакета (java.lang.* в смысле import-звёздочки, БЕЗ
# подпакетов) — java.lang.reflect/ref/annotation/management и т.п. не входят
# в критический bootstrap-путь и инструментируются как обычно. java.lang.invoke
# исключён отдельно (ASM-генераторы байткода/nasgen дёргают его так же рано).
_BOOTSTRAP_RX = re.compile(
    r"(^|/)java/lang/(invoke/)?[^/]+\.java$"
    r"|(^|/)java/(util|io|nio)/[^/]+\.java$"
)


def _is_bootstrap_path(zip_path: str) -> bool:
    return bool(_BOOTSTRAP_RX.search(zip_path.replace("\\", "/")))


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
    """Перечень_ветвей → {(qualified_name, line): [(branch_num, file), ...]}."""
    br = {}
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                key = (row[2].strip(), int(row[6]))
                file = row[5].strip() if len(row) > 5 and row[5].strip() else None
                br.setdefault(key, []).append((int(row[3]), file))
    return br


def _file_matches(a, b) -> bool:
    if not a or not b:
        return False
    from core.file_lists import path_matches_list
    return path_matches_list(a, [b]) or path_matches_list(b, [a])


def _pick_by_file(cands, file, line=None):
    """cands — список (номер, файл[, строка]) для одного имени. Один
    кандидат — однозначно он. При коллизии (одноимённые методы в разных
    классах/файлах) — сначала файл+строка точно (различает перегрузки в
    одном файле), затем только файл; иначе — первый, как раньше."""
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


def _lookup_br(fn: str, ref_line: int, file: str, br_num: dict) -> int | None:
    for d in (0, 1, -1, 2, -2):
        cands = br_num.get((fn, ref_line + d))
        if cands:
            return _pick_by_file(cands, file)
    return None


def run_probe_query(codeql, db, query, path_pattern="%"):
    content = query.read_text(encoding="utf-8")
    if "${PROJECT_PATTERN}" in content:
        query_to_run = query.parent / f".{query.name}"
        query_to_run.write_text(content.replace("${PROJECT_PATTERN}", path_pattern or "%"), encoding="utf-8")
    else:
        query_to_run = query
    bqrs = Path(tempfile.gettempdir(), "probe_java.bqrs"); csvp = Path(tempfile.gettempdir(), "probe_java.csv")
    subprocess.run([codeql, "query", "run", f"--database={db}", f"--output={bqrs}", str(query_to_run)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(csvp, "w") as out:
        subprocess.run([codeql, "bqrs", "decode", "--format=csv", str(bqrs)],
                       check=True, stdout=out, stderr=subprocess.DEVNULL)
    pts = []
    with open(csvp, encoding="utf-8") as fh:
        r = csv.reader(fh); next(r, None)
        for row in r:
            # kind, func, file, ref_line, ins_line, ins_col, has_block, btype, end_line, end_col
            if len(row) < 10: continue
            pts.append({"kind": row[0], "func": row[1], "file": row[2],
                        "ref_line": int(row[3]), "open_line": int(row[4]), "open_col": int(row[5]),
                        "has_block": int(row[6]),
                        "close_line": int(row[8]), "close_col": int(row[9]), "btype": row[7]})
    return pts


def read_probe_points_from_db(project_db_path: str):
    """Читает геометрию точек вставки из СЫРЫХ ДАННЫХ project.db (раздел
    'probe', собранный на этапе статики через probe_points.ql) — без
    отдельного запроса к CodeQL-БД (см. instrument_cpp.py). Колонки
    queries/java/probe_points.ql названы ТАК ЖЕ, как у C++-варианта
    (ref_line/ins_line/ins_col/end_line/end_col — см. RAW_SCHEMA["q_probe"]
    в core/project_db.py), чтобы одна таблица БД годилась для обоих языков."""
    import sys as _sys
    _sys.path.insert(0, str(HERE.parent))
    from core.project_db import ProjectDB

    def _i(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    proj = ProjectDB.open(project_db_path)
    try:
        rows = proj.load_raw_data().get("probe", [])
    finally:
        proj.close()
    pts = []
    for r in rows:
        pts.append({
            "kind": r.get("kind", ""), "func": r.get("func", ""), "file": r.get("file", ""),
            "ref_line": _i(r.get("ref_line")), "open_line": _i(r.get("ins_line")),
            "open_col": _i(r.get("ins_col")), "has_block": _i(r.get("has_block")),
            "close_line": _i(r.get("end_line")),
            "close_col": _i(r.get("end_col")), "btype": r.get("btype", ""),
        })
    return pts


def dedupe_probe_points(pts, log=print):
    """Убирает точки вставки с ПОЛНОСТЬЮ совпадающей геометрией (kind/file/
    open_line/open_col/close_line/close_col). CodeQL может вернуть НЕСКОЛЬКО
    разных сущностей Callable/Stmt для ОДНОЙ физической точки исходника —
    напр. generic-инстанцирование/raw-типы дают отдельные Method-сущности с
    одинаковым телом и локацией, но разным func (qname зависит от того, через
    какой generic-контекст CodeQL видит declaring type). Без дедупликации
    КАЖДАЯ лишняя строка добавляет ЕЩЁ ОДНУ вставку в ТУ ЖЕ позицию — реальный
    кейс на большом проекте: один try получал два finally (невалидный
    синтаксис), сконцентрировано в java.io.* (BufferedReader,
    BufferedInputStream, Bits — raw/generic-heavy классы JDK)."""
    seen = set()
    out = []
    dup = 0
    for pt in pts:
        key = (pt["kind"], pt["file"], pt["open_line"], pt["open_col"],
               pt["close_line"], pt["close_col"])
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        out.append(pt)
    if dup and log:
        log(f"[3] Дубликатов геометрии точек вставки отброшено: {dup} "
            f"(одна и та же позиция вставки пришла от нескольких CodeQL-сущностей)")
    return out


def _insertion_is_valid(ln: str, eff: int, prio: int, has_block: int = 1) -> bool:
    """Геометрия из CodeQL иногда не попадает на границу токена (реальный
    кейс: com.sun.corba...ObjectStreamClass.getFields() — вставка пришлась
    ВНУТРЬ имени метода/переменной, разрезав идентификатор пополам:
    "getField" + датчик + "s()", а закрывающая — внутрь "length"). Открывающая
    вставка с has_block=1 (prio=0: вход ФО ИЛИ ветвь if/for/while/do/try/
    catch/else) ВСЕГДА должна идти СРАЗУ после '{', закрывающая (prio=1:
    выход ФО) — СТРОГО на месте '}' тела (см. add_ins/ins_col в main:
    открытие — ins_col как 0-based индекс ПОСЛЕ '{', закрытие — close_col-1
    как 0-based индекс САМОГО '}'). has_block=2 (case/default метка switch)
    — датчик ставится сразу после ':' без обёртки в {} (см. has_block=2 в
    probe_points.ql и instrument_cpp.py: op "direct"), поэтому символьной
    проверки тут нет — только границы строки (сам факт сдвига на ':'
    проверяется геометрией CodeQL, символ перед позицией может быть любым,
    включая пробел после ':'). has_block=0 (вход ФО) — символ перед позицией
    либо '{' (обычное тело), либо ';' (явный super()/this() в конструкторе,
    см. explicitCtorCall в probe_points.ql — вставка ставится сразу после
    ЭТОГО оператора, который всегда заканчивается ';'). Если это не так —
    позиция недостоверна (рассинхрон строки/колонки в данных CodeQL по
    неизвестной пока причине), и лучше честно пропустить датчик (см.
    dropped_sids), чем молча испортить синтаксис файла."""
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

    Баг (реальный проект, gosjava): java/lang/CharacterData.java
    (bootstrap-исключён из охвата, см. _is_bootstrap_path) и
    org/w3c/dom/CharacterData.java (обычный, входит в охват) — РАЗНЫЕ файлы
    с ОДИНАКОВЫМ basename. Старый код при единственном кандидате по
    basename возвращал его БЕЗ проверки пути — геометрия первого
    (исключённого) файла применялась к случайному совпадению по имени
    (второму, физически не связанному файлу), портя его на произвольных
    байтовых позициях (внутрь javadoc, внутрь идентификаторов). Теперь
    endswith-проверка обязательна ВСЕГДА, даже для единственного кандидата —
    иначе вместо порчи чужого файла датчик просто не находит позицию (см.
    add_ins в main(): fpath is None -> точка пропускается)."""
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
    ap.add_argument("--no-exclude-bootstrap", action="store_true",
                    help="НЕ исключать java.lang.*/java.util.*/java.io.*/java.nio.*/"
                         "java.lang.invoke.* (прямые члены, без подпакетов) из охвата. "
                         "По умолчанию они исключаются: датчик в этих классах вызывается "
                         "на раннем bootstrap JVM, до готовности VM диспетчеризовать вызов "
                         "метода — нативный SIGSEGV, который НЕ лечится ни re-entrancy guard, "
                         "ни catch(Throwable) внутри Cqtrace.hit() (он не успевает начать "
                         "исполняться). Снимайте флаг только если уверены, что эти пакеты "
                         "не входят в реальный охват компиляции вашего проекта.")
    ap.add_argument("--project-db", default="",
                    help="Путь к project.db. Если задан — геометрия точек вставки "
                         "берётся из сырых данных (раздел 'probe'), БЕЗ отдельного "
                         "запроса probe_points.ql к CodeQL-БД.")
    ap.add_argument("--cqtrace-package", default="",
                    help="Java-пакет класса рантайма Cqtrace; ссылка везде <пакет>.Cqtrace.hit(). "
                         "По умолч. автоопределение берёт самый частый пакет — в БОЛЬШИХ проектах "
                         "это тестовый (src/test), и main его не видит. Для Maven задайте ОБЩИЙ "
                         "корень, напр. org.h2.")
    ap.add_argument("--cqtrace-dir", default="",
                    help="каталог для Cqtrace.java (относительно копии); должен соответствовать "
                         "пакету и компилироваться в MAIN-фазе, напр. src/main/org/h2 "
                         "(вместе с --cqtrace-package org.h2).")
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
    from core.file_lists import extract_project_sources, read_file_list

    db_path = Path(args.db).resolve()
    out = Path(args.out).resolve()
    reports = Path(args.reports).resolve()

    include_list = read_file_list(args.include_list) if args.include_list else None
    exclude_list = read_file_list(args.exclude_list) if args.exclude_list else None

    # 1. Дерево исходников — прямо из src.zip БД (точный снэпшот того, что
    # реально анализировал CodeQL), как у C/C++ (см. core/file_lists.py).
    print(f"[1] Извлекаю дерево исходников из src.zip БД -> {out} ...")
    from instrument_c_make import _pattern_filter_factory
    _base_filter = _pattern_filter_factory(args.pattern)
    if args.no_exclude_bootstrap:
        _extract_filter = _base_filter
    else:
        def _extract_filter(zip_path, _base=_base_filter):
            if _is_bootstrap_path(zip_path):
                return False
            return _base(zip_path) if _base else True
        print("    Исключаю из охвата java.lang/java.util/java.io/java.nio/"
              "java.lang.invoke (прямые члены) — раннний bootstrap JVM, "
              "см. --no-exclude-bootstrap.")
    extract_res = extract_project_sources(
        db_path, out,
        pattern_filter=_extract_filter,
        include_patterns=include_list, exclude_patterns=exclude_list,
        include_list=include_list, exclude_list=exclude_list, log=print)
    if extract_res["generated_skipped"]:
        print(f"    Внимание: {extract_res['generated_skipped']} сгенерированных во время "
              f"сборки файлов потенциально доступны в БД, но отсеяны текущим фильтром "
              f"(--pattern/--include-list/--exclude-list).")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    # 3. Точки вставки — из сырых данных project.db, если передан, иначе
    # свежим запросом probe_points.ql (fallback для standalone-режима).
    # Раздел 'probe' может быть ПУСТ в project.db, собранном до того, как
    # project_runner.py начал собирать его для языка "java" (миграция БД не
    # переисполняет старые запросы сама) — раньше это давало 0 точек молча.
    # Полная пересборка статики ради одного отсутствующего раздела — дорого
    # (перезапуск ВСЕХ запросов на БД), а нужен только probe_points.ql, поэтому
    # при пустом разделе откатываемся на лёгкий прямой запрос вместо отказа.
    pts = []
    source = ""
    if args.project_db:
        pts = read_probe_points_from_db(args.project_db)
        if pts:
            source = "из сырых данных project.db (раздел 'probe')"
        else:
            print("    Внимание: раздел 'probe' в project.db пуст (БД собрана "
                  "до добавления этого языка в project_runner.py, или статика "
                  "вообще не пересобиралась) — делаю прямой запрос probe_points.ql "
                  "вместо отказа (дешевле полной пересборки статики).")
    if not pts:
        pts = run_probe_query(args.codeql, db_path,
                              HERE.parent / "queries" / args.lang / "probe_points.ql",
                              path_pattern=args.pattern or "%")
        source = "запросом probe_points.ql" + ("" if args.project_db else " (standalone-режим)")
    print(f"[3] Точек вставки: {len(pts)} ({source})")
    pts = dedupe_probe_points(pts)

    all_java = list(out.rglob("*.java"))
    pkg = args.cqtrace_package or detect_package(all_java)
    # ВАЖНО: ссылка на датчик — ПРОСТОЕ имя "Cqtrace.hit(...)", НЕ полный путь
    # "<pkg>.Cqtrace.hit(...)". При полном пути ПЕРВЫЙ сегмент пакета (com,
    # sun, se, spi, java, org — частые куски реальных имён) резолвится Java
    # как обычное простое имя: если в зоне видимости есть локальная
    # переменная/параметр/поле с ЭТИМ ЖЕ именем (своя частая история: "String
    # com = ...", параметр "se", и т.п.), компилятор трактует "com.sun...." как
    # доступ к полю на этой переменной, а не как путь пакета — гарантированная
    # ошибка компиляции на ЛЮБОМ файле с таким совпадением (см. реальный кейс:
    # ConstantSetNode.java — `String com = ...; if (com == null) {
    # com.sun....hit(...)`). Простое имя класса такой проблемы не создаёт:
    # 1) вызов метода `hit(...)` после import static резолвится Java ТОЛЬКО
    # среди методов (отдельное пространство имён от переменных — JLS 6.5.5/
    # 6.5.6) и переменной не подменяется НИКОГДА; 2) при простом доступе
    # "Cqtrace.hit(...)" риск коллизии остаётся только с переменной, буквально
    # названной "Cqtrace" — на практике не встречается (не словарное слово).
    # Поэтому используем import + простое имя типа, а не import static:
    # static-импорт рискует столкнуться с СОБСТВЕННЫМ методом класса по имени
    # "hit" (member функции приоритетнее static-импорта при разрешении вызова
    # без квалификатора), простое имя ТИПА — гораздо более редкая коллизия.
    # Сам импорт вставляется в КАЖДЫЙ инструментированный файл отдельным
    # проходом ниже (после применения вставок датчиков, чтобы не сдвигать
    # номера строк, которыми оперирует probe_points.ql).
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
    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue  # отключена инструментация ветвей
        fpath = match_file(pt["file"])
        if fpath is None: continue
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
            # this() (явный вызов в конструкторе, см. explicitCtorCall в
            # probe_points.ql) — там перед позицией ';', а не '{'. Оба случая
            # легитимны для kind="entry", поэтому _insertion_is_valid
            # принимает любой из двух символов (в отличие от has_block=1,
            # где ветвь однозначно начинается строго после '{').
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, 0); try {{", se, has_block=0)
            add_ins(fpath, pt["close_line"], pt["close_col"] - 1, 1,
                    f"}} finally {{ {ref}.hit({fo}, -1); }} ", sx)
            sensor_map.append((se, fo, 0, base, pt["open_line"], "вход"))
            sensor_map.append((sx, fo, -1, base, pt["close_line"], "выход"))
        else:
            bn = _lookup_br(fn, pt["ref_line"], pt["file"], br_num)
            if bn is None:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей")); continue
            if pt["open_col"] <= 0:
                skipped.append((fn, "branch", "нет позиции блока")); continue
            s = sid; sid += 1
            if pt.get("has_block") == 2:
                # case/default: ins_col из probe_points.ql — 1-based позиция
                # символа ПОСЛЕ ':' (см. has_block=2 там же); -1 переводит её
                # в 0-based индекс этого символа (мирроринг instrument_cpp.py,
                # op "direct" — там тот же сдвиг col-1 по той же причине).
                add_ins(fpath, pt["open_line"], pt["open_col"] - 1, 0,
                        f" {ref}.hit({fo}, {bn});", s, has_block=2)
            else:
                add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, {bn});", s)
            sensor_map.append((s, fo, bn, base, pt["open_line"], pt["btype"]))

    print(f"[4] Датчиков (потенциально): {sid - 1} (пропущено точек: {len(skipped)})")

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

    # import <pkg>.Cqtrace; в КАЖДЫЙ инструментированный файл — отдельным
    # проходом ПОСЛЕ применения вставок датчиков (строки/колонки выше — из
    # probe_points.ql, привязаны к ИСХОДНОЙ нумерации строк; вставка лишней
    # строки до этого момента сдвинула бы все последующие координаты).
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
