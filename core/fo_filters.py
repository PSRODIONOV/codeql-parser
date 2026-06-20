#!/usr/bin/env python3
"""Пост-фильтры списка функциональных объектов (ФО) — применяются после
получения сырых результатов functional_objects.ql, ДО сохранения в кэш/CSV,
чтобы ФО, которые физически невозможно ни показать как отдельную сущность,
ни инструментировать для динамики, не попадали ни в один отчёт.

Используется и из main.py (CLI), и из core/project_runner.py (GUI) — раньше
фильтр жил только в main.py, и GUI-прогон (через project_runner) его не
вызывал. Из-за этого такие ФО оставались в Перечень_ФО с валидным номером,
инструментатор находил их через _lookup_fo и пытался вставить датчик в
позицию, где надёжного места для него нет (X-macro списки вида
hotspot/.../classes.hpp: один файл многократно #include-ится с разным
#define macro(x), раскрываясь то в функцию, то в элемент enum/массива) —
обёртка вставленным датчиком ломала синтаксис enum/массива в других местах
подключения того же файла.
"""
import re
import zipfile
from pathlib import Path

# Удаление комментариев из строки исходника перед проверкой «имя ФО встречается
# в коде»: имя, упомянутое в КОММЕНТАРИИ (напр. «// -> int get_answer(void)…»),
# не означает, что программист написал саму функцию — иначе ФО, целиком собранный
# макросом (##-склейка), ошибочно НЕ исключается. Строчные // и однострочные
# блочные /* */ убираем; многострочные блоки игнорируем (на строке объявления
# функции практически не встречаются).
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/")
_LINE_COMMENT = re.compile(r"//.*$")


def _strip_comments(line: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", line))


def read_source_snapshot(db_path):
    """Индексирует исходники из src.zip внутри БД по базовому имени файла."""
    result = {}
    src_zip = Path(db_path) / "src.zip"
    if not src_zip.exists():
        return result
    try:
        with zipfile.ZipFile(src_zip) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                base = name.replace("\\", "/").rsplit("/", 1)[-1]
                if base in result:
                    continue
                try:
                    result[base] = z.read(name).decode("utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
    except (zipfile.BadZipFile, OSError):
        pass
    return result


def filter_macro_synthesized_fo(func_data, source_by_base, log=None):
    """Исключает ФО, чьё короткое имя (f.getName()) физически не встречается
    на указанной строке исходника — признак того, что имя целиком собрано
    макросом через ##-склейку токенов (X-macro вида macro(Name) ->
    Class##Node::Method) либо макрос целиком сконструировал функцию
    (G_DEFINE_TYPE и подобные). Для части таких случаев уже работает
    isInMacroExpansion() в самих .ql-запросах, но не для всех — напр. для
    X-macro CodeQL репортит позицию АРГУМЕНТА макроса (он литерален), а не
    итогового склеенного имени, поэтому isInMacroExpansion() там не
    срабатывает. Эта проверка — по факту, без знания механизма макроса.

    log — необязательная функция логирования (см. _log в project_runner.py
    или просто print в main.py); вызывается с одним строковым аргументом.
    """
    result = []
    excluded = 0
    for item in func_data:
        name = item.get("name", "")
        path = item.get("file", "")
        line_s = item.get("line", "")
        if not name or not path or not line_s:
            result.append(item)
            continue
        try:
            line_no = int(line_s)
        except (ValueError, TypeError):
            result.append(item)
            continue
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        lines = source_by_base.get(base)
        if not lines or not (1 <= line_no <= len(lines)):
            result.append(item)  # нет снэпшота строки — не можем проверить, не исключаем
            continue
        # Сравниваем с исходной строкой БЕЗ комментариев — иначе имя,
        # упомянутое в комментарии, маскирует ##-склеенное имя ФО.
        if name in _strip_comments(lines[line_no - 1]):
            result.append(item)
        else:
            excluded += 1
    if excluded and log:
        log(f"[functional] Исключено {excluded} ФО — имя целиком собрано "
            f"макросом (не найдено в тексте исходной строки)")
    return result


def filter_info_by_excluded_fo(info_data, excluded_func_names):
    """Исключает ИО (локальные переменные), объявленные в исключённых ФО.

    Для локальных переменных qualified_name = FunctionName::varName —
    извлекаем имя ФО и проверяем, есть ли оно в excluded_func_names.
    Глобальные/статические/поля class не затрагиваются (нет enclosing ФО).
    """
    if not excluded_func_names:
        return info_data
    result = []
    excluded = 0
    for item in info_data:
        if item.get("kind") == "local variable":
            qname = item.get("qualified_name", "")
            func_name = qname.split("::", 1)[0] if "::" in qname else ""
            if func_name in excluded_func_names:
                excluded += 1
                continue
        result.append(item)
    return result
