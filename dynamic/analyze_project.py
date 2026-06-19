#!/usr/bin/env python3
"""
Оркестратор анализа проекта: создаёт единую структуру каталогов и проводит
статический + динамический анализ.

Структура (root = <workspace>/<name>):
  orig-sources/            — проектные исходники из src.zip БД CodeQL
  instrumented-sources/    — копия с вставленными датчиками
  reports/static/          — статические отчёты + flowcharts/
  reports/dynamic/         — отчёты о покрытии + traces/

Этапы:
  1. извлечь проектные исходники из <db>/src.zip → orig-sources
  2. статика: main.py → reports/static (+ flowcharts)
  3. инструментация: instrument_cpp.py (orig-sources → instrumented-sources)
  4. (опц.) сборка+запуск инструментированного → traces
  5. (опц.) покрытие: coverage_report.py → reports/dynamic

Использование:
  python3 dynamic/analyze_project.py --name test-project-cpp \
      --db databases/small-projects/test-project-cpp-db \
      --marker test-project-cpp --language cpp --pattern '%test-project-cpp%' \
      --codeql codeql-linux/codeql --run-build
"""
import argparse, os, shutil, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # корень репозитория


def _find_compiler(*candidates: str) -> str:
    """Return first compiler found in PATH; last candidate is returned as fallback."""
    for c in candidates:
        if shutil.which(c):
            return c
    return candidates[-1]


def _cxx_compiler() -> str:
    return _find_compiler("g++", "clang++", "c++")


def _c_compiler() -> str:
    return _find_compiler("gcc", "clang", "cc")


def extract_sources(db: Path, marker: str, dest: Path):
    """Извлекает из src.zip файлы проекта (путь содержит marker) в dest,
    сохраняя структуру относительно сегмента marker."""
    src_zip = db / "src.zip"
    if not src_zip.exists():
        sys.exit(f"src.zip не найден в БД: {src_zip}")
    dest.mkdir(parents=True, exist_ok=True)
    seg = marker.strip("/") + "/"
    n = 0
    with zipfile.ZipFile(src_zip) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            norm = name.replace("\\", "/")
            i = norm.find(seg)
            if i < 0:
                continue
            rel = norm[i + len(seg):]          # путь относительно корня проекта
            if not rel:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as fsrc, open(target, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            n += 1
    print(f"[1] Извлечено исходников проекта: {n} → {dest}")
    return n


def run(cmd, **kw):
    print("    $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def detect_java_package(d):
    import re
    rx = re.compile(r"^\s*package\s+([\w.]+)\s*;")
    for f in sorted(Path(d).glob("*.java")):
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]:
            m = rx.match(line)
            if m:
                return m.group(1)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="имя проекта (каталог в workspace)")
    ap.add_argument("--db", required=True, help="каталог CodeQL БД")
    ap.add_argument("--marker", required=True, help="сегмент пути проекта в src.zip")
    ap.add_argument("--language", default="cpp")
    ap.add_argument("--pattern", default="", help="--pattern для статики")
    ap.add_argument("--codeql", default="codeql")
    ap.add_argument("--workspace", default=str(ROOT / "workspace"))
    ap.add_argument("--run-build", action="store_true",
                    help="собрать и запустить инструментированный код, построить покрытие")
    ap.add_argument("--entry", default="", help="точка входа (python: main.py, js: main.js)")
    ap.add_argument("--main-class", default="", help="главный класс Java (по умолчанию <pkg>.Main)")
    args = ap.parse_args()

    db = Path(args.db).resolve()
    root = Path(args.workspace).resolve() / args.name
    orig = root / "orig-sources"
    instr = root / "instrumented-sources"
    static = root / "reports" / "static"
    dynamic = root / "reports" / "dynamic"
    traces = dynamic / "traces"
    for d in (static, dynamic, traces):
        d.mkdir(parents=True, exist_ok=True)
    print(f"[0] Структура проекта: {root}")

    # 1. orig-sources из src.zip
    if orig.exists():
        shutil.rmtree(orig)
    extract_sources(db, args.marker, orig)

    # 2. Статика → reports/static
    print("[2] Статический анализ → reports/static ...")
    r = run([sys.executable, str(ROOT / "main.py"), str(db), "-o", str(static),
             "--language", args.language, "--pattern", args.pattern,
             "--codeql", args.codeql])
    if r.returncode != 0:
        sys.exit("Статический анализ завершился с ошибкой")

    # 3. Инструментация orig-sources → instrumented-sources (диспетч. по языку)
    instrumenters = {
        "cpp": "instrument_cpp.py", "python": "instrument_py.py",
        "javascript": "instrument_js.py", "java": "instrument_java.py",
    }
    log_prefix = {"cpp": "cpp", "python": "python", "javascript": "js", "java": "java"}
    if args.language not in instrumenters:
        sys.exit(f"Инструментация для языка {args.language} не реализована")
    print(f"[3] Инструментация ({args.language}) → instrumented-sources ...")
    r = run([sys.executable, str(ROOT / "dynamic" / instrumenters[args.language]),
             "--project", str(orig), "--db", str(db), "--reports", str(static),
             "--out", str(instr), "--codeql", args.codeql, "--lang", args.language])
    if r.returncode != 0:
        sys.exit("Инструментация: синтаксические ошибки (см. Отчёт_об_ошибках_вставки.csv)")

    if not args.run_build:
        print(f"\n[OK] Статика и инструментация готовы.\n"
              f"     Соберите/запустите {instr} → трассы в {traces},\n"
              f"     затем: coverage_report.py --traces <трассы> --reports {static} "
              f"--sensor-map {instr}/Карта_датчиков.csv --out {dynamic}")
        return

    # 4. Сборка + запуск инструментированного кода → трассы в reports/dynamic/traces
    print(f"[4] Сборка и запуск ({args.language}) ...")
    # HOME (Linux/macOS) и USERPROFILE (Windows) — оба нужны: C-рантайм проверяет
    # HOME, потом USERPROFILE; Python expanduser("~") — аналогично.
    env = {**os.environ, "HOME": str(traces), "USERPROFILE": str(traces)}
    if args.language == "cpp":
        exe_name = "instrumented.exe" if os.name == "nt" else "instrumented"
        exe = instr / exe_name
        cpps = [p.name for p in sorted(instr.iterdir()) if p.suffix in (".c", ".cpp", ".cc", ".cxx")]
        cxx = _cxx_compiler()
        rb = run([cxx, "-std=c++14", "-pthread", "-I", ".", "-o", str(exe), *cpps],
                 cwd=instr, capture_output=True, text=True)
        if rb.returncode != 0:
            print(rb.stderr[-2000:]); sys.exit("Сборка C/C++ не удалась")
        run([str(exe)], env=env, capture_output=True, text=True)
    elif args.language == "python":
        run([sys.executable, args.entry or "main.py"], cwd=instr, env=env,
            capture_output=True, text=True)
    elif args.language == "javascript":
        run(["node", args.entry or "main.js"], cwd=instr, env=env,
            capture_output=True, text=True)
    elif args.language == "java":
        classes = root / "classes"
        if classes.exists(): shutil.rmtree(classes)
        classes.mkdir()
        javas = [p.name for p in sorted(instr.glob("*.java"))]
        rb = run(["javac", "-d", str(classes), *javas], cwd=instr, capture_output=True, text=True)
        if rb.returncode != 0:
            print(rb.stderr[-2000:]); sys.exit("Сборка Java не удалась")
        main_class = args.main_class or (detect_java_package(instr) + ".Main")
        run(["java", f"-Duser.home={traces}", "-cp", str(classes), main_class],
            capture_output=True, text=True)

    logs = list(traces.glob(f"{log_prefix[args.language]}-*.log"))
    print(f"[4] Трасс создано: {len(logs)} в {traces}")
    if not logs:
        sys.exit("Трассы не созданы")

    # 5. Покрытие → reports/dynamic
    print("[5] Отчёты о покрытии → reports/dynamic ...")
    run([sys.executable, str(ROOT / "dynamic" / "coverage_report.py"),
         "--traces", str(traces), "--reports", str(static),
         "--sensor-map", str(instr / "Карта_датчиков.csv"), "--out", str(dynamic)])
    print(f"\n[OK] Полный анализ готов: {root}")


if __name__ == "__main__":
    main()
