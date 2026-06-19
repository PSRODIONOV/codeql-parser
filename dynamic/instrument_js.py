#!/usr/bin/env python3
"""
Инструментатор датчиков динамического анализа для JavaScript (Node, CommonJS).

Вставляет:
  - вход/выход ФО: тело функции оборачивается
        { cqtrace.hit(fo,0); try { <тело> } finally { cqtrace.hit(fo,-1); } }
  - ветвь: cqtrace.hit(fo,#N) первым оператором блока ветви (if/for/while/try).

Номера ФО и ветвей берутся из статических отчётов → совпадают со статикой 1:1.
Проверка синтаксиса — `node --check` по каждому файлу.

Использование:
  python3 instrument_js.py --project <dir> --db <codeql-db> --reports <static-dir>
      --out <work-dir> [--codeql codeql] [--lang javascript]
"""
import argparse, tempfile, csv, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"


def read_fo_numbers(reports_dir: Path):
    fo = {}
    with open(reports_dir / "Перечень_ФО(процедур_функций).csv", encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                fo[row[1].strip()] = int(row[0])
    return fo


def read_branch_numbers(reports_dir: Path):
    br = {}
    with open(reports_dir / "Перечень_ветвей.csv", encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                br[(row[2].strip(), int(row[6]))] = int(row[3])
    return br


def run_probe_query(codeql, db, query, path_pattern="%"):
    content = query.read_text(encoding="utf-8")
    if "${PROJECT_PATTERN}" in content:
        query_to_run = query.parent / f".{query.name}"
        query_to_run.write_text(content.replace("${PROJECT_PATTERN}", path_pattern or "%"), encoding="utf-8")
    else:
        query_to_run = query
    bqrs = Path(tempfile.gettempdir(), "probe_js.bqrs"); csvp = Path(tempfile.gettempdir(), "probe_js.csv")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="javascript")
    ap.add_argument("--pattern", default="", help="Паттерн пути проекта для isProjectFile")
    ap.add_argument("--no-branches", action="store_true",
                    help="инструментировать только вход/выход ФО, без датчиков ветвей")
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

    project = Path(args.project).resolve()
    out = Path(args.out).resolve()
    reports = Path(args.reports).resolve()

    from src_copy import copy_src_files
    n = copy_src_files(project, out, "javascript")
    print(f"[1] Скопировано JS/TS-файлов: {n} → {out}")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    pts = run_probe_query(args.codeql, Path(args.db).resolve(),
                          HERE.parent / "queries" / args.lang / "probe_points.ql",
                          path_pattern=args.pattern or "%")
    print(f"[3] Точек вставки: {len(pts)}")

    # Индекс по basename → [(relpath, Path)] для сопоставления по относительному
    # пути (вложенные каталоги + дубли basename, напр. index.js в корне и lib/router/).
    from collections import defaultdict
    by_base = defaultdict(list)
    for p in out.rglob("*.js"):
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

    # ins[Path] = list of (line, eff_index, prio, text)
    ins = {}
    sensor_map = []
    skipped = []
    touched = set()

    # prio: при совпадении (строка, позиция) — вставка «перед }» (prio=1) идёт
    # раньше «после {» (prio=0). Нужно для пустых тел `{}`, где обе позиции совпадают.
    def add_ins(fpath, line, eff_index, prio, text):
        ins.setdefault(fpath, []).append((line, eff_index, prio, text))
        touched.add(fpath)

    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue  # отключена инструментация ветвей
        fpath = match_file(pt["file"])
        if fpath is None:
            continue
        base = fpath.relative_to(out).as_posix()
        fn = pt["func"]
        if fn not in fo_num:
            skipped.append((fn, pt["kind"], "ФО нет в Перечень_ФО")); continue
        fo = fo_num[fn]
        if pt["kind"] == "entry":
            if pt["open_col"] <= 0 or pt["close_col"] <= 0:
                skipped.append((fn, "entry", "нет позиции тела")); continue
            # после '{' (open_col): hit(fo,0); try {     [eff_index = open_col]
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" cqtrace.hit({fo}, 0); try {{")
            # перед '}' (close_col): } finally { hit(fo,-1); }   [eff_index = close_col-1]
            add_ins(fpath, pt["close_line"], pt["close_col"] - 1, 1,
                    f"}} finally {{ cqtrace.hit({fo}, -1); }} ")
            sensor_map.append((fo, 0, base, pt["open_line"], "вход/выход"))
        else:
            key = (fn, pt["ref_line"])
            if key not in br_num:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей")); continue
            if pt["open_col"] <= 0:
                skipped.append((fn, "branch", "нет позиции блока")); continue
            bn = br_num[key]
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" cqtrace.hit({fo}, {bn});")
            sensor_map.append((fo, bn, base, pt["open_line"], pt["btype"]))

    print(f"[4] Датчиков: {len(sensor_map)} (пропущено точек: {len(skipped)})")

    use_strict = re.compile(r"""^\s*['"]use strict['"];?\s*$""")
    for fp in touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        # применяем вставки по убыванию (line, eff_index, prio)
        for line, eff, prio, text in sorted(ins[fp], key=lambda x: (x[0], x[1], x[2]), reverse=True):
            idx = line - 1
            if idx < 0 or idx >= len(lines):
                continue
            ln = lines[idx]
            nl = ""
            if ln.endswith("\r\n"): ln, nl = ln[:-2], "\r\n"
            elif ln.endswith("\n"): ln, nl = ln[:-1], "\n"
            lines[idx] = ln[:eff] + text + ln[eff:] + nl
        # относительный путь к cqtrace.js (файлы могут быть во вложенных каталогах)
        rel = os.path.relpath(out / "cqtrace.js", fp.parent).replace("\\", "/")
        if not rel.startswith("."):
            rel = "./" + rel
        # require рантайма — после 'use strict' (чтобы не сломать директиву), иначе сверху
        pos = 0
        for i, ln in enumerate(lines[:5]):
            if use_strict.match(ln):
                pos = i + 1; break
        lines.insert(pos, f"const cqtrace = require('{rel}');\n")
        fp.write_text("".join(lines), encoding="utf-8")

    shutil.copy(RUNTIME / "cqtrace.js", out / "cqtrace.js")

    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)

    print("[8] Проверка синтаксиса (node --check)...")
    errors = []
    for fp in sorted(touched):
        rel = fp.relative_to(out).as_posix()
        r = subprocess.run(["node", "--check", rel], cwd=out, capture_output=True, text=True)
        if r.returncode != 0:
            msg = r.stderr.strip().splitlines()
            errors.append((rel, msg[0] if msg else "syntax error"))
    if errors:
        with open(out / "Отчёт_об_ошибках_вставки.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";"); w.writerow(["Файл", "Ошибка"]); w.writerows(errors)
        print(f"[8] !!! Ошибок: {len(errors)} — см. Отчёт_об_ошибках_вставки.csv")
        sys.exit(2)
    print("[8] Синтаксис OK.")

    # Pruning: оставляем только инструментированные файлы + рантайм
    _js_exts = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}
    _runtime_js = out / "cqtrace.js"
    _pruned = 0
    for _p in list(out.rglob("*")):
        if _p.is_file() and _p.suffix.lower() in _js_exts \
                and _p != _runtime_js and _p not in touched:
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
