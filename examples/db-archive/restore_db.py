#!/usr/bin/env python3
"""Восстановление CodeQL-БД тест-проекта test-project-cpp-branches.

Сама БД (examples/databases/small-projects/test-project-cpp-branches-db) —
сборочный артефакт и лежит в .gitignore. Её ЯДРО (db-cpp + src.zip) хранится
в git рядом, в этом каталоге, как zip — чтобы случайное удаление каталога БД
не теряло её безвозвратно. Регрессионные тесты БД не требуют (они на золотых
отчётах в reports/small-projects/cpp-branches), БД нужна лишь для повторной
генерации отчётов / инструментации.

Использование:
  python restore_db.py            # распаковать ядро БД из zip (быстро, без codeql)
  python restore_db.py --regen    # пересобрать БД из исходников (нужен codeql + g++)
"""
import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # корень репозитория
ZIP = HERE / "test-project-cpp-branches-db.zip"
DB = ROOT / "examples" / "databases" / "small-projects" / "test-project-cpp-branches-db"
SRC = ROOT / "examples" / "test-projects" / "small-projects" / "test-project-cpp-branches"


def unzip() -> None:
    if not ZIP.exists():
        raise SystemExit(f"Архив не найден: {ZIP}")
    if DB.exists():
        shutil.rmtree(DB)
    DB.mkdir(parents=True)
    with zipfile.ZipFile(ZIP) as z:
        z.extractall(DB)
    print(f"[OK] БД распакована из zip: {DB}")


def regen(codeql: str) -> None:
    srcs = sorted(p.name for p in SRC.glob("*.cpp"))
    cmd = [codeql, "database", "create", str(DB), "--language=cpp",
           f"--source-root={SRC}", "--overwrite",
           "--command=g++ -std=c++11 -c " + " ".join(srcs)]
    print("    $", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"[OK] БД пересобрана из исходников: {DB}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regen", action="store_true",
                    help="пересобрать БД из исходников через codeql (нужны codeql и g++)")
    ap.add_argument("--codeql", default="codeql", help="путь к codeql (для --regen)")
    args = ap.parse_args()
    if args.regen:
        regen(args.codeql)
    else:
        unzip()
