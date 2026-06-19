#!/usr/bin/env python3
"""
Инструментатор датчиков динамического анализа для Python.

Вставляет:
  - декоратор @cqtrace.fn(<ФО>) над каждым def (вход/выход ФО);
  - cqtrace._t(<ФО>, <#N>) первым оператором тела каждой ветви (if/for/while/try).

Номера ФО и ветвей берутся из статических отчётов (Перечень_ФО / Перечень_ветвей),
поэтому совпадают со статикой 1:1. Проверка синтаксиса — ast.parse по каждому файлу.

Использование:
  python3 instrument_py.py --project <dir> --db <codeql-db> --reports <static-dir>
      --out <work-dir> [--codeql codeql] [--lang python]
"""
import argparse, tempfile, ast, csv, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"


def _runtime_import_pos(lines):
    """Позиция для вставки `import cqtrace`: после модульного докстринга и всех
    `from __future__ import ...` (они обязаны идти в начале файла)."""
    n = len(lines)
    i = 0
    while i < n and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    # пропустить модульный докстринг (тройные кавычки)
    if i < n:
        st = lines[i].lstrip()
        for pre in ('r', 'R', 'b', 'u', ''):
            for q in ('"""', "'''"):
                if st.startswith(pre + q):
                    after = st[len(pre + q):]
                    if q in after:                 # однострочный докстринг
                        i += 1
                    else:
                        i += 1
                        while i < n and q not in lines[i]:
                            i += 1
                        if i < n:
                            i += 1
                    break
            else:
                continue
            break
    pos = i
    while i < n:
        s = lines[i].strip()
        if not s or s.startswith("#"):
            i += 1; continue
        if s.startswith("from __future__ import"):
            i += 1; pos = i; continue
        break
    return pos


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
    bqrs = Path(tempfile.gettempdir(), "probe_py.bqrs"); csvp = Path(tempfile.gettempdir(), "probe_py.csv")
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
            pts.append({"kind": row[0], "func": row[1], "file": row[2],
                        "ref_line": int(row[3]), "ins_line": int(row[4]),
                        "ins_col": int(row[5]), "btype": row[7]})
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="python")
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
    n = copy_src_files(project, out, "python")
    print(f"[1] Скопировано .py-файлов: {n} → {out}")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    pts = run_probe_query(args.codeql, Path(args.db).resolve(),
                          HERE.parent / "queries" / args.lang / "probe_points.ql",
                          path_pattern=args.pattern or "%")
    print(f"[3] Точек вставки: {len(pts)}")

    # Индекс файлов по basename → [(relpath_posix, Path)] для сопоставления по
    # относительному пути (вложенные пакеты с дублями __init__.py).
    from collections import defaultdict
    by_base = defaultdict(list)
    for p in out.rglob("*.py"):
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

    # insertions[Path] = list of (ins_line, text)  — вставка ЦЕЛОЙ строки выше ins_line
    insertions = {}
    sensor_map = []
    skipped = []
    files_touched = set()
    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue  # отключена инструментация ветвей
        fpath = match_file(pt["file"])
        if fpath is None:
            continue
        base = fpath.relative_to(out).as_posix()
        if pt["ins_line"] <= 0 or pt["ins_col"] <= 0:
            skipped.append((pt["func"], pt["kind"], "нет позиции")); continue
        fn = pt["func"]
        if fn not in fo_num:
            skipped.append((fn, pt["kind"], "ФО нет в Перечень_ФО")); continue
        fo = fo_num[fn]
        indent = " " * (pt["ins_col"] - 1)
        # prio: при совпадении строки вставки декоратор (entry, prio=0) должен
        # оказаться ближе к def, а ветка (prio=1) — ВЫШЕ него. Это случается, когда
        # тело ветви начинается с вложенного декорированного def.
        if pt["kind"] == "entry":
            text = f"{indent}@cqtrace.fn({fo})"
            prio = 0
            sensor_map.append((fo, 0, base, pt["ins_line"], "вход/выход"))
        else:
            key = (fn, pt["ref_line"])
            if key not in br_num:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей")); continue
            bn = br_num[key]
            text = f"{indent}cqtrace._t({fo}, {bn})"
            prio = 1
            sensor_map.append((fo, bn, base, pt["ins_line"], pt["btype"]))
        insertions.setdefault(fpath, []).append((pt["ins_line"], prio, text))
        files_touched.add(fpath)

    print(f"[4] Датчиков: ФО+ветви = {len(sensor_map)} (пропущено: {len(skipped)})")

    # Применяем вставки. Порядок: строка по убыванию; при равной строке сначала
    # entry (декоратор, prio=0), потом ветка (prio=1) — чтобы ветка встала ВЫШЕ
    # декоратора (последняя вставка в ту же позицию оказывается сверху).
    for fp in files_touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        nl = "\n"
        for ins_line, prio, text in sorted(insertions[fp], key=lambda x: (-x[0], x[1])):
            idx = ins_line - 1
            if idx < 0 or idx > len(lines): continue
            lines.insert(idx, text + nl)
        # `import cqtrace` — ПОСЛЕ возможных `from __future__ import ...`
        # (они обязаны идти в начале файла). Иначе SyntaxError.
        lines.insert(_runtime_import_pos(lines), "import cqtrace\n")
        fp.write_text("".join(lines), encoding="utf-8")

    shutil.copy(RUNTIME / "cqtrace.py", out / "cqtrace.py")

    # Pruning: оставляем только инструментированные файлы + рантайм
    _keep = files_touched | {out / "cqtrace.py"}
    _pruned = 0
    for _p in list(out.rglob("*")):
        if _p.is_file() and _p.suffix.lower() in {".py", ".pyx"} and _p not in _keep:
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

    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)

    # Проверка синтаксиса — ast.parse
    # Ошибки не прерывают инструментацию: Python-2-файлы или legacy-код с
    # синтаксисом, несовместимым с Python 3, существовали ДО вставки датчиков.
    print("[8] Проверка синтаксиса (ast.parse)...")
    errors = []
    for fp in sorted(files_touched):
        base = fp.relative_to(out).as_posix()
        try:
            ast.parse(fp.read_text(encoding="utf-8"))
        except SyntaxError as e:
            errors.append((base, f"строка {e.lineno}: {e.msg}"))
    if errors:
        with open(out / "Отчёт_об_ошибках_вставки.csv", "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";"); w.writerow(["Файл", "Ошибка"]); w.writerows(errors)
        print(f"[8] Предупреждение: {len(errors)} файлов с синтаксическими ошибками "
              f"(Python 2 / несовместимый синтаксис) — см. Отчёт_об_ошибках_вставки.csv")
    else:
        print("[8] Синтаксис OK.")
    print(f"[OK] Инструментировано. Датчиков: {len(sensor_map)}")


if __name__ == "__main__":
    main()
