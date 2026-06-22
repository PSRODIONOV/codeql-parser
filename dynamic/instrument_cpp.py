#!/usr/bin/env python3
"""
Инструментатор датчиков динамического анализа для C/C++.

Вставляет датчики в КОПИЮ исходников проекта:
  - в начало/конец каждого ФО (по Перечень_ФО) — номер ФО;
  - в начало каждой ветви (по Перечень_ветвей) — номер ветви #N.

Нумерация ФО и ветвей берётся ИЗ статических отчётов, поэтому совпадает со
статикой 1:1. Перед завершением выполняется проверка синтаксиса (g++ -fsyntax-only);
ошибки выводятся в Отчёт_об_ошибках_вставки.csv для ручного исправления.

Дерево исходников отдельно передавать не нужно — оно извлекается прямо из
src.zip внутри CodeQL БД (см. core/file_lists.py).

Использование:
  python3 instrument_cpp.py --db <codeql-db> --reports <dir-со-статикой>
      --out <рабочая-копия> [--codeql codeql] [--lang cpp]
      [--include-list files.txt] [--exclude-list files.txt]
"""
import argparse, tempfile, csv, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_compiler(*candidates: str) -> str:
    """Return first compiler found in PATH; last candidate is returned as fallback."""
    for c in candidates:
        if shutil.which(c):
            return c
    return candidates[-1]
RUNTIME = HERE / "runtime"


_DECLARED_AT_RE = re.compile(r'^(.*)\((\d+)\)$')


def _parse_declared_at(s: str):
    """'<путь>(<строка>)' -> (путь, строка) либо (None, None)."""
    m = _DECLARED_AT_RE.match(s.strip())
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _sids_in_text(text: str) -> set:
    """Извлечь sid-ы датчика из текста вставки — для отметки "не вставлен"
    при пропуске inline_candidate (см. dropped_sids в main). __TRACE_FN(fo,
    se, sx) — sid-ы это se/sx (2-е и 3-е число); __TRACE(s, fo, br) — sid
    это s (1-е число)."""
    nums = [int(n) for n in re.findall(r'\d+', text)]
    if text.startswith("__TRACE_FN("):
        return set(nums[1:3])
    return {nums[0]} if nums else set()


def read_fo_numbers(reports_dir: Path):
    """Перечень_ФО → {qualified_name: [(fo_num, file, line), ...]} — СПИСОК,
    а не один номер: разные функции (в разных файлах — static-тёзки,
    перегрузки) могут иметь одинаковый qualified_name. См. _lookup_fo —
    дисамбигуация по файлу из probe_points.ql."""
    fo = {}
    p = reports_dir / "Перечень_ФО(процедур_функций).csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                name = row[1].strip()
                file, line = _parse_declared_at(row[2]) if len(row) > 2 else (None, None)
                fo.setdefault(name, []).append((int(row[0]), file, line))
    return fo


def read_branch_numbers(reports_dir: Path):
    """Перечень_ветвей → {(qualified_name, line): [(branch_num, file), ...]}."""
    br = {}
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            # № п/п, № ФО, ФО, № ветви, Тип, Файл, Строка
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                key = (row[2].strip(), int(row[6]))
                file = row[5].strip() if len(row) > 5 and row[5].strip() else None
                br.setdefault(key, []).append((int(row[3]), file))
    return br


def run_probe_query(codeql: str, db: Path, query: Path, path_pattern: str = "%"):
    """Запускает probe_points.ql, возвращает список словарей-точек."""
    content = query.read_text(encoding="utf-8")
    if "${PROJECT_PATTERN}" in content:
        tmp = query.parent / f".{query.name}"
        tmp.write_text(content.replace("${PROJECT_PATTERN}", path_pattern or "%"), encoding="utf-8")
        query_to_run = tmp
    else:
        query_to_run = query
    bqrs = Path(tempfile.gettempdir(), "probe_points.bqrs")
    csvp = Path(tempfile.gettempdir(), "probe_points.csv")
    subprocess.run([codeql, "query", "run", f"--database={db}",
                    f"--output={bqrs}", str(query_to_run)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(csvp, "w") as out:
        subprocess.run([codeql, "bqrs", "decode", "--format=csv", str(bqrs)],
                       check=True, stdout=out, stderr=subprocess.DEVNULL)
    pts = []
    with open(csvp, encoding="utf-8") as fh:
        r = csv.reader(fh)
        next(r, None)
        for row in r:
            if len(row) < 8:
                continue
            pts.append({
                "kind":      row[0], "func": row[1], "file": row[2],
                "ref_line":  int(row[3]), "ins_line": int(row[4]),
                "ins_col":   int(row[5]), "has_block": int(row[6]), "btype": row[7],
                "end_line":  int(row[8]) if len(row) > 8 else 0,
                "end_col":   int(row[9]) if len(row) > 9 else 0,
            })
    return pts


def read_probe_points_from_db(project_db_path: str):
    """Читает геометрию точек вставки из СЫРЫХ ДАННЫХ project.db (раздел 'probe',
    собранный на этапе статики через probe_points.ql) и возвращает тот же формат,
    что и run_probe_query — но БЕЗ отдельного запроса к CodeQL-БД. Это и есть
    путь «всё берётся из сырых данных»: инструментатор ничего не запрашивает."""
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
            "kind": r.get("kind", ""), "func": r.get("func", ""),
            "file": r.get("file", ""),
            "ref_line": _i(r.get("ref_line")), "ins_line": _i(r.get("ins_line")),
            "ins_col": _i(r.get("ins_col")), "has_block": _i(r.get("has_block")),
            "btype": r.get("btype", ""),
            "end_line": _i(r.get("end_line")), "end_col": _i(r.get("end_col")),
        })
    return pts


def _strip_tpl(name: str) -> str:
    """Удаляет параметры шаблонов из qualified_name: Foo<int>::bar → Foo::bar."""
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r'<[^<>]*>', '', name)
    return name


def _file_matches(a, b) -> bool:
    """Сравнение путей без учёта того, относительный ли это путь или
    абсолютный путь build-машины — см. path_matches_list (тот же критерий,
    что используется для белого/чёрного списка файлов)."""
    if not a or not b:
        return False
    from core.file_lists import path_matches_list
    return path_matches_list(a, [b]) or path_matches_list(b, [a])


def _pick_by_file(cands, file, line=None):
    """cands — список (номер, файл[, строка]) для одного имени. Если ровно
    один кандидат — однозначно он. При нескольких (коллизия одноимённых
    функций) — сперва файл+строка точно (различает перегрузки в ОДНОМ
    файле, напр. 'emit_opcode' на разных строках ad_x86_64.cpp), затем
    только файл (различает static-тёзки в разных файлах); если совпадения
    нет вовсе — берётся первый, как раньше."""
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


def _lookup_fo(fn: str, file: str, line, fo_num: dict, fo_notpl: dict) -> int | None:
    """Ищет номер ФО сначала точно, потом без параметров шаблонов;
    дисамбигуация по файлу+строке при коллизии одноимённых функций."""
    cands = fo_num.get(fn)
    if cands is None:
        cands = fo_notpl.get(_strip_tpl(fn))
    return _pick_by_file(cands, file, line)


def _short_name(qualified_name: str) -> str:
    """Последний сегмент qualified_name после '::' (без параметров шаблонов)
    — то, что должно литерально присутствовать в исходном тексте у функции,
    реально объявленной программистом. Если это не так — функция целиком
    собрана макросом (X-macro вида macro(Name) -> Name##Node::Method, где
    ни 'Name##Node', ни 'Method' не существуют как текст где-либо — только
    аргумент 'Name'), и надёжного места для датчика нет вообще: тот же
    физический файл может многократно #include-иться с разными #define
    macro(x), раскрываясь в разных местах в элемент enum/массива/функцию —
    обёртка '{ датчик; ... }' ломает синтаксис везде, кроме случая функции."""
    return _strip_tpl(qualified_name).rsplit("::", 1)[-1]


def _lookup_br(fn: str, ref_line: int, file: str, br_num: dict) -> int | None:
    """Ищет номер ветви точно, затем со сдвигом ±1/±2 строки; дисамбигуация
    по файлу при коллизии (имя, строка) у разных функций."""
    for d in (0, 1, -1, 2, -2):
        cands = br_num.get((fn, ref_line + d))
        if cands:
            return _pick_by_file(cands, file)
    return None


def _dedup_by_position(pts):
    """Дедупликация по физической позиции вставки: шаблонные методы
    (GrowableArray<E>, HierarchyVisitor<T>::Node и т.п.) инстанцируются
    много раз для разных типов, но ВСЕ инстанциации делят ОДНУ И ТУ ЖЕ
    физическую строку/колонку в файле (текст шаблона написан один раз).
    Если вставлять датчик для КАЖДОЙ инстанциации, все они окажутся в одной
    точке — компилируется (имена переменных-датчиков не конфликтуют), но
    при вызове ОДНОЙ инстанциации сработают датчики ВСЕХ (искажение данных
    покрытия: до сотни "вызовов" на одно реальное событие). Оставляем одну
    точку на (файл, kind, btype, ins_line, ins_col), предпочитая нешаблонную
    форму имени (без '<'), иначе — первую встретившуюся.
    """
    best = {}
    for pt in pts:
        key = (pt["file"], pt["kind"], pt.get("btype", ""), pt["ins_line"], pt["ins_col"])
        cur = best.get(key)
        if cur is None:
            best[key] = pt
        elif "<" in cur["func"] and "<" not in pt["func"]:
            best[key] = pt
    return list(best.values())


def _find_macro_call_end_idx(lines, start_idx: int) -> int:
    """Начиная со start_idx (0-based), находит индекс строки, на которой
    суммарный баланс круглых скобок (открытые минус закрытые), считая с
    этой строки, впервые возвращается к 0 — конец вызова макроса вида
    JVM_ENTRY(...)/JNI_ENTRY(...), сигнатура которого может занимать
    несколько строк (напр. длинный список параметров). Наивный счётчик без
    учёта строк/комментариев — достаточно для сигнатур функций, где они
    практически не встречаются."""
    depth = 0
    started = False
    for i in range(start_idx, len(lines)):
        for ch in lines[i]:
            if ch == '(':
                depth += 1; started = True
            elif ch == ')':
                depth -= 1
        if started and depth <= 0:
            return i
    return start_idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="каталог CodeQL БД")
    ap.add_argument("--reports", required=True, help="каталог со статическими отчётами")
    ap.add_argument("--out", required=True, help="каталог рабочей (инструментируемой) копии")
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="cpp")
    ap.add_argument("--pattern", default="", help="Паттерн пути проекта для isProjectFile")
    ap.add_argument("--include-list", default="", help="Текстовый файл — белый список путей (по одному на строку)")
    ap.add_argument("--exclude-list", default="", help="Текстовый файл — чёрный список путей (по одному на строку)")
    ap.add_argument("--no-branches", action="store_true",
                    help="инструментировать только вход/выход ФО, без датчиков ветвей")
    ap.add_argument("--project-db", default="",
                    help="Путь к project.db. Если задан — геометрия точек вставки "
                         "берётся из сырых данных (раздел 'probe'), БЕЗ отдельного "
                         "запроса probe_points.ql к CodeQL-БД.")
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
    from instrument_c_make import _pattern_filter_factory

    db_path = Path(args.db).resolve()
    out = Path(args.out).resolve()
    reports = Path(args.reports).resolve()

    include_list = read_file_list(args.include_list) if args.include_list else None
    exclude_list = read_file_list(args.exclude_list) if args.exclude_list else None

    # 1. Дерево исходников — прямо из src.zip БД (точный снэпшот того, что
    # реально анализировал CodeQL, включая файлы, появляющиеся только во
    # время сборки — см. core/file_lists.py).
    print(f"[1] Извлекаю дерево исходников из src.zip БД -> {out} ...")
    # См. комментарий в instrument_c_make.py: те же строки передаются и как
    # glob-шаблоны, и как точные/относительные пути — двойная семантика,
    # согласованная с apply_file_filters для статики.
    extract_res = extract_project_sources(
        db_path, out,
        pattern_filter=_pattern_filter_factory(args.pattern),
        include_patterns=include_list, exclude_patterns=exclude_list,
        include_list=include_list, exclude_list=exclude_list, log=print)
    if extract_res["generated_skipped"]:
        print(f"    Внимание: {extract_res['generated_skipped']} сгенерированных во время "
              f"сборки файлов (ADLC/JVMTI/JFR и т.п.) потенциально доступны в БД, но "
              f"отсеяны текущим фильтром (--pattern/--include-list/--exclude-list).")

    # 2. Статические номера
    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    fo_notpl = {}
    for k, v in fo_num.items():
        fo_notpl.setdefault(_strip_tpl(k), []).extend(v)
    fo_total = sum(len(v) for v in fo_num.values())
    br_total = sum(len(v) for v in br_num.values())
    print(f"[2] ФО из статики: {fo_total} (уникальных имён: {len(fo_num)}), "
          f"ветвей: {br_total} (уникальных пар имя/строка: {len(br_num)})")

    # 3. Точки вставки. Основной путь — из СЫРЫХ ДАННЫХ project.db (раздел
    #    'probe', собранный статикой): инструментатор НЕ делает отдельный запрос.
    #    Запрос probe_points.ql остаётся только как fallback для standalone-режима
    #    (analyze_project.py/CLI), где project.db нет.
    if args.project_db:
        pts = read_probe_points_from_db(args.project_db)
        print(f"[3] Геометрия точек вставки: из сырых данных project.db "
              f"(раздел 'probe', без отдельного запроса)")
    else:
        pts = run_probe_query(args.codeql, db_path,
                              HERE.parent / "queries" / args.lang / "probe_points.ql",
                              path_pattern=args.pattern or "%")
        print(f"[3] Геометрия точек вставки: запросом probe_points.ql "
              f"(project.db не передан — standalone-режим)")
    n_before_dedup = len(pts)
    pts = _dedup_by_position(pts)
    print(f"[3] Точек вставки из CodeQL: {n_before_dedup} "
          f"(после дедупликации шаблонных инстанциаций по позиции: {len(pts)})")

    # 4. Готовим вставки. Те же расширения, что в isProjectFile probe_points.ql/
    # functional_objects.ql (включая заголовки — там нередки инлайн-функции
    # с телом, напр. геттеры/сеттеры). Без .h/.hpp здесь такие точки молча
    # пропускались бы, а сами заголовки удалялись бы ниже как непроинструментированные.
    src_ext = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"}
    present = {p.name: p for p in out.rglob("*") if p.suffix in src_ext}

    # insertions[basename] = list of (op, line, col, text[, end_line, end_col])
    #   op "inline_candidate" — has_block=1 (entry/branch): { ожидается на
    #     (line, col), но может быть синтезирована макросом (HotSpot
    #     JNI_ENTRY/JVM_ENTRY*/PRODUCT_RETURN и т.п. — там { не литеральна в
    #     этой позиции файла). Разворачивается в конкретную операцию по факту
    #     текста файла (см. ниже, перед применением вставок).
    #   op "inline"  — вставить после '{' на позиции col (has_block=1)
    #   op "newline_after" — вставить текст отдельной строкой сразу после
    #     строки объявления (тело реально многострочно, { синтезирована
    #     макросом — JNI_ENTRY-стиль)
    #   op "open"    — вставить '{ text ' перед позицией col (has_block=0, открывающий)
    #   op "close"   — вставить ' }' после позиции col (has_block=0, закрывающий)
    insertions: dict = {}
    sensor_map = []
    # sid-ы датчиков, для которых на этапе разрешения inline_candidate (ниже,
    # по факту чтения файла) выяснилось, что надёжного места для вставки нет
    # (самодостаточный макрос, X-macro и т.п.) — sensor_map уже был заполнен
    # НА МОМЕНТ диспетчеризации (раньше, чем стало известно это), поэтому без
    # вычитания этих sid Карта_датчиков.csv лгала бы: для них есть
    # "вход"/"выход", хотя __TRACE_FN в реальный текст не попал (см.
    # add_via_macro в test-project-cpp-branches).
    dropped_sids = set()
    skipped = []
    sid = 1
    for pt in sorted(pts, key=lambda x: (x["file"], x["ins_line"], x["ins_col"])):
        if args.no_branches and pt["kind"] != "entry":
            continue
        base = os.path.basename(pt["file"].replace("\\", "/"))
        if base not in present:
            continue
        if pt["ins_col"] <= 0 or pt["ins_line"] <= 0:
            skipped.append((pt["func"], pt["kind"], "нет позиции тела"))
            continue
        fn = pt["func"]
        fo = _lookup_fo(fn, pt["file"], pt["ref_line"], fo_num, fo_notpl)
        if fo is None:
            skipped.append((fn, pt["kind"], "ФО нет в Перечень_ФО"))
            continue
        if pt["kind"] == "entry":
            se, sx = sid, sid + 1
            sid += 2
            text = f"__TRACE_FN({fo}, {se}, {sx});"
            sensor_map.append((se, fo, 0, base, pt["ins_line"], "вход"))
            sensor_map.append((sx, fo, -1, base, pt["ins_line"], "выход"))
            insertions.setdefault(base, []).append(("inline_candidate", pt["ins_line"], pt["ins_col"], text,
                                                     pt["end_line"], pt["end_col"], _short_name(fn)))
        else:  # branch
            bn = _lookup_br(fn, pt["ref_line"], pt["file"], br_num)
            if bn is None:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей"))
                continue
            s = sid; sid += 1
            text = f"__TRACE({s}, {fo}, {bn});"
            sensor_map.append((s, fo, bn, base, pt["ins_line"], pt["btype"]))
            if pt["has_block"] == 1:
                insertions.setdefault(base, []).append(("inline_candidate", pt["ins_line"], pt["ins_col"], text,
                                                         pt["end_line"], pt["end_col"], _short_name(fn)))
            elif pt["has_block"] == 2:
                # case/default: датчик ставится сразу после ':' метки, без
                # обёртки в скобки — см. подробный комментарий в
                # instrument_c_make.py и has_block=2 в probe_points.ql.
                insertions.setdefault(base, []).append(("direct", pt["ins_line"], pt["ins_col"], text))
            else:
                # Обернуть одиночный оператор в блок: { __TRACE(...); stmt; }
                el, ec = pt["end_line"], pt["end_col"]
                if el > 0 and ec > 0:
                    insertions.setdefault(base, []).append(("open",  pt["ins_line"], pt["ins_col"], text))
                    insertions.setdefault(base, []).append(("close", el, ec, ""))
                else:
                    skipped.append((fn, f"branch@{pt['ref_line']}", "has_block=0 без end_col"))

    total_sensors = sid - 1
    print(f"[4] Датчиков размещено: {total_sensors} (пропущено точек: {len(skipped)})")

    # 5. Применяем вставки (по убыванию строки/колонки — не сдвигаем координаты)
    def _strip_nl(s: str):
        if s.endswith("\r\n"): return s[:-2], "\r\n"
        if s.endswith("\n"):   return s[:-1], "\n"
        return s, ""

    # newline='' на чтении И записи — иначе Python в текстовом режиме сам
    # транслирует переводы строк (на Windows запись '\n' превращается в
    # '\r\n'), и весь файл переходит на CRLF, даже если только одна строка
    # была правда изменена.
    for base, ins in insertions.items():
        fp = present[base]
        with open(fp, encoding="utf-8", errors="ignore", newline='') as f:
            lines = f.readlines()
        _, dominant_nl = _strip_nl(lines[0]) if lines else (None, "\n")

        # Разворачиваем inline_candidate в конкретную операцию по факту
        # текста файла: { может быть синтезирована макросом (см. комментарий
        # у insertions выше) — тогда в этой позиции лежит что-то другое.
        resolved = []
        for entry in ins:
            if entry[0] != "inline_candidate":
                resolved.append(entry)
                continue
            _, ln_no, col, text, end_line, end_col, short_name = entry
            idx = ln_no - 1
            ln_real = _strip_nl(lines[idx])[0] if 0 <= idx < len(lines) else ""
            if 0 <= col - 1 < len(ln_real) and ln_real[col - 1] == '{':
                if "__TRACE_FN" in text:
                    resolved.append(("newline_after", ln_no, col, text))
                else:
                    resolved.append(("inline", ln_no, col, text))
            elif "{" in ln_real:
                # Fallback: { найдена на строке, но не на заявленной позиции
                brace_col = ln_real.index("{") + 1  # 1-based
                if "__TRACE_FN" in text:
                    resolved.append(("newline_after", ln_no, brace_col, text))
                else:
                    resolved.append(("inline", ln_no, brace_col, text))
            elif short_name not in ln_real:
                # Короткое имя ФО не встречается буквально в строке —
                # функция целиком собрана макросом (X-macro: macro(Name) ->
                # Name##Node::Method и т.п.) — надёжного места для датчика
                # нет, датчик не ставим (см. подробный комментарий в
                # _short_name и в instrument_c_make.py).
                dropped_sids.update(_sids_in_text(text))
            elif end_line > ln_no:
                # Вызов макроса (JVM_ENTRY/JNI_ENTRY и т.п.) может занимать
                # несколько строк (длинная сигнатура) — вставлять сразу
                # после ln_no небезопасно, можно попасть ВНУТРЬ списка
                # аргументов самого вызова. Находим строку, где скобки
                # вызова реально балансируются.
                call_end_idx = _find_macro_call_end_idx(lines, idx)
                resolved.append(("newline_after", call_end_idx + 1, 0, text))
            else:
                # end_line == ln_no, нет ни одной "{" на строке, но
                # short_name встречается (как аргумент макровызова) —
                # целиком самодостаточный макрос (открывает И закрывает блок
                # внутри СВОЕГО определения, см. JAVA_INTEGER_OP: `inline
                # TYPE NAME(...) { ... }` целиком в теле макроса). Обернуть
                # вызов в "{ датчик; ВЫЗОВ }" нельзя — макрос сам уже
                # произведёт пару {}, и получится вложенное определение
                # функции внутри { } (ошибка компиляции). Внутрь тела
                # (которое целиком в ТЕКСТЕ ОПРЕДЕЛЕНИЯ макроса, общем для
                # всех вызовов) поставить датчик тоже нельзя — нет
                # дискриминации по конкретному ФО. Надёжного места нет —
                # пропускаем (тот же случай, что и short_name not in ln_real
                # чуть выше).
                dropped_sids.update(_sids_in_text(text))

        # Те же open/close пары, но пришедшие из ОРИГИНАЛЬНОГО has_block=0
        # пути — там text файла ещё не было прочитан, границы не проверялись.
        # Пары всегда идут подряд (open, close) — валидируем обе половины
        # сразу, отбрасывая ВСЮ пару при несовпадении.
        final = []
        i = 0
        while i < len(resolved):
            entry = resolved[i]
            if (entry[0] == "open" and i + 1 < len(resolved)
                    and resolved[i + 1][0] == "close"):
                o_ln_no, o_col = entry[1], entry[2]
                c_ln_no, c_col = resolved[i + 1][1], resolved[i + 1][2]
                o_idx, c_idx = o_ln_no - 1, c_ln_no - 1
                o_ln = _strip_nl(lines[o_idx])[0] if 0 <= o_idx < len(lines) else None
                c_ln = _strip_nl(lines[c_idx])[0] if 0 <= c_idx < len(lines) else None
                if (o_ln is not None and c_ln is not None
                        and 0 <= o_col <= len(o_ln) and 0 <= c_col <= len(c_ln)):
                    final.append(entry)
                    final.append(resolved[i + 1])
                i += 2
            else:
                final.append(entry)
                i += 1
        ins = final

        # Третий ключ (0 для "close", 1 для остальных) — при равных
        # (строка, колонка) "close" должен применяться раньше "open" (см.
        # подробный комментарий в instrument_c_make.py: иначе при
        # однострочном теле из одного символа, напр. ';' после комментария,
        # "open" сдвигает строку, и устаревшая колонка "close" разрезает
        # уже вставленный текст пополам — `else` отрывается от своего `if`).
        #
        # Обработка newline_after ОТДЕЛЬНО (см. instrument_c_make.py):
        # группируем по ln_no, сдвиг накапливается внутри группы.
        # Третий ключ: при РАВНЫХ (строка, колонка) "close" применяется РАНЬШЕ
        # "open". Так бывает только когда тело ветви пустое/нулевой ширины
        # (напр. `if (x>0) ;` — open и close попадают на колонку одного и того
        # же ';'): если открыть первым, "}" по устаревшей колонке встанет сразу
        # после "{", дав `{ } датчик; ;` и оторвав `else` от `if`
        # (см. classify_empty). Пары с РАЗНЫМИ колонками уже корректно
        # упорядочены по -col (close правее => применяется первым), поэтому на
        # них этот тай-брейк не влияет (напр. однострочный `if ... ; else ...;`).
        all_ops = sorted(ins, key=lambda x: (-x[1], -x[2], 0 if x[0] == "close" else 1))

        for op, ln_no, col, text, *_ in all_ops:
            idx = ln_no - 1
            if idx < 0 or idx >= len(lines):
                continue
            ln, nl = _strip_nl(lines[idx])

            if op in ("newline_after", "inline"):
                # Вставляем датчик на НОВОЙ строке ПОСЛЕ { (если она есть на
                # этой строке), а не просто "после текущей строки целиком" —
                # критично для однострочных блоков вида `if (...) { stmt; }`
                # / `else { stmt; }`, где { и } на ОДНОЙ строке: наивная
                # вставка "после строки" ставит датчик уже ЗА закрывающей }
                # блока — между ним и `else`, что компилятор не принимает.
                # ВАЖНО: col уже указывает на проверенную позицию { (см. этап
                # разрешения inline_candidate выше) — использовать именно её,
                # а не искать "{" заново с начала строки: на строке может
                # встретиться более РАННИЙ "{" внутри символьного/строкового
                # литерала (например условие вида `_curchar != '{'`), и
                # наивный find() нашёл бы его первым, разрезав код пополам
                # внутри литерала (см. adlparse.cpp::get_oplist).
                brace_pos = (col - 1) if 0 < col <= len(ln) and ln[col - 1] == '{' else ln.find('{')
                if brace_pos >= 0:
                    indent = re.match(r'^(\s*)', ln).group(1)
                    rest_after_brace = ln[brace_pos + 1:]
                    lines[idx] = ln[:brace_pos + 1] + nl
                    lines.insert(idx + 1, indent + text + nl)
                    if rest_after_brace.strip():
                        lines.insert(idx + 2, indent + rest_after_brace + nl)
                else:
                    indent = re.match(r'^(\s*)', ln).group(1)
                    lines.insert(idx + 1, indent + text + nl)
            elif op == "open":
                c = col - 1
                if 0 <= c <= len(ln):
                    lines[idx] = ln[:c] + "{ " + text + " " + ln[c:] + nl
            elif op == "close":
                if 0 <= col <= len(ln):
                    lines[idx] = ln[:col] + " }" + ln[col:] + nl
            elif op == "direct":
                # case/default — вставить текст датчика сразу после ':'
                # метки, без скобок (см. has_block=2 в probe_points.ql).
                # col (1-based) указывает на символ ПОСЛЕ ':' — переводим в
                # 0-based ИНДЕКС этого символа (col - 1), как и везде при
                # переходе из координат CodeQL в срез Python (см. "open":
                # c = col - 1, чуть выше). Без этой поправки граница среза
                # захватывала бы в префикс ещё и сам этот символ — обычно
                # незаметно (пробел), но если после ':' нет пробела (см.
                # `case ...metadata_type:return ...;` в c1_LIR.hpp), датчик
                # разрезал бы пополам первое слово тела (`r`+датчик+`eturn`).
                # При ':' в КОНЦЕ строки (`case N:`) shifted_col == len(ln) —
                # валидная позиция «в конец», поэтому граница <= len(ln)
                # (иначе датчик молча не вставлялся бы — см. weekday_kind).
                shifted_col = col - 1
                if 0 <= shifted_col <= len(ln):
                    lines[idx] = ln[:shifted_col] + " " + text + ln[shifted_col:] + nl
        lines.insert(0, f'#include "__trace.h"{dominant_nl}')
        with open(fp, "w", encoding="utf-8", newline='') as f:
            f.write("".join(lines))

    # 6. Рантайм: ЕДИНЫЙ header-only __trace.h — всё тело датчиков (макросы,
    #    реализация __trace_hit И запись фактических маршрутов R/C) в ОДНОМ
    #    заголовке. Отдельный __trace_rt.cpp НЕ нужен: реализация и состояние
    #    помечены weak и сливаются линкером в один экземпляр на бинарник, даже
    #    если заголовок подключён в каждой единице трансляции. Поэтому
    #    достаточно '#include "__trace.h"' везде; заголовок можно один раз
    #    положить в /usr/include, и он будет виден отовсюду (см. шапку
    #    __trace_singlehdr.h). Заодно даёт маршруты R/C для route_match.
    #    Префикс языка в имени файла трасс (<lang>-<ts>-<pid>.log) — под --lang.
    _hdr = (RUNTIME / "__trace_singlehdr.h").read_text(encoding="utf-8")
    _hdr = f'#define CQ_LANG "{args.lang}"\n' + _hdr
    (out / "__trace.h").write_text(_hdr, encoding="utf-8")

    # 7. Карта датчиков. Вычитаем sid-ы, для которых разрешение
    # inline_candidate (см. dropped_sids выше) не нашло надёжного места —
    # без этого карта лгала бы про датчики, которых в реальном тексте нет
    # (см. add_via_macro).
    sensor_map = [sm for sm in sensor_map if sm[0] not in dropped_sids]
    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sid", "№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map):
            w.writerow(sm)

    # 8. Проверка синтаксиса: gcc/clang для .c, g++/clang++ для .cpp/.cc/.cxx.
    # Заголовки (.h/.hpp) НЕ компилируем напрямую — многие не самодостаточны
    # (рассчитывают на #include, уже сделанные до них в .cpp-файле, который их
    # подключает), и standalone-проверка дала бы ложные ошибки. Их синтаксис
    # неявно проверяется, когда проверяется .cpp/.c, который их включает.
    cc  = _find_compiler("gcc",  "clang",   "cc")
    cxx = _find_compiler("g++",  "clang++", "c++")
    print(f"[8] Проверка синтаксиса ({cc}/{cxx} -fsyntax-only)...")
    errors = []
    _compilable_ext = {".c", ".cpp", ".cc", ".cxx"}
    for fp in sorted(p for p in present.values() if p.suffix.lower() in _compilable_ext):
        rel = str(fp.relative_to(out))
        if fp.suffix.lower() == ".c":
            cmd = [cc,  "-std=c11",   "-fsyntax-only", "-I", str(out), rel]
        else:
            cmd = [cxx, "-std=c++14", "-fsyntax-only", "-I", str(out), rel]
        r = subprocess.run(cmd, cwd=out, capture_output=True, text=True)
        if r.returncode != 0:
            for ln in r.stderr.splitlines():
                if ": error:" in ln:
                    errors.append((rel, ln))
    if errors:
        with open(out / "Отчёт_об_ошибках_вставки.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["Файл", "Ошибка"])
            w.writerows(errors)
        print(f"[8] !!! Синтаксических ошибок: {len(errors)} — см. Отчёт_об_ошибках_вставки.csv")
        sys.exit(2)
    print(f"[8] Синтаксис OK. Карта датчиков: {out / 'Карта_датчиков.csv'}")

    # Pruning: оставляем только инструментированные единицы трансляции + рантайм.
    # ЗАГОЛОВКИ НЕ УДАЛЯЕМ: они подключаются (#include) инструментированными
    # .c/.cpp и нужны для компиляции, даже если сами не содержат точек вставки
    # (декларации, не самодостаточны). Удаление заголовка-декларации (напр.
    # if_demo.h без inline-тел) ломает сборку файла, который его включает.
    # Поэтому _prune_exts — только единицы трансляции, без .h/.hpp/.inl.
    _touched = {present[b] for b in insertions}
    # __trace.h — единый header-only рантайм; отдельного __trace_rt.cpp больше
    # нет, поэтому НЕ исключаем его из pruning: устаревший __trace_rt.cpp от
    # прежних прогонов должен удаляться (его strong-символ __trace_hit иначе
    # перекрыл бы weak-реализацию из заголовка и маршруты R/C не записались бы).
    _runtime = {out / "__trace.h"}
    _prune_exts = {".c", ".cpp", ".cc", ".cxx"}
    _pruned = 0
    for _p in list(out.rglob("*")):
        if _p.is_file() and _p.suffix.lower() in _prune_exts \
                and _p not in _touched and _p not in _runtime:
            _p.unlink()
            _pruned += 1
    for _d in sorted([_d for _d in out.rglob("*") if _d.is_dir()],
                     key=lambda x: len(x.parts), reverse=True):
        try:
            _d.rmdir()
        except OSError:
            pass
    if _pruned:
        print(f"[9] Удалено неинструментированных файлов: {_pruned}")
    print(f"[OK] Инструментировано. Датчиков: {total_sensors - len(dropped_sids)}")


if __name__ == "__main__":
    main()
