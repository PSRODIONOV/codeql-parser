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

Использование:
  python3 instrument_java.py --project <dir> --db <codeql-db> --reports <static-dir>
      --out <work-dir> [--codeql codeql] [--lang java]
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
    ap.add_argument("--project", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--lang", default="java")
    ap.add_argument("--pattern", default="", help="Паттерн пути проекта для isProjectFile")
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
    n = copy_src_files(project, out, "java")
    print(f"[1] Скопировано .java-файлов: {n} → {out}")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    pts = run_probe_query(args.codeql, Path(args.db).resolve(),
                          HERE.parent / "queries" / args.lang / "probe_points.ql",
                          path_pattern=args.pattern or "%")
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

    # prio: при совпадении (строка, позиция) — вставка «перед }» (prio=1) идёт
    # раньше «после {» (prio=0). Нужно для пустых тел `{}`, где обе позиции совпадают.
    def add_ins(fpath, line, eff_index, prio, text):
        ins.setdefault(fpath, []).append((line, eff_index, prio, text)); touched.add(fpath)

    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue  # отключена инструментация ветвей
        fpath = match_file(pt["file"])
        if fpath is None: continue
        base = fpath.relative_to(out).as_posix()
        fn = pt["func"]
        if fn not in fo_num:
            skipped.append((fn, pt["kind"], "ФО нет в Перечень_ФО")); continue
        fo = fo_num[fn]
        if pt["kind"] == "entry":
            if pt["open_col"] <= 0 or pt["close_col"] <= 0:
                skipped.append((fn, "entry", "нет позиции тела")); continue
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, 0); try {{")
            add_ins(fpath, pt["close_line"], pt["close_col"] - 1, 1,
                    f"}} finally {{ {ref}.hit({fo}, -1); }} ")
            sensor_map.append((fo, 0, base, pt["open_line"], "вход/выход"))
        else:
            key = (fn, pt["ref_line"])
            if key not in br_num:
                skipped.append((fn, f"branch@{pt['ref_line']}", "ветви нет в Перечень_ветвей")); continue
            if pt["open_col"] <= 0:
                skipped.append((fn, "branch", "нет позиции блока")); continue
            bn = br_num[key]
            add_ins(fpath, pt["open_line"], pt["open_col"], 0, f" {ref}.hit({fo}, {bn});")
            sensor_map.append((fo, bn, base, pt["open_line"], pt["btype"]))

    print(f"[4] Датчиков: {len(sensor_map)} (пропущено точек: {len(skipped)})")

    for fp in touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        for line, eff, prio, text in sorted(ins[fp], key=lambda x: (x[0], x[1], x[2]), reverse=True):
            idx = line - 1
            if idx < 0 or idx >= len(lines): continue
            ln = lines[idx]; nl = ""
            if ln.endswith("\r\n"): ln, nl = ln[:-2], "\r\n"
            elif ln.endswith("\n"): ln, nl = ln[:-1], "\n"
            lines[idx] = ln[:eff] + text + ln[eff:] + nl
        fp.write_text("".join(lines), encoding="utf-8")

    # Рантайм Cqtrace.java — в КАТАЛОГ пакета (для Maven: src/main/org/h2/Cqtrace.java).
    tmpl = (RUNTIME / "Cqtrace.java.tmpl").read_text(encoding="utf-8")
    cq = tmpl.replace("@PACKAGE@", pkg if pkg else "")
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
        w.writerow(["№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map): w.writerow(sm)

    # Проверка синтаксиса — javac всех плоских .java (только для мелких проектов).
    # Для проектов со своей сборкой (Maven/Gradle) её роль выполняет последующая сборка.
    if args.no_syntax_check:
        print("[8] Проверка синтаксиса пропущена (--no-syntax-check; проверит сборка).")
    else:
        print("[8] Проверка синтаксиса (javac)...")
        chk = out / ".syntax_check"; chk.mkdir(exist_ok=True)
        java_files = [p.name for p in sorted(out.glob("*.java"))]
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
