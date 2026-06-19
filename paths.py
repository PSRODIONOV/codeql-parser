"""Центральный резолвер путей: корень проекта и заимствованные инструменты.

Все заимствования (CodeQL, JDK, Maven, Node.js, PHP, Joern, vendored-пакеты)
лежат в каталоге third-party/. Чтобы избежать хрупкой арифметики
``Path(__file__).parent`` в каждом модуле (она ломается при переносе модулей
в подпакеты), корень определяется по устойчивому маркеру, а доступ к
заимствованиям идёт через ``third_party(...)``.
"""
from pathlib import Path


def _find_root(start: Path) -> Path:
    """Поднимается вверх от ``start`` до каталога-корня проекта.

    Маркер корня — наличие каталога ``queries`` и файла ``README.md`` вместе
    (есть в корне и отсутствует в подкаталогах). Если не найден — возвращает
    ``start`` (безопасный фолбэк).
    """
    for d in [start, *start.parents]:
        if (d / "queries").is_dir() and (d / "README.md").is_file():
            return d
    return start


PROJECT_ROOT = _find_root(Path(__file__).resolve().parent)
THIRD_PARTY = PROJECT_ROOT / "third-party"


def third_party(*parts: str) -> Path:
    """Путь внутри third-party/, например ``third_party('codeql-win', 'codeql.exe')``."""
    return THIRD_PARTY.joinpath(*parts)
