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
            if len(row) < 9: continue
            pts.append({"kind": row[0], "func": row[1], "file": row[2],
                        "ref_line": int(row[3]), "open_line": int(row[4]), "open_col": int(row[5]),
                        "close_line": int(row[6]), "close_col": int(row[7]), "btype": row[8]})
    return pts


def read_probe_points_from_db(project_db_path: str):
    """Читает геометрию точек вставки из СЫРЫХ ДАННЫХ project.db (раздел
    'probe', собранный на этапе статики через probe_points.ql) — без
    отдельного запроса к CodeQL-БД (см. instrument_cpp.py). Колонки
    queries/java/probe_points.ql называются camelCase (refLine/openLine/
    openCol/closeLine/closeCol) — отличие от C++-варианта, маппинг локальный."""
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
            "ref_line": _i(r.get("refLine")), "open_line": _i(r.get("openLine")),
            "open_col": _i(r.get("openCol")), "close_line": _i(r.get("closeLine")),
            "close_col": _i(r.get("closeCol")), "btype": r.get("btype", ""),
        })
    return pts


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
    extract_res = extract_project_sources(
        db_path, out,
        pattern_filter=_pattern_filter_factory(args.pattern),
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
    print(f"[3] Точек вставки: {len(pts)}")

    all_java = list(out.rglob("*.java"))
    pkg = args.cqtrace_package or detect_package(all_java)
    ref = (pkg + ".Cqtrace") if pkg else "Cqtrace"
    print(f"[3] Пакет Cqtrace: {pkg or '(default)'} → ссылка {ref}.hit(...)")

    # Индекс по basename → [(relpath, Path)] для сопоставления по относительному пути.
    from collections import defaultdict
    by_base = defaultdict(list)
    for p in all_java:
        by_base[p.name].append((p.relative_to(out).as_posix(), p))

    def match_file(probe_path):
        pp = probe_path.replace("\\", "/")
        cands = by_base.get(pp.rsplit("/", 1)[-1], [])
        if len(cands) == 1:
            return cands[0][1]
        best = None
        for rel, p in cands:
            if pp.endswith("/" + rel) and (best is None or len(rel) > len(best[0])):
                best = (rel, p)
        return best[1] if best else None

    ins = {}; sensor_map = []; skipped = []; touched = set()
    dropped_sids = set()

    # prio: при совпадении (строка, позиция) — вставка «перед }» (prio=1) идёт
    # раньше «после {» (prio=0). Нужно для пустых тел `{}`, где обе позиции совпадают.
    def add_ins(fpath, line, eff_index, prio, text, sid):
        ins.setdefault(fpath, []).append((line, eff_index, prio, text, sid)); touched.add(fpath)

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
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, 0); try {{", se)
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
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, {bn});", s)
            sensor_map.append((s, fo, bn, base, pt["open_line"], pt["btype"]))

    print(f"[4] Датчиков (потенциально): {sid - 1} (пропущено точек: {len(skipped)})")

    for fp in touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        for line, eff, prio, text, sid_ in sorted(ins[fp], key=lambda x: (x[0], x[1], x[2]), reverse=True):
            idx = line - 1
            if idx < 0 or idx >= len(lines):
                dropped_sids.add(sid_); continue
            ln = lines[idx]; nl = ""
            if ln.endswith("\r\n"): ln, nl = ln[:-2], "\r\n"
            elif ln.endswith("\n"): ln, nl = ln[:-1], "\n"
            if eff < 0 or eff > len(ln):
                dropped_sids.add(sid_); continue
            lines[idx] = ln[:eff] + text + ln[eff:] + nl
        fp.write_text("".join(lines), encoding="utf-8")

    if dropped_sids:
        sensor_map = [sm for sm in sensor_map if sm[0] not in dropped_sids]
        print(f"[4] Датчиков не вставлено (вне границ файла): {len(dropped_sids)}")

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
    print(f"[5] Рантайм: {(cq_dir / 'Cqtrace.java').relative_to(out)}")

    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sid", "№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)

    # Проверка синтаксиса — javac всех плоских .java (только для мелких проектов).
    # Для проектов со своей сборкой (Maven/Gradle) её роль выполняет последующая сборка.
    if args.no_syntax_check:
        print("[8] Проверка синтаксиса пропущена (--no-syntax-check; проверит сборка).")
    else:
        print("[8] Проверка синтаксиса (javac)...")
        chk = out / ".syntax_check"; chk.mkdir(exist_ok=True)
        java_files = [str(p.relative_to(out)) for p in sorted(touched | {cq_dir / "Cqtrace.java"})]
        r = subprocess.run(["javac", "-d", str(chk), *java_files], cwd=out,
                           capture_output=True, text=True)
        shutil.rmtree(chk, ignore_errors=True)
        errors = [(ln.split(":")[0], ln) for ln in r.stderr.splitlines() if ": error:" in ln]
        if errors:
            with open(out / "Отчёт_об_ошибках_вставки.csv", "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, delimiter=";"); w.writerow(["Файл", "Ошибка"]); w.writerows(errors)
            print(f"[8] !!! Ошибок: {len(errors)} — см. Отчёт_об_ошибках_вставки.csv")
            sys.exit(2)
        print("[8] Синтаксис OK.")

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
        print(f"[9] Удалено неинструментированных файлов: {_pruned}")
    print(f"[OK] Инструментировано. Датчиков: {len(sensor_map)}")


if __name__ == "__main__":
    main()
