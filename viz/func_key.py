"""func_key.py — уникальный ключ функции для словарей маршрутов/ветвей.

qualified_name НЕуникален: static-функции с одним именем в разных единицах
трансляции (типично для C) и перегрузки C++ (getQualifiedName без сигнатуры)
дают дубли. Если ключевать routes_by_func / branch_edges_by_func /
branch_inventory_by_func (и их копии в project.db, таблица derived_map) по
имени, данные «тёзок» перезаписывают друг друга и в Граф_ветвей/Перечень_ветвей
попадает только последняя функция.

Поэтому ключ — строка "<номер_ФО>|<имя>", где номер ФО — позиция функции в
Перечень_ФО (i+1 по func_data), уникален в пределах прогона. Разделитель «|»
безопасен: номер до ПЕРВОГО «|» — цифры, остаток — имя целиком (имена вроде
"Cls::operator||" не ломают разбор).

split_func_key терпим к старому формату (просто имя, без номера) — для чтения
derived_map из project.db, созданных прежними версиями: возвращает (0, имя).
"""
from typing import Tuple


def make_func_key(func_num: int, func_name: str) -> str:
    """Уникальный ключ функции: '<номер_ФО>|<имя>'."""
    return f"{func_num}|{func_name}"


def split_func_key(key: str) -> Tuple[int, str]:
    """Разбирает ключ на (номер_ФО, имя).

    Для legacy-ключей (просто имя, без 'номер|') возвращает (0, имя) —
    вызывающий код в этом случае ищет номер по func_index.
    """
    head, sep, name = str(key).partition("|")
    if sep and head.isdigit():
        return int(head), name
    return 0, str(key)
