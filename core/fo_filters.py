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
    """Индексирует исходники из src.zip внутри БД — по ОТНОСИТЕЛЬНОМУ пути
    (после вычитания общего префикса build-машины, см. detect_db_prefix) И
    по basename (запасной вариант, см. _pick_snapshot ниже).

    Баг (реальный проект, gosjava): индексация ТОЛЬКО по basename (как было
    раньше) брала ПЕРВЫЙ попавшийся файл с данным именем и отдавала его для
    ВСЕХ файлов с тем же именем в разных каталогах — напр. в src.zip были
    ОДНОВРЕМЕННО org/omg/CORBA/StringSeqHelper.java и com/sun/corba/se/spi/
    activation/RepositoryPackage/StringSeqHelper.java. filter_macro_
    synthesized_fo сверял имя ФО (insert/extract/read) со строкой ЧУЖОГО
    файла, не находил совпадения и ложно решал, что имя "собрано макросом",
    теряя реальные ФО (см. ровно тот же класс багов и тот же приём фикса —
    match_file_by_relpath в dynamic/instrument_java.py, история коллизии
    basename на CharacterData.java)."""
    from core.file_lists import detect_db_prefix
    by_relpath, by_base = {}, {}
    src_zip = Path(db_path) / "src.zip"
    if not src_zip.exists():
        return {"by_relpath": by_relpath, "by_base": by_base, "prefix": ""}
    try:
        prefix = detect_db_prefix(str(src_zip))
    except Exception:
        prefix = ""
    try:
        with zipfile.ZipFile(src_zip) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                norm = name.replace("\\", "/").lstrip("/")
                rel = norm[len(prefix):] if prefix and norm.startswith(prefix) else norm
                try:
                    lines = z.read(name).decode("utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                by_relpath[rel] = lines
                by_base.setdefault(rel.rsplit("/", 1)[-1], []).append((rel, lines))
    except (zipfile.BadZipFile, OSError):
        pass
    return {"by_relpath": by_relpath, "by_base": by_base, "prefix": prefix}


def _pick_snapshot(snapshot, abs_path: str):
    """Находит строки исходника по абсолютному пути ФО (build-машина).

    Сначала — точное совпадение по относительному пути (после вычитания
    того же prefix, что использовался при индексации — однозначно, без
    риска коллизии basename). Если файл не нашёлся (напр. не входил в
    охват --pattern при индексации) — запасной вариант по basename, но
    ТОЛЬКО если ровно один кандидат действительно совпадает хвостом пути
    (иначе вернуть None: лучше не проверять строку вообще, чем сверить её
    со случайно подвернувшимся ОДНОИМЁННЫМ, но другим файлом)."""
    if not snapshot or not abs_path:
        return None
    norm = abs_path.replace("\\", "/").lstrip("/")
    prefix = snapshot.get("prefix", "")
    rel = norm[len(prefix):] if prefix and norm.startswith(prefix) else norm
    exact = snapshot.get("by_relpath", {}).get(rel)
    if exact is not None:
        return exact
    base = rel.rsplit("/", 1)[-1]
    cands = [lines for r, lines in snapshot.get("by_base", {}).get(base, [])
              if rel.endswith(r) or r.endswith(rel)]
    return cands[0] if len(cands) == 1 else None


def filter_macro_synthesized_fo(func_data, snapshot, log=None):
    """Исключает ФО, чьё короткое имя (f.getName()) физически не встречается
    на указанной строке исходника — признак того, что имя целиком собрано
    макросом через ##-склейку токенов (X-macro вида macro(Name) ->
    Class##Node::Method) либо макрос целиком сконструировал функцию
    (G_DEFINE_TYPE и подобные). Для части таких случаев уже работает
    isInMacroExpansion() в самих .ql-запросах, но не для всех — напр. для
    X-macro CodeQL репортит позицию АРГУМЕНТА макроса (он литерален), а не
    итогового склеенного имени, поэтому isInMacroExpansion() там не
    срабатывает. Эта проверка — по факту, без знания механизма макроса.

    ВАЖНО: применять ТОЛЬКО для cpp/c — у остальных языков нет ни
    препроцессора, ни макросов (см. вызывающий код в core/project_runner.py
    и main.py — там стоит условие по языку).

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
        lines = _pick_snapshot(snapshot, path)
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
