#!/usr/bin/env python3
"""
Инструментатор датчиков динамического анализа для PHP.

Вставляет:
  - $__cqtg_N = cqtrace_fn($fo, $se, $sx); — первым оператором тела каждой функции/метода;
    деструктор __CqtraceGuard автоматически пишет датчик выхода из ФО.
  - cqtrace_hit($fo, $br); — первым оператором тела каждой ветви (if/else/for/try/catch).

Требует Joern (Java 11+) для запроса точек вставки (queries/php/probe_points.sc).
Номера ФО и ветвей берутся из статических отчётов — совпадают со статикой 1:1.

Использование:
  python3 instrument_php.py --project <dir> --db <php-src-dir> --reports <static-dir>
      --out <work-dir> [--joern joern] [--lang php] [--pattern <substr>]
"""
import argparse, base64, csv, json, os, shutil, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
sys.path.insert(0, str(HERE.parent))   # корень проекта для импорта paths
from paths import third_party


def _b64enc(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def _to_wsl_path(p: str) -> str:
    s = str(p).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = f"/mnt/{s[0].lower()}{s[2:]}"
    return s


def _wsl_mode(joern_path: str) -> bool:
    return os.name == "nt" and not str(joern_path).lower().endswith(".bat")


def _find_wsl() -> str:
    found = shutil.which("wsl")
    if found:
        return found
    default = r"C:\Windows\System32\wsl.exe"
    if os.path.exists(default):
        return default
    return "wsl"


def _find_java_home(joern_path: str) -> str:
    root = Path(joern_path).resolve().parent.parent
    candidates = (
        ["jdk25-win", "jdk11-win"] if os.name == "nt"
        else ["jdk25-linux", "jdk11-linux", "jdk11"]
    )
    for name in candidates:
        java_bin = root / name / "bin" / ("java.exe" if os.name == "nt" else "java")
        if java_bin.exists():
            return str(root / name)
    return ""


def read_fo_numbers(reports_dir: Path) -> dict:
    fo = {}
    p = reports_dir / "Перечень_ФО(процедур_функций).csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if row and row[0].strip() and len(row) > 1 and row[1].strip():
                fo[row[1].strip()] = int(row[0])
    return fo


def read_branch_numbers(reports_dir: Path) -> dict:
    br = {}
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if len(row) >= 7 and row[2].strip() and row[6].strip():
                try:
                    br[(row[2].strip(), int(row[6]))] = int(row[3])
                except ValueError:
                    pass
    return br


def run_probe_query(joern_path: str, src_dir: Path, script: Path,
                    path_pattern: str = "") -> list:
    """Run probe_points.sc via Joern, return list of probe point dicts."""
    # Joern запускается с cwd=временный каталог, поэтому ОТНОСИТЕЛЬНЫЙ путь к joern
    # (напр. third-party/joern-cli/joern.bat) оттуда не найдётся → приводим к абсолютному.
    if os.path.exists(joern_path):
        joern_path = str(Path(joern_path).resolve())
    work_dir = Path(tempfile.mkdtemp(prefix="cq_php_probe_"))
    out_file = work_dir / "probe_points.jsonl"

    wsl = _wsl_mode(joern_path)
    if wsl:
        inp_b64 = _b64enc(_to_wsl_path(str(src_dir)))
        out_b64 = _b64enc(_to_wsl_path(str(out_file)))
    else:
        inp_b64 = _b64enc(str(src_dir))
        out_b64 = _b64enc(str(out_file))
    pat_b64 = _b64enc(path_pattern)

    injected = f'val _inp = "{inp_b64}"\nval _out = "{out_b64}"\nval _pat = "{pat_b64}"'
    script_src = script.read_text(encoding="utf-8")
    script_src = script_src.replace("// __PARAMS__", injected, 1)
    temp_script = work_dir / "probe_points_run.sc"
    temp_script.write_text(script_src, encoding="utf-8")

    if wsl:
        cmd = [_find_wsl(), _to_wsl_path(joern_path),
               "--script", _to_wsl_path(str(temp_script))]
    elif sys.platform == "win32":
        cmd = ["cmd", "/c", joern_path, "--script", str(temp_script)]
    else:
        cmd = [joern_path, "--script", str(temp_script)]

    env = os.environ.copy()
    env.setdefault("_JAVA_OPTIONS", "-Xmx2g")
    if not wsl:
        java_home = _find_java_home(joern_path)
        if java_home:
            env["JAVA_HOME"] = java_home
        php_dir = third_party("php-8.3")
        if (php_dir / "php.exe").exists() and str(php_dir) not in env.get("PATH", ""):
            env["PATH"] = str(php_dir) + os.pathsep + env.get("PATH", "")

    joern_cwd = tempfile.mkdtemp(prefix="joern_wd_")
    subprocess.run(cmd, check=True, env=env, cwd=joern_cwd)

    pts = []
    if out_file.exists():
        for line in out_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                pts.append({
                    "kind":      row.get("kind", ""),
                    "func":      row.get("func", ""),
                    "file":      row.get("file", "").replace("\\", "/"),
                    "ref_line":  int(row.get("ref_line", 0)),
                    "ins_line":  int(row.get("ins_line", 0)),
                    "ins_col":   int(row.get("ins_col", 0)),
                    "has_block": int(row.get("has_block", 1)),
                    "btype":     row.get("btype", ""),
                })
            except Exception:
                pass

    shutil.rmtree(work_dir, ignore_errors=True)
    return pts


def _require_line(fname: str) -> str:
    """require_once line with path relative to the file's own directory."""
    return "require_once __DIR__ . '/cqtrace.php';\n"


def _insert_require(lines: list) -> list:
    """Insert require_once after <?php tag if not already present."""
    req = _require_line("")
    for ln in lines[:5]:
        if "cqtrace.php" in ln:
            return lines          # already present
    ins_pos = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("<?php") or s.startswith("<?"):
            ins_pos = i + 1
            break
    lines.insert(ins_pos, req)
    return lines


def main():
    ap = argparse.ArgumentParser(description="PHP dynamic instrumentation")
    ap.add_argument("--project",     required=True, help="PHP source directory")
    ap.add_argument("--db",          required=True, help="PHP source directory (same as --project for PHP)")
    ap.add_argument("--reports",     required=True, help="Static analysis reports directory")
    ap.add_argument("--out",         required=True, help="Output directory for instrumented sources")
    ap.add_argument("--joern",       default="joern", help="Path to joern executable")
    ap.add_argument("--lang",        default="php")
    ap.add_argument("--pattern",     default="", help="File path substring filter for Joern")
    ap.add_argument("--no-branches", action="store_true",
                    help="Instrument function entries only (skip branch sensors)")
    args = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from src_copy import copy_src_files

    project = Path(args.project).resolve()
    out     = Path(args.out).resolve()
    reports = Path(args.reports).resolve()
    src_dir = Path(args.db).resolve()   # for PHP: source directory, not a CodeQL DB

    print(f"[1] Копирую .php файлы → {out} …")
    n = copy_src_files(project, out, "php")
    print(f"    Скопировано: {n}")

    fo_num = read_fo_numbers(reports)
    br_num = read_branch_numbers(reports)
    print(f"[2] ФО: {len(fo_num)}, ветвей: {len(br_num)}")

    script = HERE.parent / "queries" / "php" / "probe_points.sc"
    print(f"[3] Запрос точек вставки через Joern …")
    pts = run_probe_query(args.joern, src_dir, script, args.pattern)
    print(f"    Получено точек: {len(pts)}")

    # Index output .php files by basename for path matching
    by_base: dict = defaultdict(list)
    for p in out.rglob("*.php"):
        by_base[p.name].append((p.relative_to(out).as_posix(), p))

    def match_file(probe_path: str):
        base = probe_path.rsplit("/", 1)[-1]
        cands = by_base.get(base, [])
        if len(cands) == 1:
            return cands[0][1]
        best = None
        for rel, p in cands:
            if probe_path.endswith("/" + rel):
                if best is None or len(rel) > len(best[0]):
                    best = (rel, p)
        return best[1] if best else None

    # insertions[Path] = list of (ins_line, ins_col, text, prio)
    insertions: dict = defaultdict(list)
    sensor_map = []
    skipped = 0
    sid = 1

    for pt in pts:
        if args.no_branches and pt["kind"] != "entry":
            continue
        if pt["has_block"] == 0 or pt["ins_line"] <= 0:
            skipped += 1
            continue

        fp = match_file(pt["file"])
        if fp is None:
            skipped += 1
            continue

        fn = pt["func"]
        if fn not in fo_num:
            skipped += 1
            continue
        fo = fo_num[fn]

        if pt["kind"] == "entry":
            se, sx = sid, sid + 1
            sid += 2
            text = f"$__cqtg_{se} = cqtrace_fn({fo}, {se}, {sx});"
            prio = 1
            sensor_map.append((se, fo, 0,  fp.relative_to(out).as_posix(),
                                pt["ins_line"], "вход"))
            sensor_map.append((sx, fo, -1, fp.relative_to(out).as_posix(),
                                pt["ins_line"], "выход"))
        else:
            key = (fn, pt["ref_line"])
            if key not in br_num:
                skipped += 1
                continue
            bn = br_num[key]
            s  = sid
            sid += 1
            text = f"cqtrace_hit({fo}, {bn});"
            prio = 0
            sensor_map.append((s, fo, bn, fp.relative_to(out).as_posix(),
                                pt["ins_line"], pt["btype"]))

        insertions[fp].append((pt["ins_line"], pt["ins_col"], text, prio))

    total = len(sensor_map)
    print(f"[4] Датчиков: {total} в {len(insertions)} файлах (пропущено: {skipped})")

    # Apply insertions: process each file, reverse-order by line to keep positions valid
    files_touched = set(insertions.keys())
    for fp in files_touched:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        # Sort by line descending; within same line: branches first (prio=0), then entry (prio=1)
        for ins_line, ins_col, text, _prio in sorted(
                insertions[fp], key=lambda x: (-x[0], x[3])):
            idx = ins_line - 1
            if idx < 0 or idx >= len(lines):
                continue
            # Derive indentation from the target line if ins_col == 0
            if ins_col > 0:
                indent = " " * ins_col
            else:
                raw = lines[idx]
                indent = raw[: len(raw) - len(raw.lstrip())]
            lines.insert(idx, indent + text + "\n")

        lines = _insert_require(lines)
        fp.write_text("".join(lines), encoding="utf-8")

    # Copy runtime to output root
    shutil.copy2(RUNTIME / "cqtrace.php", out / "cqtrace.php")
    print(f"[5] Рантайм скопирован → {out / 'cqtrace.php'}")

    # Write sensor map
    with open(out / "Карта_датчиков.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sid", "№ ФО", "Запись (br)", "Файл", "Строка", "Тип"])
        for sm in sorted(sensor_map):
            w.writerow(sm)

    print(f"[OK] Инструментировано. Датчиков: {total}.")


if __name__ == "__main__":
    main()
