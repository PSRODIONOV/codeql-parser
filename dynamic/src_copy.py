"""
Filtered source copy: only language-relevant files, directory hierarchy preserved.
Used by instrument_*.py scripts and gui_project.py.
"""
from __future__ import annotations
import shutil
from pathlib import Path

LANG_EXTS: dict[str, set[str]] = {
    "cpp":        {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".inl"},
    "python":     {".py", ".pyx"},
    "javascript": {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"},
    "java":       {".java"},
    "php":        {".php", ".php3", ".php4", ".php5", ".phtml"},
}


def copy_src_files(src: Path, dst: Path, lang: str) -> int:
    """Copy only language-relevant files from src into dst, preserving relative paths.

    dst is created if absent; existing dst is cleared first.
    Returns the number of files copied.
    """
    exts = LANG_EXTS.get(lang, set())
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    if not exts:
        # unknown lang — fall back to full copy
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return sum(1 for p in dst.rglob("*") if p.is_file())

    n = 0
    for p in src.rglob("*"):
        if p.is_file() and p.suffix.lower() in exts:
            rel = p.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    return n
