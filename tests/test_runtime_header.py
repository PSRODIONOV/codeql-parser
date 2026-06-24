"""Регресс бага #10: __trace_singlehdr.h должен компилироваться в C под
ЛЮБЫМ -std=, включая строгий ANSI/C89, где bare "inline" — не ключевое
слово языка (фича C99+). См. dynamic/runtime/__trace_singlehdr.h:78-85
и src/iniparser.c в реальном проекте (Error.txt) — без __inline__ вместо
inline компиляция любого C-файла со своей сборкой в C89-режиме ломалась
каскадом ошибок на каждом __TRACE_FN()."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
HEADER = ROOT / "dynamic" / "runtime" / "__trace_singlehdr.h"

SNIPPET = """
#include "__trace.h"
int demo(int x) {
    __TRACE_FN(1, 2, 3);
    __TRACE(4, 5, 6);
    return x;
}
"""

# (компилятор, -std, расширение исходника)
CASES = [
    ("gcc", "c89", "c"),
    ("gcc", "gnu89", "c"),
    ("gcc", "c99", "c"),
    ("g++", "c++11", "cpp"),
]


@pytest.fixture(scope="module")
def header_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("trace_header")
    shutil.copyfile(HEADER, d / "__trace.h")
    return d


@pytest.mark.parametrize("compiler,std,ext", CASES, ids=[f"{c}-{s}" for c, s, _ in CASES])
def test_header_compiles_under_std(header_dir, tmp_path, compiler, std, ext):
    if shutil.which(compiler) is None:
        pytest.skip(f"{compiler} не найден в PATH")
    src = tmp_path / f"snippet.{ext}"
    src.write_text(SNIPPET, encoding="utf-8")
    obj = tmp_path / "snippet.o"
    cmd = [compiler, f"-std={std}", "-Wall", f"-I{header_dir}", "-c", str(src), "-o", str(obj)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, (
        f"{compiler} -std={std} не скомпилировал __trace.h:\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert obj.exists()
