#!/usr/bin/env python3
"""
Инструментатор датчиков для C/C++ проектов СО СВОЕЙ СБОРКОЙ (make и т.п.), напр. nginx, gosjava.

Отличия от instrument_cpp.py (плоские мелкие проекты):
  - сопоставление точек вставки с файлами по ОТНОСИТЕЛЬНОМУ пути (вложенные каталоги,
    дубли имён вроде os/unix vs os/win32);
  - тело датчика ПОЛНОСТЬЮ в заголовке __trace.h (weak-символы — см. сам файл);
    каждый инструментированный файл просто #include "__trace.h", без выбора
    "одного impl-файла на бинарник" и без разбора CMakeLists.txt/add_library.

Заголовок __trace.h НЕ копируется в include-пути проекта — он один раз пишется
в <out>/__trace.h. Пользователь сам копирует его в системный include-путь
(обычно /usr/include) и поправляет сборочные скрипты/команды компиляции, если
тулчейн собран нестандартно (--sysroot, -nostdinc и т.п. отключают поиск
/usr/include даже для #include "...").

Вход/выход ФО — через cleanup-атрибут (__TRACE_FN после `{` тела). Ветвь — __TRACE после `{`.

Дерево исходников отдельно передавать не нужно — оно извлекается прямо из
src.zip внутри CodeQL БД (точный снэпшот того, что реально анализировал
CodeQL, включая файлы, появляющиеся только во время сборки — ADLC/JVMTI/JFR
и т.п., которых нет на диске до сборки). См. core/file_lists.py.

Использование:
  python3 instrument_c_make.py --db <db> --reports <static> --out <instr-tree>
      [--codeql codeql] [--lang cpp] [--pattern '%/hotspot/%']
      [--include-list files.txt] [--exclude-list files.txt]
"""
import argparse, tempfile, csv, os, re, shutil, subprocess, sys
from pathlib import Path
from collections import defaultdict

HERE = Path(__file__).resolve().parent
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
    """qualified_name -> [(fo_num, file, line), ...] — СПИСОК, а не один
    номер: разные функции (в разных файлах — static-тёзки, перегрузки)
    могут иметь одинаковый qualified_name. Раньше последняя запись просто
    затирала предыдущие при одинаковом имени — это давало НЕВЕРНЫЙ номер
    ФО для датчика, если probe_points.ql сослался на ОДНОИМЁННУЮ, но
    физически другую функцию. См. _lookup_fo — дисамбигуация по файлу."""
    fo = {}
    with open(reports_dir / "Перечень_ФО(процедур_функций).csv", encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                name = row[1].strip()
                file, line = _parse_declared_at(row[2]) if len(row) > 2 else (None, None)
                fo.setdefault(name, []).append((int(row[0]), file, line))
    return fo


def read_branch_numbers(reports_dir: Path):
    """(qualified_name, line) -> [(branch_num, file), ...] — см. read_fo_numbers:
    тот же класс коллизий возможен, если у двух одноимённых функций в
    разных файлах ветвь оказалась на одной и той же строке."""
    br = {}
    with open(reports_dir / "Перечень_ветвей.csv", encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                key = (row[2].strip(), int(row[6]))
                file = row[5].strip() if len(row) > 5 and row[5].strip() else None
                br.setdefault(key, []).append((int(row[3]), file))
    return br


def run_probe_query(codeql, db, query, path_pattern: str = "%"):
    content = query.read_text(encoding="utf-8")
    if "${PROJECT_PATTERN}" in content:
        tmp = query.parent / f".{query.name}"
        tmp.write_text(content.replace("${PROJECT_PATTERN}", path_pattern or "%"), encoding="utf-8")
        query_to_run = tmp
    else:
        query_to_run = query
    bqrs = Path(tempfile.gettempdir(), "probe_cmake.bqrs")
    csvp = Path(tempfile.gettempdir(), "probe_cmake.csv")
    subprocess.run([codeql, "query", "run", f"--database={db}", f"--output={bqrs}", str(query_to_run)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(csvp, "w") as out:
        subprocess.run([codeql, "bqrs", "decode", "--format=csv", str(bqrs)],
                       check=True, stdout=out, stderr=subprocess.DEVNULL)
    pts = []
    with open(csvp, encoding="utf-8") as fh:
        r = csv.reader(fh); next(r, None)
        for row in r:
            if len(row) < 8: continue
            pts.append({
                "kind":     row[0], "func": row[1], "file": row[2].replace("\\", "/"),
                "ref_line": int(row[3]), "ins_line": int(row[4]),
                "ins_col":  int(row[5]), "has_block": int(row[6]), "btype": row[7],
                "end_line": int(row[8]) if len(row) > 8 else 0,
                "end_col":  int(row[9]) if len(row) > 9 else 0,
            })
    return pts


def _strip_tpl(name: str) -> str:
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
    функций) — сперва пробуем файл+строку точно (различает ПЕРЕГРУЗКИ в
    ОДНОМ файле, напр. 'emit_opcode' на разных строках ad_x86_64.cpp — файла
    одного недостаточно), затем только файл (различает static-тёзки в
    разных файлах). Если совпадения не нашлось вовсе (напр. функция, чьё
    тело физически в другом файле, чем 'Объявлен в' — см. фикс
    file-attribution в probe_points.ql) — берётся первый кандидат, как было
    раньше (не хуже старого поведения)."""
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


def _lookup_fo(fn: str, file: str, line, fo_num: dict, fo_notpl: dict):
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


def _lookup_br(fn: str, ref_line: int, file: str, br_num: dict):
    for d in (0, 1, -1, 2, -2):
        cands = br_num.get((fn, ref_line + d))
        if cands:
            return _pick_by_file(cands, file)
    return None


def _strip_nl(s: str):
    if s.endswith("\r\n"): return s[:-2], "\r\n"
    if s.endswith("\n"):   return s[:-1], "\n"
    return s, ""


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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _pattern_filter_factory(pattern: str):
    """--pattern — тот же SQL LIKE-шаблон ('%' = подстрока любой длины),
    что подставляется в isProjectFile(...) внутри .ql-запросов (там он
    матчится против getAbsolutePath(), т.е. пути С ведущим '/'). Здесь
    получаем имена БЕЗ ведущего слеша (внутренние имена ZIP) — добавляем
    его перед сравнением для согласованности с тем же шаблоном."""
    if not pattern or pattern == "%":
        return None
    import fnmatch
    glob_pat = pattern.replace("%", "*")
    def check(zip_path: str) -> bool:
        return fnmatch.fnmatch("/" + zip_path.lstrip("/"), glob_pat)
    return check


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="cpp")
    ap.add_argument("--pattern", default="", help="Паттерн пути проекта для isProjectFile")
    ap.add_argument("--include-list", default="", help="Текстовый файл — белый список путей (по одному на строку)")
    ap.add_argument("--exclude-list", default="", help="Текстовый файл — чёрный список путей (по одному на строку)")
    ap.add_argument("--no-branches", action="store_true",
                    help="инструментировать только вход/выход ФО, без датчиков ветвей")
    args = ap.parse_args()

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

    if out.exists(): shutil.rmtree(out)
    print(f"[1] Извлекаю дерево исходников из src.zip БД -> {out} ...")
    # Содержимое --include-list/--exclude-list передаём ОДНОВРЕМЕННО и как
    # glob-шаблоны, и как точные/относительные пути (см. path_matches_patterns/
    # path_matches_list в core/file_lists.py) — та же двойная семантика, что
    # и в apply_file_filters для статики (core/project_runner.py): строки
    # без '*'/'?' надёжнее матчатся как путь (совпадение по хвосту), а
    # строки-шаблоны срабатывают через glob. --pattern (isProjectFile) — это
    # ОТДЕЛЬНЫЙ обязательный базовый фильтр принадлежности проекту.
    extract_res = extract_project_sources(
        db_path, out,
        pattern_filter=_pattern_filter_factory(args.pattern),
        include_patterns=include_list, exclude_patterns=exclude_list,
        include_list=include_list, exclude_list=exclude_list, log=print)
    db_prefix = extract_res["prefix"]
    if extract_res["generated_skipped"]:
        print(f"    Внимание: {extract_res['generated_skipped']} сгенерированных во время "
              f"сборки файлов (ADLC/JVMTI/JFR и т.п.) потенциально доступны в БД, но "
              f"отсеяны текущим фильтром (--pattern/--include-list/--exclude-list).")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    fo_notpl = {}
    for k, v in fo_num.items():
        fo_notpl.setdefault(_strip_tpl(k), []).extend(v)
    fo_total = sum(len(v) for v in fo_num.values())
    br_total = sum(len(v) for v in br_num.values())
    print(f"[2] ФО: {fo_total} (уникальных имён: {len(fo_num)}), "
          f"ветвей: {br_total} (уникальных пар имя/строка: {len(br_num)})")

    pts = run_probe_query(args.codeql, db_path,
                          HERE.parent / "queries" / args.lang / "probe_points.ql",
                          path_pattern=args.pattern or "%")
    n_before_dedup = len(pts)
    pts = _dedup_by_position(pts)
    print(f"[3] Точек вставки из CodeQL: {n_before_dedup} "
          f"(после дедупликации шаблонных инстанциаций по позиции: {len(pts)})")

    # Точное сопоставление: extract_project_sources извлёк дерево из ТЕХ ЖЕ
    # абсолютных путей (db_prefix — общий префикс build-машины, срезанный
    # при извлечении), поэтому файл probe_points.ql детерминированно лежит
    # по rel = pt["file"] минус db_prefix — без нечёткого сопоставления по
    # basename (раньше могло путать одноимённые файлы в разных каталогах).
    def match_file(probe_path):
        norm = probe_path.lstrip("/")
        rel = norm[len(db_prefix):] if db_prefix and norm.startswith(db_prefix) else norm
        p = out / rel
        return p if p.is_file() else None

    # insertions[fp] = list of (op, line, col, text[, end_line, end_col])
    #   "inline_candidate" — has_block=1 (entry или branch): разрешается
    #     во 2-м проходе по факту чтения файла:
    #       символ ровно '{'              → "newline_after" (датчик на новой
    #                                        строке после {)
    #       не '{', end_line > line       → "newline_after" (многострочный
    #                                        макрос — JNI_ENTRY-стиль)
    #       не '{', end_line == line      → "open"/"close" (однострочный
    #                                        макрос — PRODUCT_RETURN-стиль)
    #   "open"    — вставить '{ text ' перед col (has_block=0, открывающий)
    #   "close"   — вставить ' }' после col (has_block=0, закрывающий)
    insertions = defaultdict(list)
    sensor_map = []
    # sid-ы датчиков, для которых на этапе разрешения inline_candidate
    # (ниже, по факту чтения файла) выяснилось, что надёжного места для
    # вставки нет (самодостаточный макрос, X-macro и т.п.) — sensor_map уже
    # был заполнен НА МОМЕНТ диспетчеризации (раньше, чем стало известно
    # это), поэтому без вычитания этих sid Карта_датчиков.csv лгала бы: для
    # них есть "вход"/"выход", хотя __TRACE_FN в реальный текст не попал —
    # ниже по покрытию такой ФО ошибочно числился бы "не покрыт" вместо
    # корректного "нет датчика" (см. add_via_macro в test-project-cpp-branches).
    dropped_sids = set()
    skipped = 0
    sid = 1
    touched = set()
    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue
        fp = match_file(pt["file"])
        if fp is None or pt["ins_col"] <= 0 or pt["ins_line"] <= 0:
            skipped += 1; continue
        fn = pt["func"]
        fo = _lookup_fo(fn, pt["file"], pt["ref_line"], fo_num, fo_notpl)
        if fo is None:
            skipped += 1; continue
        rel = fp.relative_to(out).as_posix()
        if pt["kind"] == "entry":
            se, sx = sid, sid + 1; sid += 2
            text = f"__TRACE_FN({fo}, {se}, {sx});"
            sensor_map.append((se, fo, 0,  rel, pt["ins_line"], "вход"))
            sensor_map.append((sx, fo, -1, rel, pt["ins_line"], "выход"))
            insertions[fp].append(("inline_candidate", pt["ins_line"], pt["ins_col"], text,
                                   pt["end_line"], pt["end_col"], _short_name(fn)))
            touched.add(fp)
        else:
            bn = _lookup_br(fn, pt["ref_line"], pt["file"], br_num)
            if bn is None:
                skipped += 1; continue
            s = sid; sid += 1
            text = f"__TRACE({s}, {fo}, {bn});"
            sensor_map.append((s, fo, bn, rel, pt["ins_line"], pt["btype"]))
            if pt["has_block"] == 1:
                insertions[fp].append(("inline_candidate", pt["ins_line"], pt["ins_col"], text,
                                       pt["end_line"], pt["end_col"], _short_name(fn)))
            elif pt["has_block"] == 2:
                # case/default: датчик ставится сразу после ':' метки, без
                # какой-либо обёртки в скобки — метки внутри switch делят
                # ОДИН общий блок тела, поэтому ни поиск '{' (has_block=1),
                # ни обёртка "{ датчик; оператор; }" (has_block=0) здесь не
                # нужны и не подходят (см. probe_points.ql).
                insertions[fp].append(("direct", pt["ins_line"], pt["ins_col"], text))
            else:
                el, ec = pt["end_line"], pt["end_col"]
                if el > 0 and ec > 0:
                    insertions[fp].append(("open",  pt["ins_line"], pt["ins_col"], text))
                    insertions[fp].append(("close", el, ec, ""))
                else:
                    skipped += 1; continue
            touched.add(fp)

    total = sid - 1
    print(f"[4] Датчиков размещено: {total} в {len(touched)} файлах (пропущено точек: {skipped})")

    # Рантайм-заголовок: одна копия в out/__trace.h. Реализация уже целиком в
    # заголовке (weak-символы) — пользователь сам копирует файл в системный
    # include-путь (/usr/include), --header-dir/--impl-file не нужны.
    rt = (RUNTIME / "__trace_singlehdr.h").read_text(encoding="utf-8")
    rt = rt.replace('#define CQ_LANG "cpp"', f'#define CQ_LANG "{args.lang}"')
    (out / "__trace.h").write_text(rt, encoding="utf-8")

    # Применяем вставки + подключаем рантайм.
    # newline='' на чтении И записи — иначе Python в текстовом режиме сам
    # транслирует переводы строк (на Windows запись '\n' превращается в
    # '\r\n'), и весь файл переходит на CRLF, даже если только одна строка
    # была правда изменена. Это ломает применение debian/patching патчей
    # (unified diff с LF) к уже инструментированному файлу — "different
    # line endings" в quilt/patch.
    for fp in touched:
        with open(fp, encoding="utf-8", errors="ignore", newline='') as f:
            lines = f.readlines()
        _, dominant_nl = _strip_nl(lines[0]) if lines else (None, "\n")

        resolved = []
        for entry in insertions[fp]:
            if entry[0] != "inline_candidate":
                resolved.append(entry)
                continue
            _, ln_no, col, text, end_line, end_col, short_name = entry
            idx = ln_no - 1
            ln_real = _strip_nl(lines[idx])[0] if 0 <= idx < len(lines) else ""
            if 0 <= col - 1 < len(ln_real) and ln_real[col - 1] == '{':
                # Точное совпадение: { на заявленной позиции
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
                dropped_sids.update(_sids_in_text(text))
            elif end_line > ln_no:
                call_end_idx = _find_macro_call_end_idx(lines, idx)
                resolved.append(("newline_after", call_end_idx + 1, 0, text))
            else:
                # end_line == ln_no, нет "{" на строке, но short_name
                # встречается (как аргумент макровызова) — целиком
                # самодостаточный макрос (открывает И закрывает блок внутри
                # СВОЕГО определения, см. JAVA_INTEGER_OP в
                # globalDefinitions.hpp: `inline TYPE NAME(...) { ... }`
                # целиком в теле макроса). Обернуть вызов в "{ датчик;
                # ВЫЗОВ }" нельзя — макрос сам произведёт пару {}, получится
                # вложенное определение функции внутри { } (ошибка
                # компиляции). Внутрь тела (общего для всех вызовов макроса)
                # датчик тоже не поставить — нет дискриминации по
                # конкретному ФО. Надёжного места нет — пропускаем (см.
                # instrument_cpp.py).
                dropped_sids.update(_sids_in_text(text))

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
                # Последний символ тела (по координате CodeQL, c_col-1 0-based)
                # должен быть ';' — этим заканчивается ЛЮБОЙ корректный
                # одиночный оператор (ExprStmt/ReturnStmt/ThrowStmt/пустой ';'
                # и т.п.). Если это не так — HotSpot-идиома CHECK/CHECK_/
                # RETURN/TRAPS: макрос-аргумент САМ закрывает скобки вызова
                # (`f(..., CHECK)` -> `f(..., THREAD); if (...) return; ...)`),
                # и CodeQL репортует конец оператора там, где кончается
                # макроподстановка (сразу после "CHECK"), а НЕ после настоящего
                # ');' вызова. Вставка "}" по такой координате попадёт ВНУТРЬ
                # списка аргументов вызова (см. classfile_parse_error(...,
                # CHECK) в classFileParser.cpp) — пары нет надёжного места,
                # пропускаем обе половины (как макро-кейсы выше).
                c_last_ok = (c_ln is not None and 0 < c_col <= len(c_ln)
                             and c_ln[c_col - 1] == ';')
                if (o_ln is not None and c_ln is not None
                        and 0 <= o_col <= len(o_ln) and 0 <= c_col <= len(c_ln)
                        and c_last_ok):
                    final.append(entry)
                    final.append(resolved[i + 1])
                elif o_ln is not None and c_ln is not None:
                    dropped_sids.update(_sids_in_text(entry[3]))
                i += 2
            else:
                final.append(entry)
                i += 1

        all_ops = sorted(final,
                         key=lambda x: (-x[1], -x[2], 0 if x[0] in ("inline", "open") else 1))

        col_shifts = {}
        last_col = {}
        for op, ln_no, col, text, *_ in all_ops:
            idx = ln_no - 1
            if idx < 0 or idx >= len(lines):
                continue
            # Сдвиг переносится ТОЛЬКО между операциями на ОДНОЙ И ТОЙ ЖЕ
            # колонке той же строки (истинная коллизия open/close при пустом
            # теле, напр. `if (x>0) ;` — см. close ниже). Операции
            # обрабатываются по убыванию колонки, поэтому операция со СТРОГО
            # МЕНЬШЕЙ колонкой лежит ЛЕВЕЕ уже вставленного текста и
            # накопленным сдвигом вообще не затрагивается (вставка не
            # сдвигает то, что было ДО неё). Перенос чужого сдвига на неё
            # портит несвязанный участок строки — например, "close" внешнего
            # if получал сдвиг от "open" вложенного else (другая, более
            # правая колонка) и резал уже вставленный __TRACE() этого else
            # пополам (см. if_else_oneline_nn в test-project-cpp-branches).
            if last_col.get(ln_no) != col:
                col_shifts[ln_no] = 0
            last_col[ln_no] = col
            ln, nl = _strip_nl(lines[idx])

            if op == "newline_after":
                # Вставляем датчик на НОВОЙ строке ПОСЛЕ {, а не в конец строки.
                # Если { на этой строке — вставляем после {; иначе — в конец.
                # ВАЖНО: col уже указывает на проверенную позицию { (см. этап
                # разрешения inline_candidate выше) — использовать именно её,
                # а не искать "{" заново с начала строки: на строке может
                # встретиться более РАННИЙ "{" внутри символьного/строкового
                # литерала (например условие вида `_curchar != '{'`), и
                # наивный find() нашёл бы его первым, разрезав код пополам
                # внутри литерала (см. adlparse.cpp::get_oplist).
                brace_pos = (col - 1) if 0 < col <= len(ln) and ln[col - 1] == '{' else ln.find('{')
                if brace_pos >= 0:
                    # { найдена: вставляем после неё на новой строке
                    indent = re.match(r'^(\s*)', ln).group(1)
                    rest_after_brace = ln[brace_pos + 1:]
                    lines[idx] = ln[:brace_pos + 1] + nl
                    lines.insert(idx + 1, indent + text + nl)
                    if rest_after_brace.strip():
                        lines.insert(idx + 2, indent + rest_after_brace + nl)
                else:
                    # { не на этой строке — вставляем в конец (старое поведение)
                    indent = re.match(r'^(\s*)', ln).group(1)
                    lines.insert(idx + 1, indent + text + nl)
            elif op == "inline":
                # Вставляем датчик на новой строке ПОСЛЕ {, как и "newline_after"
                # (см. тот же приём чуть выше) — а не просто после ТЕКУЩЕЙ
                # строки целиком. Критично для однострочных блоков вида
                # `if (...) { stmt; }` / `else { stmt; }`, где { и }
                # находятся на ОДНОЙ строке: наивная вставка "после строки"
                # ставит датчик уже ЗА закрывающей } блока — между ним и
                # `else`, что компилятор не принимает (else должен идти
                # сразу за телом if, без посторонних операторов между ними).
                # Та же причина, что и в "newline_after" чуть выше: брать
                # уже проверенную col, а не искать "{" заново (литералы).
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
                    col_shifts[ln_no] = col_shifts.get(ln_no, 0) + len("{ " + text + " ")
            elif op == "close":
                # Учитываем сдвиг от inline/open на той же строке
                shifted_col = col + col_shifts.get(ln_no, 0)
                if 0 <= shifted_col <= len(ln):
                    lines[idx] = ln[:shifted_col] + " }" + ln[shifted_col:] + nl
            elif op == "direct":
                # case/default — просто вставить текст датчика сразу после
                # ':' метки, без скобок (см. has_block=2 в probe_points.ql).
                # col (1-based) указывает на символ ПОСЛЕ ':' — переводим в
                # 0-based ИНДЕКС этого символа (col - 1), как и везде при
                # переходе из координат CodeQL в срез Python (см. "open"/
                # "close" чуть выше: c = col - 1). Без этой поправки граница
                # среза захватывала бы в префикс ещё и сам этот символ —
                # обычно это незаметно (это пробел, его наличие в префиксе
                # или суффиксе визуально не отличить), но если после ':' нет
                # пробела (см. `case ...metadata_type:return ...;` в
                # c1_LIR.hpp — без пробела перед return), датчик разрезал бы
                # пополам первое слово тела (`r` + датчик + `eturn`).
                # При ':' в КОНЦЕ строки (обычное `case N:`) shifted_col ==
                # len(ln) — валидная позиция «в конец», поэтому граница
                # <= len(ln), иначе датчик молча терялся бы (см. weekday_kind
                # в test-project-cpp-branches).
                shifted_col = (col - 1) + col_shifts.get(ln_no, 0)
                if 0 <= shifted_col <= len(ln):
                    lines[idx] = ln[:shifted_col] + " " + text + ln[shifted_col:] + nl
                    col_shifts[ln_no] = col_shifts.get(ln_no, 0) + len(" " + text)

        lines.insert(0, f'#include "__trace.h"{dominant_nl}')
        with open(fp, "w", encoding="utf-8", newline='') as f:
            f.write("".join(lines))

    print(f"[5] Рантайм записан: {out / '__trace.h'}")
    print(f"    Скопируйте его в системный include-путь (например /usr/include) "
          f"— тогда #include \"__trace.h\" найдётся из любого файла независимо "
          f"от -I путей сборки, и поправьте сборочные скрипты при необходимости.")

    # Вычитаем sid-ы, для которых разрешение inline_candidate (см. dropped_sids
    # выше) не нашло надёжного места — без этого Карта_датчиков.csv лгала бы
    # про датчики, которых в реальном тексте нет (см. add_via_macro).
    sensor_map = [sm for sm in sensor_map if sm[0] not in dropped_sids]
    total -= len(dropped_sids)
    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sid", "№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)
    print(f"[OK] Инструментировано. Датчиков: {total}. Соберите проект (make/cmake) в {out}")


if __name__ == "__main__":
    main()
