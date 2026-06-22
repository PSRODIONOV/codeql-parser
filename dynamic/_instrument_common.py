"""Общие хелперы для instrument_c_make.py/instrument_cpp.py.

Оба скрипта инструментируют C/C++ исходники одинаковым текстовым способом
(вставка __TRACE/__TRACE_FN), и обнаруженные баги (см. ревью) повторялись
в обоих файлах один-в-один. Здесь — то, что реально общее, чтобы фикс
применялся один раз, а не дважды вручную.
"""
import re


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
    """Найти позицию первой "настоящей" '{' в строке — пропуская символьные
    /строковые литералы и однострочный комментарий (// ...). Используется
    как fallback при разрешении inline_candidate, когда { на заявленной
    CodeQL-позиции нет (см. probe_points.ql) — без пропуска литералов и
    комментариев самодостаточный макрос без единой настоящей { на строке
    (см. MAKE_ADDER/JAVA_INTEGER_OP) ложно находил бы '{' в соседнем
    комментарии вида "// см. Foo::bar() { ... }" и резолвился по ней вместо
    того, чтобы быть распознанным как "надёжного места нет" и пропущенным."""
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
    признак HotSpot-идиомы CHECK/CHECK_/RETURN/TRAPS (макрос — последний
    аргумент вызова, сам закрывающий список аргументов, см. ревью)."""
    return not (ch.isalnum() or ch == '_')
