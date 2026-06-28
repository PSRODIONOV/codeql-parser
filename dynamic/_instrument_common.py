"""Общие хелперы для instrument_c_make.py/instrument_cpp.py.

Оба скрипта инструментируют C/C++ исходники одинаковым текстовым способом
(вставка __TRACE/__TRACE_FN) — здесь то, что у них реально общее.
"""
import csv
import re
from pathlib import Path


def _parse_pos(s: str):
    """'line:col' -> (line, col); пусто/мусор -> (0, 0)."""
    if s and ":" in s:
        a, b = s.split(":", 1)
        try:
            return int(a), int(b)
        except ValueError:
            pass
    return 0, 0


def read_fo_geometry(reports_dir: Path):
    """Геометрия входа/выхода ФО — из Перечень_ФО(процедур_функций).csv
    (колонки "Позиция входа"/"Позиция выхода", считаются в
    queries/cpp/functional_objects.ql). Формат результата: kind/func/file/
    ref_line/ins_line/ins_col/has_block/btype/end_line/end_col — это и
    ожидает main() обоих инструментаторов."""
    pts = []
    p = reports_dir / "Перечень_ФО(процедур_функций).csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if not (row and row[0].strip() and len(row) > 5 and row[1].strip()):
                continue
            name = row[1].strip()
            m = re.match(r'^(.*)\((\d+)\)$', row[2].strip()) if row[2].strip() else None
            if not m:
                continue
            file, ref_line = m.group(1), int(m.group(2))
            ins_line, ins_col = _parse_pos(row[4].strip())
            end_line, end_col = _parse_pos(row[5].strip())
            pts.append({"kind": "entry", "func": name, "file": file, "ref_line": ref_line,
                        "ins_line": ins_line, "ins_col": ins_col, "has_block": 1, "btype": "-",
                        "end_line": end_line, "end_col": end_col})
    return pts


def read_branch_geometry(reports_dir: Path):
    """Геометрия ветвей — из Перечень_ветвей.csv (колонки "Позиция вставки"/
    "Блок"/"Позиция конца", считаются в queries/cpp/function_flow.ql/
    viz/flowchart_generator.py). catch — обычные строки этого же отчёта
    (Тип=catch, со своим номером ветви, см. queries/cpp/catch_points.ql).
    has_block читается напрямую из колонки "Блок" (а не выводится из Тип) —
    надёжнее при появлении новых типов веток. Формат результата — тот же,
    что ожидает main() обоих инструментаторов."""
    pts = []
    p = reports_dir / "Перечень_ветвей.csv"
    with open(p, encoding="utf-8-sig") as fh:
        for row in list(csv.reader(fh, delimiter=";"))[1:]:
            if not (len(row) >= 9 and row[2].strip() and row[6].strip()):
                continue
            func, btype, file, ref_line = row[2].strip(), row[4].strip(), row[5].strip(), int(row[6])
            ins_line, ins_col = _parse_pos(row[7].strip())
            try:
                has_block = int(row[8].strip()) if row[8].strip() != "" else 1
            except ValueError:
                has_block = 1
            end_line, end_col = _parse_pos(row[9].strip()) if len(row) > 9 else (0, 0)
            pts.append({"kind": "branch", "func": func, "file": file, "ref_line": ref_line,
                        "ins_line": ins_line, "ins_col": ins_col, "has_block": has_block,
                        "btype": btype, "end_line": end_line, "end_col": end_col})
    return pts


def sids_in_text(text: str) -> set:
    """Извлечь sid-ы датчика из текста вставки — для отметки "не вставлен"
    при пропуске inline_candidate (см. dropped_sids в main обоих скриптов).
    __TRACE_FN(fo, se, sx) — sid-ы это se/sx (2-е и 3-е число); __TRACE(s,
    fo, br) — sid это s (1-е число)."""
    nums = [int(n) for n in re.findall(r'\d+', text)]
    if text.startswith("__TRACE_FN("):
        return set(nums[1:3])
    return {nums[0]} if nums else set()


def first_real_brace(ln: str) -> int:
    """Найти позицию первой "настоящей" '{' в строке — пропуская символьные/
    строковые литералы и однострочный комментарий (// ...). Fallback при
    разрешении inline_candidate, когда { на заявленной CodeQL-позиции нет:
    без пропуска литералов/комментариев самодостаточный макрос без единой
    настоящей { на строке ложно находил бы '{' в соседнем комментарии."""
    in_str = None  # None | '"' | "'"
    i, n = 0, len(ln)
    while i < n:
        c = ln[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ('"', "'"):
            in_str = c
            i += 1
            continue
        if c == '/' and i + 1 < n and ln[i + 1] == '/':
            break  # остаток строки — комментарий
        if c == '{':
            return i
        i += 1
    return -1


def is_reliable_stmt_end(ch: str) -> bool:
    """Похож ли символ ch на конец полноценного оператора (а не на
    обрезанный идентификатор)? Любой одиночный оператор (ExprStmt/
    ReturnStmt/ThrowStmt/break/continue/пустой ';', GNU statement-expression
    '({ ... })' и т.п.) заканчивается ПУНКТУАЦИЕЙ (';', ')', '}' ...), а не
    буквой/цифрой/'_'. Буква/цифра/'_' на этой позиции означает, что
    координата конца оператора от CodeQL обрезана ВНУТРИ идентификатора —
    признак макроса-аргумента, который сам закрывает список аргументов
    вызова (напр. HotSpot CHECK/CHECK_/RETURN/TRAPS)."""
    return not (ch.isalnum() or ch == '_')
