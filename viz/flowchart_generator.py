from __future__ import annotations
import os
import re
import shutil
import zipfile
import hashlib
import json
import gc
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

from viz.func_key import make_func_key

# Deeply nested C++ functions (auto-generated code, macros) can exceed Python's
# default 1000-frame limit when _falls_through/_seq_falls_through alternate.
# 50000 handles ~25000 nesting levels — well beyond any real source code.
sys.setrecursionlimit(50000)


# ─── Process-pool: воркеры строят SVG в отдельных процессах (обход GIL) ──────────
# Состояние процесса-воркера (генератор + большие индексы) задаётся ОДИН раз в
# initializer и переиспользуется всеми задачами процесса — словари не пиклятся
# на каждую задачу.
_PP_STATE: Dict[str, Any] = {}


def _pp_init(spec: dict, func_index: dict, var_index: dict) -> None:
    """Инициализатор процесса-воркера: реконструирует генератор по spec."""
    import importlib, atexit
    mod = importlib.import_module(spec["module"])
    cls = getattr(mod, spec["qualname"])
    gen = cls(**spec["kwargs"])  # clear_output=False внутри kwargs
    _PP_STATE["gen"] = gen
    _PP_STATE["func_index"] = func_index
    _PP_STATE["var_index"] = var_index
    # Закрыть постоянный node-процесс при завершении воркера.
    _close = getattr(gen, "close_elk_servers", None)
    if callable(_close):
        atexit.register(_close)


def _pp_task(args: tuple):
    """Задача воркера: строит одну блок-схему, возвращает (имя_файла, cache_key)."""
    func_name, func_num, filt, cache_key = args
    gen = _PP_STATE["gen"]
    try:
        result = gen.generate(func_name, func_num, filt,
                              _PP_STATE["func_index"], _PP_STATE["var_index"])
        return (result, cache_key)
    except Exception as e:  # не роняем пул из-за одной функции
        return ("", cache_key)


# ─── Упрощённый режим блок-схем ──────────────────────────────────────────────
# Типы, которые получают фиксированную метку (вместо текста из кода).
_SIMPLIFIED_LABELS: Dict[str, str] = {
    "if":    "Условие",
    "for":   "Цикл",
    "while": "Цикл",
    "do":    "Цикл",
    "try":   "Обработка исключений",
    "return":   "Возврат",
    "break":    "Прерывание",
    "continue": "Продолжение",
    "throw":    "Исключение",
}

def _simplify_seq(nodes: list) -> list:
    """Упрощает список узлов иерархии блок-схемы:
    - типы из _SIMPLIFIED_LABELS получают фиксированную метку и сохраняются как есть;
    - всё остальное (call/io/process/expr/other/label/goto/exit и любые неизвестные)
      схлопывается в один узел «Базовый блок» (подряд идущие — в один).
    Рекурсивно применяется к дочерним узлам."""
    result: list = []
    last_bb = False
    for node in sorted(nodes, key=lambda n: n["line_start"]):
        st = node["stmt_type"]
        if st not in _SIMPLIFIED_LABELS:
            # Всё что не является узлом ветвления/возврата → Базовый блок
            if not last_bb:
                bb = dict(node)
                bb["stmt_type"]  = "other"
                bb["stmt_label"] = "Базовый блок"
                bb["children"]   = []
                bb["_simplified"] = True
                result.append(bb)
                last_bb = True
            # else: объединяем с предыдущим — ничего не добавляем
        else:
            simp = dict(node)
            simp["stmt_label"] = _SIMPLIFIED_LABELS[st]
            simp["_simplified"] = True
            if st == "if":
                else_line = node.get("else_line", 0)
                then_ch = [c for c in node["children"]
                           if not else_line or c["line_start"] < else_line]
                else_ch = [c for c in node["children"]
                           if else_line and c["line_start"] >= else_line]
                simp["children"] = _simplify_seq(then_ch) + _simplify_seq(else_ch)
            elif st == "try":
                try_ch   = [c for c in node["children"]
                            if not int(c.get("in_catch", 0) or 0)]
                catch_ch = [c for c in node["children"]
                            if int(c.get("in_catch", 0) or 0)]
                simp["children"] = _simplify_seq(try_ch) + _simplify_seq(catch_ch)
            else:
                simp["children"] = _simplify_seq(node.get("children", []))
            result.append(simp)
            last_bb = False
    return result


class FlowchartGenerator:
    """Базовый класс блок-схем: иерархия узлов, рендеринг рёбер (без Graphviz)."""

    def __init__(self, output_dir: str, db_path: str = None, clear_output: bool = True,
                 fold_guards: bool = False, loop_back_connectors: bool = True,
                 page_size: int = 60, frame_guards: bool = True,
                 simplified: bool = False):
        self.output_dir = Path(output_dir)
        # Сворачивать охранные if…return/goto в компактный узел (см. _render_node).
        self.fold_guards = fold_guards
        # Обводить охранные if…return пунктирной рамкой (ромб+действия+return).
        self.frame_guards = frame_guards
        # Обратные рёбра циклов (тело→заголовок, continue) рисовать соединителями
        # «↑N» вместо длинных восходящих линий — «шина возврата» (см. _render_node).
        self.loop_back_connectors = loop_back_connectors
        # Постраничная разбивка крупных схем: макс. узлов на страницу (0 = выкл.).
        # Стыки — межстраничный соединитель ГОСТ (пятиугольник).
        self.page_size = page_size
        # Очищаем каталог от схем предыдущих запусков: нумерация ФО может
        # отличаться, иначе старые файлы с другими номерами накапливаются.
        # clear_output=False — для воркеров process-pool: они пишут в ОБЩИЙ
        # каталог, очистку делает только главный процесс (иначе затрут друг друга).
        if clear_output and self.output_dir.exists():
            for old in self.output_dir.iterdir():
                if old.is_file():
                    try:
                        old.unlink()
                    except OSError:
                        pass
            # Кэш генерации сбрасываем вместе с файлами: SVG удалены, и записи
            # «функция уже отрисована» больше не соответствуют действительности
            # (иначе при повторном запуске закэшированные схемы не создавались).
            shutil.rmtree(self.output_dir / ".cache", ignore_errors=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Упрощённый режим: заменяет текст узлов на типовые метки и
        # схлопывает последовательные «обычные» операторы в «Базовый блок».
        self.simplified = simplified
        # Исходники берём из снимка внутри БД (src.zip), а не с диска —
        # отчёт строится строго по кодовой базе, без обращения к файлам проекта.
        self.db_path = Path(db_path) if db_path else None
        self._source_by_base: Dict[str, List[str]] = {}
        self._build_source_index()

    def _build_source_index(self) -> None:
        """Индексирует исходники из src.zip внутри CodeQL БД по базовому имени файла."""
        if not self.db_path:
            return
        src_zip = self.db_path / "src.zip"
        if not src_zip.exists():
            return
        try:
            with zipfile.ZipFile(src_zip) as z:
                for name in z.namelist():
                    if name.endswith("/"):
                        continue
                    base = name.replace("\\", "/").rsplit("/", 1)[-1]
                    if base in self._source_by_base:
                        continue  # при коллизии базовых имён оставляем первый
                    try:
                        text = z.read(name).decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                    self._source_by_base[base] = text.splitlines()
        except (zipfile.BadZipFile, OSError):
            pass

    # ─── Реконструкция в процессе-воркере (process-pool) ────────────────────
    def _worker_kwargs(self) -> dict:
        """Аргументы для пересоздания генератора в воркере (без очистки каталога)."""
        return {
            "output_dir": str(self.output_dir),
            "db_path": str(self.db_path) if self.db_path else None,
            "clear_output": False,
            "fold_guards": self.fold_guards,
            "loop_back_connectors": self.loop_back_connectors,
            "page_size": self.page_size,
            "frame_guards": self.frame_guards,
            "simplified": self.simplified,
        }

    def _worker_spec(self) -> dict:
        """Пиклимое описание генератора для initializer процесса-воркера."""
        return {
            "module": type(self).__module__,
            "qualname": type(self).__qualname__,
            "kwargs": self._worker_kwargs(),
        }

    @staticmethod
    def _clip(text: str, limit: int = 70) -> str:
        """Обрезает слишком длинную строку кода для метки узла."""
        text = " ".join(text.split())
        if len(text) > limit:
            return text[: limit - 3] + "..."
        return text

    @staticmethod
    def _id_prefix(ids) -> str:
        """Формирует префикс с номерами объектов по перечню, напр. '(4) ' или '(4,7) '."""
        ids = sorted(set(i for i in ids if i))
        if not ids:
            return ""
        return "(" + ",".join(str(i) for i in ids) + ") "

    @staticmethod
    def _is_io_line(src: str) -> bool:
        """Определяет, является ли строка исходного кода системной операцией ввода/вывода."""
        markers = (
            # C++ консольный/потоковый ввод-вывод
            "cout", "cin", "cerr", "clog",
            # C-стиль
            "printf", "scanf", "getline", "puts", "fgets", "fputs", "fprintf", "fscanf",
            # Java консольный ввод-вывод
            "System.out.print", "System.err.print", "System.in.",
            # JavaScript консольный ввод-вывод
            "console.log(", "console.error(", "console.warn(",
            "console.info(", "console.debug(",
            "process.stdout.write", "process.stdin.",
        )
        return any(m in src for m in markers)

    _THROW_RE = re.compile(r'^\s*throw\b')
    _EXIT_RE  = re.compile(r'\b(exit|_exit|_Exit|quick_exit|abort|std::exit|std::abort|std::terminate|std::quick_exit)\s*\(')

    @classmethod
    def _is_throw_line(cls, src: str) -> bool:
        return bool(cls._THROW_RE.match(src))

    @classmethod
    def _is_exit_line(cls, src: str) -> bool:
        return bool(cls._EXIT_RE.search(src))

    def _get_source_line(self, stmt_id: str) -> Optional[str]:
        """Возвращает строку исходника по stmt_id (файл:строка) из снимка БД."""
        if ":" not in stmt_id:
            return None
        parts = stmt_id.rsplit(":", 1)
        if len(parts) != 2:
            return None
        filename, line_str = parts
        try:
            line_num = int(line_str) - 1
        except ValueError:
            return None

        base = filename.replace("\\", "/").rsplit("/", 1)[-1]
        lines = self._source_by_base.get(base)
        if not lines:
            return None
        if 0 <= line_num < len(lines):
            return lines[line_num].strip()
        return None

    def _get_source_statement(self, stmt_id: str, max_lines: int = 6) -> Optional[str]:
        """Как _get_source_line, но дочитывает продолжение многострочного оператора.

        Если в первой строке скобки не сбалансированы (вызов/выражение перенесён
        на следующие строки), приклеивает последующие строки до баланса скобок
        либо до ';' — чтобы метка вызова не обрывалась на запятой посреди аргументов.
        """
        first = self._get_source_line(stmt_id)
        if first is None:
            return None
        if ":" not in stmt_id:
            return first
        filename, line_str = stmt_id.rsplit(":", 1)
        try:
            line_num = int(line_str) - 1
        except ValueError:
            return first
        base = filename.replace("\\", "/").rsplit("/", 1)[-1]
        lines = self._source_by_base.get(base)
        if not lines:
            return first

        result = first
        balance = first.count("(") - first.count(")")
        # Строка завершена, если скобки сбалансированы и есть ';' или '{'
        i = line_num + 1
        guard = 0
        while balance > 0 and ";" not in result and i < len(lines) and guard < max_lines:
            nxt = lines[i].strip()
            result = (result + " " + nxt).strip()
            balance += nxt.count("(") - nxt.count(")")
            i += 1
            guard += 1
        return result

    def _extract_condition_text(self, stmt_id: str, stmt_type: str, default_label: str) -> str:
        """Извлекает информативный текст условия из исходной строки.

        Поддерживает обе формы: со скобками (C/C++/Java/JS — `if (cond)`) и
        двоеточием (Python — `if cond:`). Без этого для Python условие падало в
        default_label (имя AST-класса, напр. "while (IntegerLiteral)").
        """
        # многострочные условия (вызовы в условии переносятся) дочитываем до баланса
        source = self._get_source_statement(stmt_id) or self._get_source_line(stmt_id)
        if not source:
            return default_label
        src = source.strip()

        def paren(kw):  # kw (...) — со СБАЛАНСИРОВАННЫМИ вложенными скобками
            m = re.search(rf'\b{kw}\s*\(', src)
            if not m:
                return None
            i = m.end() - 1  # позиция '('
            depth = 0
            for j in range(i, len(src)):
                if src[j] == '(':
                    depth += 1
                elif src[j] == ')':
                    depth -= 1
                    if depth == 0:
                        return src[i + 1:j].strip()
            return src[i + 1:].strip()  # скобки не закрылись — берём остаток

        def colon(kw):  # Python: kw cond:  (без скобок, до завершающего двоеточия)
            m = re.search(rf'\b{kw}\b\s*(.+?)\s*:\s*(#.*)?$', src)
            return m.group(1).strip() if m else None

        if stmt_type == "if":
            c = paren("if") or colon("if") or colon("elif")
            return f"if ({c})" if c else default_label

        elif stmt_type == "while":
            c = paren("while") or colon("while")
            return f"while ({c})" if c else default_label

        elif stmt_type == "for":
            if paren("for") is not None:
                return f"for ({paren('for')})"
            c = colon("for")  # Python: "for x in seq"
            return f"for ({c})" if c else default_label

        elif stmt_type == "do":
            c = paren("while")
            return f"do ... while ({c})" if c else default_label

        elif stmt_type == "return":
            # C/Java: `return expr;`  |  Python: `return expr` (без ;)
            m = re.search(r'\breturn\b\s*(.*?)\s*;', src) or re.search(r'\breturn\b\s*(.*)$', src)
            if m and m.group(1).strip():
                return f"return {m.group(1).strip()}"
            return "return"

        elif stmt_type == "try":
            return "try"

        elif stmt_type == "switch":
            c = paren("switch")
            return f"switch ({c})" if c else default_label

        return default_label

    @staticmethod
    def _remove_comments(label: str) -> str:
        """Удаляет C++ комментарии из label'а."""
        # Удаляем // комментарии
        label = re.sub(r'//.*$', '', label, flags=re.MULTILINE)
        # Удаляем /* */ комментарии
        label = re.sub(r'/\*.*?\*/', '', label, flags=re.DOTALL)
        return label.strip()

    def _format_label(self, label: str, func_index: Dict[str, int], var_index: Dict[str, int]) -> str:
        # Удаляем комментарии
        label = self._remove_comments(label)

        # Замена ТОЛЬКО по границам слова (\b): иначе короткое имя (напр. "t")
        # впечатывалось внутрь чужих слов — "IntegerLiteral" → "In(2177)tegerLi(2177)teral".
        def _annotate(text, name, num):
            if name not in text:
                return text
            return re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)',
                          lambda _m, n=num, nm=name: f"({n}){nm}", text)

        for fname, fnum in sorted(func_index.items(), key=lambda x: -len(x[0])):
            label = _annotate(label, fname, fnum)
        for vname, vnum in sorted(var_index.items(), key=lambda x: -len(x[0])):
            label = _annotate(label, vname, vnum)
        if len(label) > 60:
            label = label[:57] + "..."
        return label

    @staticmethod
    def _get_cache_key(func_name: str, func_num: int, stmts: List[Dict[str, Any]]) -> str:
        """Вычисляет хеш функции для кэширования.

        func_num входит в ключ: номер ФО — часть имени файла схемы, при смене
        нумерации (добавили/удалили функцию) старый кэш не должен совпадать.
        """
        data = f"{func_num}:{func_name}:{json.dumps(stmts, sort_keys=True)}"
        return hashlib.md5(data.encode()).hexdigest()

    def _build_hierarchy(self, stmts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Строит иерархию вложенности по диапазонам строк line_start..line_end."""
        sorted_stmts = sorted(
            stmts,
            key=lambda x: (int(x.get("line", x.get("line_start", "1"))), int(x.get("line_end", "9999")))
        )
        nodes = []
        for s in sorted_stmts:
            nodes.append({
                "stmt_id": s["stmt_id"],
                "line_start": int(s.get("line", s.get("line_start", "1"))),
                "line_end": int(s.get("line_end", s.get("line", "1"))),
                "stmt_type": s.get("stmt_type", "other"),
                "stmt_label": s.get("stmt_label", "..."),
                "branch_type": s.get("branch_type", ""),
                "else_line": int(s.get("else_line", "0") or 0),
                "branch_num": s.get("branch_num"),
                "callee_num":  s.get("callee_num"),
                "in_catch": int(s.get("in_catch", "0") or 0),
                "children": [],
                "parent": None,
            })

        # Для try-узлов: расширить line_end, чтобы включить операторы ИХ catch-блока.
        # Catch-узел относим к ближайшему предшествующему try по строке начала —
        # раньше каждый try растягивался до самого дальнего catch ВСЕЙ функции,
        # из-за чего при нескольких try ломалась иерархия вложенности.
        try_nodes = sorted((n for n in nodes if n["stmt_type"] == "try"),
                           key=lambda n: n["line_start"])
        if try_nodes:
            for c in nodes:
                if c.get("in_catch") != 1:
                    continue
                owner = None
                for t in try_nodes:
                    if t["line_start"] <= c["line_start"]:
                        owner = t
                    else:
                        break
                if owner is not None:
                    owner["line_end"] = max(owner["line_end"], c["line_end"])

        for i, child in enumerate(nodes):
            # else-ветви — не узлы блок-схемы (визуально часть if через else_line)
            if child["stmt_type"] == "else":
                continue
            best_parent = None
            for j in range(i - 1, -1, -1):
                candidate = nodes[j]
                if candidate["line_start"] <= child["line_start"] and candidate["line_end"] >= child["line_end"]:
                    if candidate["stmt_type"] in ("if", "while", "for", "do", "code", "try", "switch"):
                        if best_parent is None or candidate["line_start"] > best_parent["line_start"]:
                            best_parent = candidate
            if best_parent:
                child["parent"] = best_parent
                best_parent["children"].append(child)

        roots = [n for n in nodes if n["parent"] is None]
        return roots

    def _dot_id(self, func_name: str, stmt_id: str) -> str:
        raw = f"{func_name}_{stmt_id}"
        return raw.replace(":", "_").replace(".", "_").replace("~", "_").replace("-", "_")

    def _render_node(
        self,
        dot: graphviz.Digraph,
        node: Dict[str, Any],
        func_name: str,
        func_index: Dict[str, int],
        var_index: Dict[str, int],
        prev_node_holder: List[str],
        exit_node: str,
        next_sibling_id: str = None,
        loop_back_id: str = None,   # ID заголовка цикла — куда возвращается continue
        loop_exit_id: str = None,   # ID точки выхода из цикла — куда уходит break
        loop_marker: str = None,    # метка цикла «↑N» для соединителей возврата
    ):
        stmt_id = self._dot_id(func_name, node['stmt_id'])
        stmt_type = node["stmt_type"]
        raw_label = node["stmt_label"]

        if not node.get("_simplified") and stmt_type in ("if", "while", "for", "do", "return", "try", "switch"):
            raw_label = self._extract_condition_text(node['stmt_id'], stmt_type, raw_label)

        bnum = node.get("branch_num")
        if bnum and stmt_type in ("if", "while", "for", "do", "try"):
            raw_label = f"#{bnum}\n{raw_label}"

        children = node["children"]

        # Формы по ГОСТ 19.701-90
        if stmt_type in ("while", "for", "do"):
            node_shape = "hexagon"
            peripheries = "1"
        elif stmt_type in ("if", "try", "switch"):
            node_shape = "diamond"
            peripheries = "1"
        elif stmt_type == "call":
            node_shape = "box"
            peripheries = "2"  # предопределённый процесс
        elif stmt_type == "io":
            node_shape = "parallelogram"  # ввод/вывод
            peripheries = "1"
        elif stmt_type in ("process", "throw", "exit"):
            node_shape = "box"
            peripheries = "1"
        else:
            node_shape = "box"
            peripheries = "1"

        # Для call, io и process показываем строку кода как есть (без форматирования ИО)
        if node.get("_simplified") or stmt_type in ("call", "io", "process", "throw", "exit"):
            label = raw_label
        else:
            label = self._format_label(raw_label, func_index, var_index)

        # Сравниваем только ID, prev_node_holder хранит кортеж (id, type)
        prev_info = prev_node_holder[0]
        prev_id = prev_info[0] if isinstance(prev_info, tuple) else prev_info
        if prev_id and prev_id != stmt_id:
            kwargs = {}
            if isinstance(prev_info, tuple) and prev_info[1] in ("while", "for", "do"):
                kwargs["tailport"] = "e"
            dot.edge(prev_id, stmt_id, **kwargs)

        if stmt_type == "if":
            # Точное разбиение на ветки по строке начала else (из CodeQL):
            # операторы до else_line — ветка "да", начиная с else_line — ветка "нет".
            else_line = node.get("else_line", 0)
            then_children = []
            else_children = []
            for c in children:
                if else_line and c["line_start"] >= else_line:
                    else_children.append(c)
                else:
                    then_children.append(c)

            # ── Сворачивание охранной конструкции (guard clause) ──────────────
            # if без else, тело «да» завершается выходом (return/throw/exit/goto)
            # и не содержит вложенных ветвлений → рисуем ОДНИМ компактным узлом
            # «#N условие → выход» вместо ромба + ветки + терминатора. Резко
            # снижает число узлов/рёбер и пересечений на функциях с массой
            # проверок ошибок (nginx-стиль). ТОЛЬКО визуально: подсчёт ветвей и
            # маршрутов идёт по filtered/иерархии и не затрагивается.
            if getattr(self, "fold_guards", True) and then_children and not else_children:
                _ts = sorted(then_children, key=lambda c: c["line_start"])
                _exit = {"return", "throw", "exit", "goto"}
                _nested = {"if", "while", "for", "do", "try", "label"}
                if (_ts[-1]["stmt_type"] in _exit
                        and not any(c["stmt_type"] in _nested for c in _ts)):
                    exit_lbl = self._clip((_ts[-1].get("stmt_label") or _ts[-1]["stmt_type"]).strip())
                    dot.node(stmt_id, f"{label}\n→ {exit_lbl}",
                             shape="box", style="filled", fillcolor="#ffecec")
                    prev_node_holder[0] = (stmt_id, "guard")
                    return

            # ── Рамка охранника (пунктирный бокс) ─────────────────────────────
            # if без else, ветка «да» завершается выходом (return/throw/exit/goto)
            # и не ветвится → обводим ВЕСЬ охранник (ромб + действия + return)
            # пунктирной рамкой. Основной поток входит сверху, ветка «нет»
            # выходит снизу. Узлы помечаются группой; рамку рисует _render_svg.
            _frame_gid = None
            if (getattr(self, "frame_guards", True) and then_children and not else_children):
                _gt = sorted(then_children, key=lambda c: c["line_start"])
                if (_gt[-1]["stmt_type"] in ("return", "throw", "exit", "goto")
                        and not any(c["stmt_type"] in ("if", "while", "for", "do", "try", "label")
                                    for c in _gt)):
                    _frame_gid = f"g_{stmt_id}"
                    dot._group = _frame_gid

            dot.node(stmt_id, label, shape=node_shape)

            # «Охранный паттерн»: да-ветка состоит только из терминаторов (return/throw/exit)
            # и нет else-ветки → основной поток продолжается через «нет».
            # В этом случае направляем «нет» прямо вниз (s), а «да» — вбок (e),
            # чтобы главная ветка оставалась по центру.
            _terminal_types = {"return", "throw", "exit"}
            then_is_guard = (
                bool(then_children)
                and not else_children
                and all(c["stmt_type"] in _terminal_types for c in then_children)
            )
            true_port  = "e" if then_is_guard else "s"
            false_port = "s" if then_is_guard else "e"

            # Продолжение после if: следующий sibling-оператор, иначе возврат к
            # заголовку цикла, иначе выход. next_sibling приоритетнее loop_back:
            # ветка «нет» и хвост ветки «да» должны идти к СЛЕДУЮЩЕМУ оператору
            # последовательности, а не сразу к концу функции/заголовку цикла
            # (раньше нетерминальная ветка «да» уходила прямо в «Конец», минуя
            # последующие операторы).
            false_target = next_sibling_id or loop_back_id or exit_node

            # merge нужен только если есть else_children (нужно объединить ветки)
            need_merge = bool(else_children)
            merge_id = f"{stmt_id}_merge" if need_merge else None
            if need_merge:
                dot.node(merge_id, "", shape="point", width="0.1", height="0.1")

            # Куда продолжается ветка после своего тела — то же продолжение,
            # что и у ветки «нет».
            cont_target = false_target

            if then_children:
                then_sorted = sorted(then_children, key=lambda c: c["line_start"])
                then_first = self._dot_id(func_name, then_sorted[0]['stmt_id'])
                dot.edge(stmt_id, then_first, taillabel="да", tailport=true_port)
                prev_node_holder[0] = (then_first, then_sorted[0]["stmt_type"])
                for ci, c in enumerate(then_sorted):
                    nxt = (self._dot_id(func_name, then_sorted[ci + 1]["stmt_id"])
                           if ci + 1 < len(then_sorted) else None)
                    self._render_node(dot, c, func_name, func_index, var_index, prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)
                prev_info = prev_node_holder[0]
                prev_id = prev_info[0] if isinstance(prev_info, tuple) else prev_info
                if need_merge and prev_id:
                    dot.edge(prev_id, merge_id)
                elif prev_id and prev_id not in (exit_node, "end", cont_target):
                    if loop_back_id and cont_target == loop_back_id:
                        dot.edge(prev_id, cont_target, tailport="w", headport="w")
                    else:
                        dot.edge(prev_id, cont_target)
            else:
                dot.edge(stmt_id, false_target, taillabel="да", tailport=true_port)

            if else_children:
                else_sorted = sorted(else_children, key=lambda c: c["line_start"])
                else_first = self._dot_id(func_name, else_sorted[0]['stmt_id'])
                dot.edge(stmt_id, else_first, taillabel="нет", tailport=false_port)
                prev_node_holder[0] = (else_first, else_sorted[0]["stmt_type"])
                for ci, c in enumerate(else_sorted):
                    nxt = (self._dot_id(func_name, else_sorted[ci + 1]["stmt_id"])
                           if ci + 1 < len(else_sorted) else None)
                    self._render_node(dot, c, func_name, func_index, var_index, prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)
                prev_info = prev_node_holder[0]
                prev_id = prev_info[0] if isinstance(prev_info, tuple) else prev_info
                if need_merge and prev_id:
                    dot.edge(prev_id, merge_id)
                elif prev_id and prev_id not in (exit_node, "end", cont_target):
                    if loop_back_id and cont_target == loop_back_id:
                        dot.edge(prev_id, cont_target, tailport="w", headport="w")
                    else:
                        dot.edge(prev_id, cont_target)
                prev_node_holder[0] = (merge_id, "merge")
            else:
                if loop_back_id and false_target == loop_back_id:
                    dot.edge(stmt_id, false_target, taillabel="нет", tailport="w", headport="w")
                else:
                    dot.edge(stmt_id, false_target, taillabel="нет", tailport=false_port)
                prev_node_holder[0] = (false_target, "exit" if false_target == exit_node else "next")

            if _frame_gid:
                dot._group = None  # закрываем группу охранника

        elif stmt_type == "try":
            dot.node(stmt_id, label, shape=node_shape)

            # Разделяем children на try и catch части используя поле in_catch (задано в function_flow_v2.ql)
            try_ch = sorted([c for c in children if not int(c.get("in_catch", "0") or 0)],
                            key=lambda c: c["line_start"])
            catch_ch = sorted([c for c in children if int(c.get("in_catch", "0") or 0)],
                              key=lambda c: c["line_start"])
            # Продолжение после try: следующий sibling, иначе цикл/выход.
            cont_target = next_sibling_id or loop_back_id or exit_node

            # Render try body — запоминаем последний живой узел
            try_tail = None
            if try_ch:
                try_first = self._dot_id(func_name, try_ch[0]['stmt_id'])
                dot.edge(stmt_id, try_first, taillabel="нет исключения", tailport="s")
                prev_node_holder[0] = (try_first, try_ch[0]["stmt_type"])
                for ci, c in enumerate(try_ch):
                    nxt = (self._dot_id(func_name, try_ch[ci + 1]["stmt_id"])
                           if ci + 1 < len(try_ch) else None)
                    self._render_node(dot, c, func_name, func_index, var_index,
                                      prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)
                pi = prev_node_holder[0]
                if pi is not None:
                    try_tail = pi[0] if isinstance(pi, tuple) else pi
            else:
                dot.edge(stmt_id, cont_target, taillabel="нет исключения", tailport="s")

            # Render catch body — запоминаем последний живой узел
            catch_tail = None
            if catch_ch:
                catch_first = self._dot_id(func_name, catch_ch[0]['stmt_id'])
                dot.edge(stmt_id, catch_first, taillabel="catch", tailport="e")
                prev_node_holder[0] = (catch_first, catch_ch[0]["stmt_type"])
                for ci, c in enumerate(catch_ch):
                    nxt = (self._dot_id(func_name, catch_ch[ci + 1]["stmt_id"])
                           if ci + 1 < len(catch_ch) else None)
                    self._render_node(dot, c, func_name, func_index, var_index,
                                      prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)
                pi = prev_node_holder[0]
                if pi is not None:
                    catch_tail = pi[0] if isinstance(pi, tuple) else pi
            else:
                dot.edge(stmt_id, cont_target, taillabel="catch", tailport="e")

            # Merge-точка только если хотя бы одна ветвь не завершается (return/throw)
            if try_tail or catch_tail:
                merge_id = f"{stmt_id}_merge"
                dot.node(merge_id, "", shape="point", width="0.1", height="0.1")
                if try_tail:
                    dot.edge(try_tail, merge_id)
                if catch_tail:
                    dot.edge(catch_tail, merge_id)
                prev_node_holder[0] = (merge_id, "merge")
            else:
                # Обе ветви завершились (return/throw) — продолжения нет
                prev_node_holder[0] = None

        elif stmt_type == "switch":
            dot.node(stmt_id, label, shape=node_shape)

            # case/default — НЕ узлы (метки границ, см. _build_hierarchy),
            # остальные children — реальные операторы тела switch. Разбиваем
            # на N групп по позиции каждой метки (case_markers), как if делит
            # children на then/else по else_line, но для N веток сразу.
            case_markers = sorted(
                [c for c in children if c["stmt_type"] in ("case", "default")],
                key=lambda c: c["line_start"])
            real_children = [c for c in children if c["stmt_type"] not in ("case", "default")]
            cont_target = next_sibling_id or loop_back_id or exit_node
            merge_id = f"{stmt_id}_merge"

            def _mk_groups():
                groups = []
                for gi, marker in enumerate(case_markers):
                    lo = marker["line_start"]
                    hi = (case_markers[gi + 1]["line_start"] if gi + 1 < len(case_markers)
                          else node["line_end"] + 1)
                    groups.append(sorted(
                        [c for c in real_children if lo <= c["line_start"] < hi],
                        key=lambda c: c["line_start"]))
                return groups

            groups = _mk_groups()

            # Куда ведёт ребро СО switch ДЛЯ метки i: первый узел её группы,
            # либо (пустая case — чистый fallthrough без своего тела, напр.
            # 'case 1: case 2: foo();') — куда ведёт СЛЕДУЮЩАЯ метка, и так
            # цепочкой до первой непустой группы или до merge, если непустых
            # групп после i не осталось вовсе.
            def _entry_dest(i):
                while i < len(groups):
                    if groups[i]:
                        return self._dot_id(func_name, groups[i][0]["stmt_id"])
                    i += 1
                return merge_id

            if not case_markers:
                # switch без единой case/default (синтаксически валидно, но
                # бессмысленно) — ведём прямо в продолжение.
                dot.edge(stmt_id, cont_target)
                prev_node_holder[0] = (cont_target, "next")
            else:
                # merge создаём сразу и безусловно (а не "только если нужен",
                # как у if/try) — у switch источником входа в merge может
                # быть И обычный fallthrough-хвост последней группы (виден
                # отсюда), И внутренний break (рисует ребро САМ, через
                # loop_exit_id=merge_id — отсюда не виден). Точно понять,
                # остался ли merge недостижим, без отдельного прохода по
                # дереву на наличие break — сложнее и более ломко, чем
                # принять, что один висячий узел-точка без входящих рёбер
                # (когда вообще все ветви — return/throw без единого break)
                # не искажает схему.
                dot.node(merge_id, "", shape="point", width="0.1", height="0.1")
                for i, marker in enumerate(case_markers):
                    case_lbl = self._clip(marker.get("stmt_label") or marker["stmt_type"])
                    dest = _entry_dest(i)
                    dot.edge(stmt_id, dest, taillabel=case_lbl)
                    grp = groups[i]
                    if not grp:
                        continue  # пустая (чистый fallthrough) — своих узлов не рисуем
                    # break внутри тела case выходит из SWITCH (не из внешнего
                    # цикла) — переопределяем loop_exit_id на merge_id ТОЛЬКО
                    # для прямых детей этой группы; continue/вложенные циклы
                    # сами переопределят его дальше, как и раньше (см. break).
                    prev_node_holder[0] = (self._dot_id(func_name, grp[0]["stmt_id"]), grp[0]["stmt_type"])
                    for ci, c in enumerate(grp):
                        nxt = (self._dot_id(func_name, grp[ci + 1]["stmt_id"])
                               if ci + 1 < len(grp) else None)
                        self._render_node(dot, c, func_name, func_index, var_index,
                                          prev_node_holder, exit_node, nxt,
                                          loop_back_id, merge_id, loop_marker)
                    prev_info = prev_node_holder[0]
                    prev_id = prev_info[0] if isinstance(prev_info, tuple) else prev_info
                    if prev_id:
                        # Хвост группы не завершён (нет break/return/...) —
                        # реальный fallthrough в СЛЕДУЮЩУЮ метку (или merge,
                        # если это последняя case) — именно ТУДА, а не в
                        # cont_target, чтобы визуально показать проваливание
                        # в код следующего case, как и выполняется в C/C++.
                        nxt_dest = _entry_dest(i + 1)
                        if prev_id not in (exit_node, "end", nxt_dest):
                            dot.edge(prev_id, nxt_dest)
                dot.edge(merge_id, cont_target)
                prev_node_holder[0] = (merge_id, "merge")

        elif stmt_type in ("while", "for", "do"):
            dot.node(stmt_id, label, shape=node_shape)

            # Точка выхода цикла: сюда идёт нормальный выход (условие ложно) и
            # все break изнутри цикла. После неё продолжается код после цикла.
            loop_exit = f"{stmt_id}_exit"
            dot.node(loop_exit, "", shape="point", width="0.1", height="0.1")

            # «Шина возврата» — АДАПТИВНО: короткие циклы рисуем обычной обратной
            # стрелкой к ЛЕВОЙ боковой вершине заголовка (привычно и наглядно);
            # длинные/вложенные — соединителями «↑N» (как goto), без длинных
            # восходящих линий, дающих пересечения.
            body_children = children

            def _cnt(nodes):
                return sum(1 + _cnt(x.get("children", [])) for x in nodes)

            use_conn = (getattr(self, "loop_back_connectors", True)
                        and _cnt(body_children) > 6)
            marker = f"↑{bnum}" if (use_conn and bnum) else None
            if use_conn:
                loopin = f"{stmt_id}_loopin"
                dot.node(loopin, f"↑{bnum}" if bnum else "↑", shape="circle",
                         style="filled", fillcolor="#e1f5fe")
                # приёмник входит в ЛЕВУЮ боковую вершину заголовка
                dot.edge(loopin, stmt_id, tailport="w", headport="w")

            if body_children:
                body_sorted = sorted(body_children, key=lambda c: c["line_start"])
                body_first = self._dot_id(func_name, body_sorted[0]['stmt_id'])
                dot.edge(stmt_id, body_first, taillabel="да")

                prev_node_holder[0] = (body_first, body_sorted[0]["stmt_type"])
                for ci, c in enumerate(body_sorted):
                    # Вложенным узлам: continue→соединитель «↑N» (loop_marker),
                    # break→loop_exit(точка выхода ИМЕННО этого цикла),
                    # next_sibling — следующий оператор тела цикла.
                    nxt = (self._dot_id(func_name, body_sorted[ci + 1]["stmt_id"])
                           if ci + 1 < len(body_sorted) else None)
                    self._render_node(dot, c, func_name, func_index, var_index,
                                      prev_node_holder, exit_node, nxt, stmt_id, loop_exit, marker)

                # Возврат из тела цикла: соединитель «↑N» (без длинной линии) или,
                # если шина отключена, обычное обратное ребро в заголовок.
                prev_info = prev_node_holder[0]
                prev_id = prev_info[0] if isinstance(prev_info, tuple) else prev_info
                if prev_id and prev_id != stmt_id:
                    if use_conn:
                        bk = f"{prev_id}__bk_{stmt_id}"
                        dot.node(bk, marker, shape="circle", style="filled", fillcolor="#e1f5fe")
                        dot.edge(prev_id, bk)
                    else:
                        dot.edge(prev_id, stmt_id, tailport="w", headport="w")

            else:
                # Нет видимых узлов в теле цикла — заглушка с возвратом.
                # В упрощённом режиме показываем «Базовый блок» (как прочие
                # неветвящиеся узлы), в полном — «(КОД)».
                code_id = f"{stmt_id}_code"
                dot.node(code_id, "Базовый блок" if self.simplified else "(КОД)", shape="box")
                dot.edge(stmt_id, code_id, label="да")
                if use_conn:
                    bk = f"{code_id}__bk_{stmt_id}"
                    dot.node(bk, marker, shape="circle", style="filled", fillcolor="#e1f5fe")
                    dot.edge(code_id, bk)
                else:
                    dot.edge(code_id, stmt_id, tailport="w", headport="w")

            # Нормальный выход из цикла (условие ложно) — вбок (EAST) в точку выхода.
            dot.edge(stmt_id, loop_exit, tailport="e")
            prev_node_holder[0] = (loop_exit, "merge")

        elif stmt_type == "return":
            # ГОСТ 19.701-90 допускает НЕСКОЛЬКО терминаторов «Конец». Делаем
            # каждый return самостоятельным концом пути (скруглённый узел) — не
            # сводим десятки return в один узел длинными сходящимися рёбрами
            # (это главный источник пересечений на больших ФО).
            dot.node(stmt_id, label, shape="box", style="rounded,filled", fillcolor="#e8e8e8")
            prev_node_holder[0] = None

        elif stmt_type == "throw":
            # throw — аварийный выход через исключение; самостоятельный терминатор.
            dot.node(stmt_id, label, shape="box", style="rounded,filled", fillcolor="#ffcccc")
            prev_node_holder[0] = None

        elif stmt_type == "exit":
            # exit/abort — программный выход; самостоятельный терминатор.
            dot.node(stmt_id, label, shape="box", style="rounded,filled", fillcolor="#ffe0b2")
            prev_node_holder[0] = None

        elif stmt_type == "continue":
            # continue — возврат к заголовку цикла. При включённой «шине возврата»
            # рисуем соединителем «continue ↑N» (без длинной восходящей линии);
            # иначе — обычным обратным ребром к заголовку.
            if getattr(self, "loop_back_connectors", True) and loop_marker:
                dot.node(stmt_id, f"continue {loop_marker}", shape="circle",
                         style="filled", fillcolor="#e1f5fe")
            else:
                dot.node(stmt_id, label, shape="box", style="filled", fillcolor="#e1f5fe")
                target = loop_back_id if loop_back_id else exit_node
                dot.edge(stmt_id, target, tailport="w", headport="w")
            prev_node_holder[0] = None  # путь завершён (управление ушло на цикл)

        elif stmt_type == "break":
            # break — выход из ЦИКЛА: управление идёт на код ПОСЛЕ цикла
            # (точка выхода цикла loop_exit_id), а не к выходу функции.
            dot.node(stmt_id, label, shape="box", style="filled", fillcolor="#fff9c4")
            target = loop_exit_id if loop_exit_id else exit_node
            dot.edge(stmt_id, target)
            prev_node_holder[0] = None  # путь завершён (вышли из цикла)

        elif stmt_type == "goto":
            # Соединитель ГОСТ 19.701: безусловный переход к одноимённой метке.
            # Рисуем кружком с именем метки (без длинного ребра-прыжка через всю
            # схему) — приёмник помечен таким же кружком (узел label).
            name = raw_label[5:].strip() if raw_label.startswith("goto ") else raw_label
            dot.node(stmt_id, name, shape="circle", style="filled", fillcolor="#fff3e0")
            prev_node_holder[0] = None  # безусловный переход — путь завершён

        elif stmt_type == "label":
            # Соединитель-приёмник ГОСТ: точка назначения goto; поток идёт дальше.
            dot.node(stmt_id, raw_label, shape="circle", style="filled", fillcolor="#fff3e0")
            prev_node_holder[0] = (stmt_id, "label")

        elif stmt_type == "call":
            dot.node(stmt_id, label, shape="box", peripheries="2")
            prev_node_holder[0] = (stmt_id, stmt_type)

            if children:
                children_sorted = sorted(children, key=lambda c: c["line_start"])
                for ci, c in enumerate(children_sorted):
                    nxt = (self._dot_id(func_name, children_sorted[ci + 1]["stmt_id"])
                           if ci + 1 < len(children_sorted) else None)
                    self._render_node(dot, c, func_name, func_index, var_index, prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)

        elif stmt_type == "code":
            # Узел "Код" для пустого тела цикла
            dot.node(stmt_id, label, shape="box")
            prev_node_holder[0] = (stmt_id, stmt_type)

        else:
            dot.node(stmt_id, label, shape=node_shape)
            prev_node_holder[0] = (stmt_id, stmt_type)

            if children:
                children_sorted = sorted(children, key=lambda c: c["line_start"])
                for ci, c in enumerate(children_sorted):
                    nxt = (self._dot_id(func_name, children_sorted[ci + 1]["stmt_id"])
                           if ci + 1 < len(children_sorted) else None)
                    self._render_node(dot, c, func_name, func_index, var_index, prev_node_holder, exit_node, nxt, loop_back_id, loop_exit_id, loop_marker)

    def generate(self, func_name: str, func_num: int,
                 stmts: List[Dict[str, str]],
                 func_index: Dict[str, int], var_index: Dict[str, int]) -> str:
        raise NotImplementedError("Use ELKFlowchartGenerator")

    # ── Маршруты выполнения ───────────────────────────────────────────────────


    @staticmethod
    def _decision_outcomes(node) -> "Optional[tuple]":
        """Ключ решения и его два исхода, либо None для не-ветвлений."""
        st = node["stmt_type"]; b = node.get("branch_num")
        if st == "if":
            return (st, b), ("да", "нет")
        if st in ("for", "while", "do"):
            return (st, b), ("да", "нет")
        if st == "try":
            return (st, b), ("нет исключения", "catch")
        return None

    def _arms(self, node):
        """Возвращает [(outcome, children_arm), …] для ветвления."""
        st = node["stmt_type"]; b = node.get("branch_num"); ch = node["children"]
        if st == "if":
            el = node.get("else_line", 0)
            then_ch = sorted([c for c in ch if not el or c["line_start"] < el],
                             key=lambda x: x["line_start"])
            else_ch = sorted([c for c in ch if el and c["line_start"] >= el],
                             key=lambda x: x["line_start"])
            return [("да", then_ch), ("нет", else_ch)]
        if st == "try":
            try_ch = sorted([c for c in ch if not int(c.get("in_catch", 0) or 0)],
                            key=lambda x: x["line_start"])
            catch_ch = sorted([c for c in ch if int(c.get("in_catch", 0) or 0)],
                              key=lambda x: x["line_start"])
            return [("нет исключения", try_ch), ("catch", catch_ch)]
        # for/while/do: "да" — вход в тело (один раз), "нет" — пропуск
        body = sorted(ch, key=lambda x: x["line_start"])
        return [("да", body), ("нет", [])]

    _TERMINATORS = ("return", "throw", "exit", "break", "continue", "goto")

    def _build_subtree_ids(self, roots: list) -> dict:
        """id(node) → множество id всех узлов его поддерева (для проверки
        «цель внутри данной ветви»). Один проход, память линейна."""
        m: dict = {}

        def rec(n):
            s = {id(n)}
            for c in n.get("children", []):
                s |= rec(c)
            m[id(n)] = s
            return s

        for r in roots:
            rec(r)
        return m

    def _falls_through(self, node, memo: dict) -> bool:
        """Может ли управление после выполнения node перейти к следующему
        оператору (нет безусловного выхода return/break/...)."""
        nid = id(node)
        if nid in memo:
            return memo[nid]
        # Optimistic sentinel before recursion — breaks cycles in malformed AST data
        # and prevents unbounded re-entry if a node is reached via multiple paths.
        memo[nid] = True
        st = node["stmt_type"]
        if st in self._TERMINATORS:
            memo[nid] = False
            return False
        d = self._decision_outcomes(node)
        if d:
            # ветвление «проваливается», если ХОТЯ БЫ одна ветвь доходит до конца
            res = any(self._seq_falls_through(arm, memo) for _, arm in self._arms(node))
            memo[nid] = res
            return res
        # memo[nid] already True
        return True

    def _seq_falls_through(self, nodes: list, memo: dict) -> bool:
        """Доходит ли последовательность операторов до конца (без выхода)."""
        for n in nodes:
            if not self._falls_through(n, memo):
                return False
        return True

    def _enumerate_routes(self, roots: list, func_num: int, max_routes: int = 1000) -> List[Dict]:
        """Базисный набор маршрутов выполнения ФО, покрывающий КАЖДУЮ ветвь.

        Вместо экспоненциального перечисления ВСЕХ путей (2^N — неперечислимо и
        не требуется РД НДВ №114) для каждого ещё не покрытого исхода ветвления
        строится ОДИН маршрут, ведущий к этому ветвлению и берущий нужный исход;
        попутно маршрут покрывает другие исходы. Размер набора ≈ цикломатической
        сложности V(G) = (число ветвлений)+1. Сложность полиномиальная — без
        экспоненты и OOM (каждый маршрут — один проход по дереву).
        """
        sub_ids = self._build_subtree_ids(roots)
        ft_memo: dict = {}

        # Все исходы ветвлений в порядке обхода (цели для покрытия)
        decisions: list = []   # (node, key, outcome)

        def collect(nodes):
            for n in nodes:
                d = self._decision_outcomes(n)
                if d:
                    key, outs = d
                    decisions.append((n, key, outs[0]))
                    decisions.append((n, key, outs[1]))
                collect(n.get("children", []))
        collect(roots)

        covered: set = set()
        seen: set = set()
        result: list = []

        def commit(conds, calls):
            s = self._route_str(conds)
            if s in seen:
                return
            seen.add(s)
            result.append({
                "route_num": len(result) + 1, "route_str": s,
                "conds": list(conds), "calls": list(calls),
            })

        def build_path(target_id, target_out):
            """Один проход root→терминатор. К целевому ветвлению (target_id) ведём
            и берём target_out; на ПРОЧИХ ветвлениях — фиксированный БАЗОВЫЙ выбор
            (первая «проваливающаяся» ветвь). Так каждый маршрут отличается от
            базового ровно одним ветвлением → набор цикломатически независим (V(G))."""
            conds: list = []
            calls: list = [func_num]
            nodes = list(roots)
            guard = 0
            while nodes and guard < 100000:
                guard += 1
                node = nodes[0]; rest = nodes[1:]
                d = self._decision_outcomes(node)
                if d:
                    key, _ = d
                    arms = self._arms(node)
                    if id(node) == target_id:
                        chosen = next(a for a in arms if a[0] == target_out)
                    else:
                        chosen = None
                        for a in arms:  # цель внутри ветви? — идём туда
                            if any(target_id in sub_ids.get(id(c), ()) or id(c) == target_id
                                   for c in a[1]):
                                chosen = a; break
                        if chosen is None:
                            # базовый выбор: первая ветвь, доходящая до конца
                            ft = [a for a in arms if self._seq_falls_through(a[1], ft_memo)]
                            chosen = (ft or arms)[0]
                    conds.append((key[0], key[1], chosen[0]))
                    covered.add((key, chosen[0]))
                    nodes = chosen[1] + rest
                    continue
                st = node["stmt_type"]
                if st == "call":
                    c = node.get("callee_num")
                    if c:
                        calls.append(c)
                    nodes = rest
                elif st in self._TERMINATORS:
                    break
                else:
                    nodes = rest
            return conds, calls

        # 1) Базовый маршрут (все ветвления — по базовому выбору).
        conds, calls = build_path(None, None)
        commit(conds, calls)

        # 2) По одному маршруту на каждый ещё не покрытый исход ветвления
        #    (базовый путь с «переключением» ровно этого ветвления) → базис V(G).
        for node, key, out in decisions:
            if len(result) >= max_routes:
                break
            if (key, out) in covered:
                continue
            conds, calls = build_path(id(node), out)
            commit(conds, calls)

        if not result:  # функция без ветвлений
            commit([], [func_num])
        return result

    def _branch_transitions(self, roots: list) -> List[Dict[str, str]]:
        """Полный граф переходов между ветками функции — структурно, без перечисления путей.

        В отличие от извлечения переходов из маршрутов (которые ограничены кэпом и
        для функций с экспоненциальным ветвлением теряют часть веток), здесь
        переходы вычисляются прямо по иерархии методом передачи вперёд множества
        «первых достижимых веток» (continuation-passing). Сложность полиномиальная,
        покрытие — полное (все ветки и переходы, как на блок-схеме).

        Возвращает список рёбер {from_branch, to_branch, transition_type, contains_call}.
        """
        edges = set()  # множество (from, to)

        def outcomes(node):
            st = node["stmt_type"]; b = node.get("branch_num")
            if st == "if":
                return (f"if#{b}-да", f"if#{b}-нет")
            if st in ("for", "while", "do"):
                return (f"{st}#{b}-да", f"{st}#{b}-нет")
            if st == "try":
                return (f"try#{b}-нет исключения", f"try#{b}-catch")
            return None

        def split_children(node):
            st = node["stmt_type"]; ch = node["children"]
            if st == "if":
                el = node.get("else_line", 0)
                then_ch = sorted([c for c in ch if not el or c["line_start"] < el],
                                 key=lambda x: x["line_start"])
                else_ch = sorted([c for c in ch if el and c["line_start"] >= el],
                                 key=lambda x: x["line_start"])
                return then_ch, else_ch
            if st == "try":
                try_ch = sorted([c for c in ch if not int(c.get("in_catch", 0) or 0)],
                                key=lambda x: x["line_start"])
                catch_ch = sorted([c for c in ch if int(c.get("in_catch", 0) or 0)],
                                  key=lambda x: x["line_start"])
                return try_ch, catch_ch
            return sorted(ch, key=lambda x: x["line_start"]), None

        # flow(nodes, after): множество веток (или "return"), первыми достижимых
        # при выполнении nodes с продолжением after. Список обходится ИТЕРАТИВНО
        # справа налево (rf = firsts уже обработанного хвоста), рекурсия — только
        # вглубь дочерних поддеревьев (глубина = уровень вложенности, мал).
        # Каждый узел обрабатывается один раз → линейная сложность, без кэпа.
        def flow(nodes, after):
            firsts = after
            for node in reversed(nodes):
                st = node["stmt_type"]
                oc = outcomes(node)
                rf = firsts  # продолжение после текущего узла = firsts хвоста
                if st in ("return", "throw", "exit"):
                    firsts = frozenset({"return"})
                elif oc is None:
                    firsts = rf  # вызовы/код — прозрачны для веток
                elif st in ("if", "try"):
                    a_ch, b_ch = split_children(node)
                    a_f = flow(a_ch, rf)
                    b_f = flow(b_ch, rf)
                    for t in a_f: edges.add((oc[0], t))
                    for t in b_f: edges.add((oc[1], t))
                    firsts = frozenset({oc[0], oc[1]})
                else:  # цикл for/while/do: вход (тело→продолжение) или пропуск
                    body, _ = split_children(node)
                    body_f = flow(body, rf)
                    for t in body_f: edges.add((oc[0], t))
                    for t in rf: edges.add((oc[1], t))
                    firsts = frozenset({oc[0], oc[1]})
            return firsts

        firsts = flow(roots, frozenset({"return"}))
        for t in firsts:
            edges.add(("entry", t))

        out = []
        for frm, to in edges:
            if frm == "entry" and to == "return":
                ttype = "прямой"
            elif to == "return":
                ttype = "возврат"
            elif frm == "entry":
                ttype = "ветвление"
            else:
                ttype = "условный"
            out.append({"from_branch": frm, "to_branch": to,
                        "transition_type": ttype, "contains_call": ""})
        return out

    @staticmethod
    def _route_str(conditions: list) -> str:
        if not conditions:
            return "Начало->Конец"
        s = "Начало->"
        for stype, num, outcome in conditions:
            s += f"{stype} #{num} -{outcome}->"
        s += "Конец"
        return s

    def generate_all(
        self,
        func_data: List[Dict[str, str]],
        flow_data: List[Dict[str, str]],
        info_data: List[Dict[str, str]],
        control_data: List[Dict[str, str]],
        data_data: List[Dict[str, str]] = None,
        file_flow_data: List[Dict[str, str]] = None,
        route_writer=None,
        load_by_demand: bool = False,
        build_flowcharts: bool = True,
        need_routes_in_memory: bool = True,
        max_routes: int = 1000,
        progress: "Optional[callable]" = None,
        workers: int = 0,
        log: "Optional[callable]" = None,
    ):
        """Строит блок-схемы для всех ФО и возвращает (generated_files, routes_by_func).

        progress(label, cur, total) и log(msg) — необязательные колбэки. Работа
        идёт двумя секциями (каждая со своей полосой прогресса и строкой итога):
        сначала «[БЛОК-СХЕМЫ] Генерация блок-схем (ФО)» (рендер SVG), затем
        «[МАРШРУТЫ] Формирование маршрутов (ФО)» (базисные маршруты + ветви).

        Args:
            build_flowcharts: если False, генерирует только routes_by_func без создания файлов блок-схем (для графов)
            need_routes_in_memory: если True, накапливает routes_by_func для Граф_ветвей/Граф_маршрутов
                (нужно даже при активном route_writer — иначе графы выходят пустыми)
            max_routes: максимум маршрутов, перечисляемых для одного ФО (защита от
                экспоненциального взрыва путей на функциях с глубокой вложенностью)
        """
        print(f"[DEBUG:generate_all] load_by_demand={load_by_demand}", flush=True)
        print(f"[DEBUG:generate_all] Начало подготовки данных", flush=True)

        # Группируем данные по функции ОДИН раз за O(N). Это даёт ту же память,
        # что и исходные списки (словари хранят ссылки на те же объекты), но
        # избавляет от O(N×M) линейного скана всех данных для каждой функции.
        # Прежний режим load_by_demand сканировал data_data (десятки тысяч строк)
        # заново на каждой из тысяч функций — отсюда катастрофическая медлительность.
        print(f"[DEBUG:generate_all] Группировка данных по функциям (один проход)...", flush=True)
        # Операторы группируем по (имя, файл): одноимённые функции (static в
        # разных единицах трансляции, перегрузки C++) не должны сливать свои
        # операторы в одно «тело» — иначе блок-схемы и маршруты строятся по
        # объединению разных функций. stmts_by_name — fallback для данных без
        # func_file (старые project.db, где колонка не сохранялась).
        stmts_by_func = defaultdict(list)
        stmts_by_name = defaultdict(list)
        for item in flow_data:
            stmts_by_func[(item["func_name"], item.get("func_file", ""))].append(item)
            stmts_by_name[item["func_name"]].append(item)

        # Вызовы группируем по (имя, файл объявления вызывающего) — caller_file
        # в control_matrix.ql берётся тем же API, что `file` в functional_objects.
        # calls_by_name — fallback по имени (старые данные).
        calls_by_func = defaultdict(list)
        calls_by_name = defaultdict(list)
        for item in control_data:
            calls_by_func[(item["caller_name"], item.get("caller_file", ""))].append(item)
            calls_by_name[item["caller_name"]].append(item)

        # Доступы к информационным объектам (переменным) по функциям
        accesses_by_func = defaultdict(list)
        if data_data:
            for item in data_data:
                accesses_by_func[item.get("function_name", "")].append(item)
        print(f"[DEBUG:generate_all] Группировка готова: stmts={len(stmts_by_func)} "
              f"calls={len(calls_by_func)} accesses={len(accesses_by_func)} функций", flush=True)

        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data)}
        # Точный номер ФО по (имя, файл объявления) — различает одноимённые
        # функции; func_index по имени остаётся fallback'ом для меток.
        num_by_name_file = {(item["qualified_name"], item.get("file", "")): i + 1
                            for i, item in enumerate(func_data)}
        # Нумерация ИО совпадает с Перечень_ИО.csv: параметры не нумеруются.
        _info_no_params = [it for it in info_data if it.get("kind") != "parameter"]
        var_index: Dict[str, int] = {item["qualified_name"]: i + 1
                                     for i, item in enumerate(_info_no_params)}
        # Файловые ИО нумеруются после переменных (как в report_generator)
        if file_flow_data:
            _base = len(_info_no_params)
            _seen_files: Dict[str, int] = {}
            for _ff in file_flow_data:
                _fn = _ff.get("file_name", "")
                if _fn and _fn not in _seen_files:
                    _seen_files[_fn] = _base + len(_seen_files) + 1
            var_index.update(_seen_files)

        # Файловые ИО по функциям (из file_flow_data) — для секции F
        file_io_by_func: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        if file_flow_data:
            for _ff in file_flow_data:
                file_io_by_func[_ff.get("function_name", "")].append(_ff)

        # Создаём индекс локальных переменных эффективно - только один раз
        print(f"[DEBUG:generate_all] Создание индекса локальных переменных...", flush=True)
        local_var_decl_by_func: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        _local_count = 0
        for _io_item in info_data:
            if _io_item.get("kind", "") == "local variable":
                _qname = _io_item.get("qualified_name", "")
                # Имя ФО = имя ИО без последнего сегмента
                for _sep in ("::", "."):
                    if _sep in _qname:
                        _cand = _qname.rsplit(_sep, 1)[0]
                        if _cand in func_index:
                            local_var_decl_by_func[_cand].append(_io_item)
                            _local_count += 1
                            break
        print(f"[DEBUG:generate_all] Индекс готов: {_local_count} локальных переменных", flush=True)

        def _line_of(s: Dict[str, str]) -> int:
            try:
                return int(s.get("line_start", s.get("line", "0")) or 0)
            except (ValueError, TypeError):
                return 0

        # Кэш для пропуска уже отрисованных блок-схем
        cache_dir = self.output_dir / ".cache"
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / "generation_cache.json"
        cache: Dict[str, str] = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text())
            except:
                cache = {}

        # Номера ФО, чьи файлы схем реально лежат на диске: попадание в кэш
        # засчитываем только при наличии файла (иначе после очистки каталога
        # закэшированная схема никогда бы не пересоздалась).
        _files_on_disk: set = set()
        for _f in self.output_dir.iterdir():
            if _f.is_file():
                _head = _f.name.split("_", 1)[0]
                if _head.isdigit():
                    _files_on_disk.add(int(_head))

        generated = []
        routes_by_func: Dict[str, List[str]] = {}
        branch_edges_by_func: Dict[str, List[Dict[str, str]]] = {}
        # Инвентарь ветвей: для каждого ФО список {num, type, line} в порядке #N.
        # Та же нумерация branch_num, что в Граф_ветвей и на блок-схемах — служит
        # сверке состава/количества ветвей между статикой и динамикой.
        branch_inventory_by_func: Dict[str, List[Dict[str, str]]] = {}

        # Подготавливаем задачи для параллельной обработки
        print(f"[DEBUG:generate_all] Начало подготовки задач для {len(func_data)} функций", flush=True)
        tasks: List[tuple] = []
        # Входные данные для фазы маршрутов (по ВСЕМ ФО, включая закэшированные):
        # (func_name, func_num, filtered). Маршруты считаем отдельной фазой ПОСЛЕ
        # рендеринга SVG, чтобы прогресс шёл двумя раздельными секциями.
        route_inputs: List[tuple] = []

        _total_fd = len(func_data)
        for idx, item in enumerate(func_data):
            func_name = item["qualified_name"]
            # Номер ФО — позиция в Перечень_ФО (idx+1), а НЕ func_index[имя]:
            # у одноимённых функций поиск по имени давал номер последней.
            func_num = idx + 1

            # O(1) выборка данных функции из предпостроенных индексов.
            # Сначала точное совпадение (имя, файл объявления); если flow-данные
            # без func_file (старые БД) — берём все операторы по имени.
            stmts = stmts_by_func.get((func_name, item.get("file", "")))
            if stmts is None:
                stmts = stmts_by_name.get(func_name, [])
            calls = calls_by_func.get((func_name, item.get("file", "")))
            if calls is None:
                calls = calls_by_name.get(func_name, [])
            accesses = accesses_by_func.get(func_name, [])
            file_ios = file_io_by_func.get(func_name, [])

            filtered: List[Dict[str, Any]] = []
            occupied_lines = set()

            # Номера ИО (по перечню), используемых на каждой строке функции,
            # и файл, в котором расположено тело функции.
            io_ids_by_line: Dict[int, set] = defaultdict(set)
            func_file = ""
            for acc in accesses:
                var = acc.get("variable_name", "")
                if var not in var_index:
                    continue
                try:
                    line = int(acc.get("access_line", "0") or 0)
                except (ValueError, TypeError):
                    continue
                if line:
                    io_ids_by_line[line].add(var_index[var])
                    func_file = func_file or acc.get("func_file", "")

            # Добавляем строки объявления локальных переменных (int result = 1; и т.п.).
            # Используем предварительно созданный индекс
            for _decl in local_var_decl_by_func.get(func_name, []):
                _qname = _decl.get("qualified_name", "")
                if _qname not in var_index:
                    continue
                try:
                    _decl_line = int(_decl.get("line", "0") or 0)
                except (ValueError, TypeError):
                    continue
                if _decl_line:
                    io_ids_by_line[_decl_line].add(var_index[_qname])
                    func_file = func_file or _decl.get("file", "")

            # A. Управляющие конструкции и return из flow_data
            for s in stmts:
                if s.get("stmt_type", "") in ("if", "else", "while", "for", "do", "return", "try", "switch"):
                    # Сохраняем поле in_catch (1 если в catch-блоке, 0 иначе) для разделения try/catch
                    s_copy = dict(s)
                    s_copy["in_catch"] = int(s.get("in_catch", "0") or 0)
                    filtered.append(s_copy)
                    occupied_lines.add(_line_of(s))
                    # Для try: занимаем строку catch-клаузы, чтобы "} catch (e) {"
                    # не попал в блок-схему как process-узел.
                    if s.get("stmt_type", "") == "try":
                        _catch_line = int(s.get("else_line", "0") or 0)
                        if _catch_line:
                            occupied_lines.add(_catch_line)
                elif s.get("stmt_type", "") == "throw":
                    # throw-оператор из flow-данных (Java): метка — строка исходника.
                    line = _line_of(s)
                    src = self._get_source_line(s.get("stmt_id", ""))
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"throw_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": "throw",
                        "stmt_label": self._clip(src.strip()) if src else "throw",
                        "branch_type": "",
                    })
                    occupied_lines.add(line)
                elif s.get("stmt_type", "") in ("break", "continue"):
                    # break — выход из цикла; continue — переход к заголовку цикла.
                    # Узел-терминатор пути (обработка рёбер — в _render_node).
                    line = _line_of(s)
                    st = s.get("stmt_type", "")
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"{st}_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": st,
                        "stmt_label": st,
                        "branch_type": "",
                    })
                    occupied_lines.add(line)
                elif s.get("stmt_type", "") in ("goto", "label"):
                    # goto/метка — соединитель ГОСТ 19.701 (кружок с именем метки),
                    # а не длинное ребро-прыжок: убирает «обрыв» блоков, достижимых
                    # только через goto, не добавляя пересекающих рёбер.
                    line = _line_of(s)
                    st = s.get("stmt_type", "")
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"{st}_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": st,
                        "stmt_label": s.get("stmt_label", st),
                        "branch_type": "",
                    })
                    occupied_lines.add(line)
                elif s.get("stmt_type", "") in ("case", "default"):
                    # case/default — НЕ узлы блок-схемы (как else у if), а метки
                    # границ ветвей switch; нужны в filtered только чтобы
                    # _build_hierarchy включил их в children switch для
                    # партиционирования (см. _render_node, stmt_type == "switch").
                    line = _line_of(s)
                    st = s.get("stmt_type", "")
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"{st}_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": st,
                        "stmt_label": s.get("stmt_label", st),
                        "branch_type": "",
                    })
                    occupied_lines.add(line)

            # B. Вызовы ФО — метка = (id ФО) + строка кода из исходников (требование 2)
            seen_call_lines = set()
            for call in calls:
                callee_name = call.get("callee_name", "")
                # Номер вызываемой: точно по (имя, файл объявления callee из
                # control_matrix.ql), для legacy-данных без callee_file — по имени.
                callee_num = (num_by_name_file.get((callee_name, call.get("callee_file", "")))
                              or func_index.get(callee_name))
                if not callee_num:
                    continue
                try:
                    call_line = int(call["call_line"])
                except (ValueError, KeyError, TypeError):
                    continue
                if call_line in seen_call_lines:
                    continue
                caller_file = call.get("caller_file", "")
                # Полный оператор (с продолжением на следующих строках), чтобы
                # многострочный вызов не обрывался посреди аргументов.
                src = self._get_source_statement(f"{caller_file}:{call_line}") if caller_file else None
                # Неявные вызовы деструкторов привязаны к закрывающей скобке или
                # к строке объявления класса — пропускаем обе ситуации.
                if src is not None and src.strip(" \t{};") == "":
                    continue
                _DECL_KW = ("class ", "struct ", "template ", "namespace ", "public ", "private ")
                if src is not None and any(src.strip().startswith(kw) for kw in _DECL_KW):
                    continue
                seen_call_lines.add(call_line)
                code = self._clip(src) if src else f"{callee_name}()"
                call_label = self._id_prefix([callee_num]) + code
                filtered.append({
                    "stmt_id": f"call_{call_line}",
                    "line_start": call_line,
                    "line_end": call_line,
                    "stmt_type": "call",
                    "stmt_label": call_label,
                    "callee_num": callee_num,
                    "branch_type": "",
                })
                occupied_lines.add(call_line)

            # F. Файловые операции (из file_flow.ql) — IO-узел (параллелограм).
            # Запускается ДО секции C и D: строки с файловым ИО должны быть
            # параллелограмом, а не прямоугольником-process.
            for _ff in file_ios:
                try:
                    _ff_line = int(_ff.get("access_line", "0") or 0)
                except (ValueError, TypeError):
                    continue
                if _ff_line == 0 or _ff_line in occupied_lines:
                    continue
                _ff_file = _ff.get("func_file", "")
                _src = self._get_source_line(f"{_ff_file}:{_ff_line}") if _ff_file else None
                if not _src:
                    continue
                stripped = _src.strip()
                if not stripped or all(c in "{}; \t" for c in stripped):
                    continue
                _fname = _ff.get("file_name", "")
                _file_id = var_index.get(_fname)
                _prefix = self._id_prefix([_file_id]) if _file_id else ""
                filtered.append({
                    "stmt_id": f"fileio_{_ff_line}",
                    "line_start": _ff_line,
                    "line_end": _ff_line,
                    "stmt_type": "io",
                    "stmt_label": _prefix + self._clip(_src),
                    "branch_type": "",
                })
                occupied_lines.add(_ff_line)
                func_file = func_file or _ff_file

            # C. Операции ввода/вывода (cin/cout/printf/...) — (id ИО) + строка кода
            for s in stmts:
                if s.get("stmt_type", "") not in ("expr", "other", "decl"):
                    continue
                line = _line_of(s)
                if line == 0 or line in occupied_lines:
                    continue
                src = self._get_source_line(s.get("stmt_id", ""))
                if src and self._is_io_line(src):
                    label = self._id_prefix(io_ids_by_line.get(line, set())) + self._clip(src)
                    filtered.append({
                        "stmt_id": f"io_{line}",
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": "io",
                        "stmt_label": label,
                        "branch_type": "",
                        "in_catch": int(s.get("in_catch", "0") or 0),
                    })
                    occupied_lines.add(line)

            # D. Выражения, использующие ИО из перечня — (id ИО) + строка кода (требование 1)
            # Строим индекс стейтментов по строке для быстрого доступа к in_catch
            stmts_by_line = {_line_of(s): s for s in stmts}

            for line in sorted(io_ids_by_line):
                if line == 0 or line in occupied_lines:
                    continue
                src = self._get_source_line(f"{func_file}:{line}") if func_file else None
                if not src:
                    continue
                # Пропускаем строки, состоящие только из скобок/точек-с-запятой —
                # это неявные вызовы деструкторов при выходе из области видимости.
                # CodeQL фиксирует их как VariableAccess, но в блок-схеме они лишние.
                stripped = src.strip()
                if not stripped or all(c in "{}; \t" for c in stripped):
                    continue
                # Строки объявлений (class/struct/template/namespace) — не операторы,
                # появляются при неявных деструкторах, CodeQL относит их к заголовочным файлам.
                _DECL_KW = ("class ", "struct ", "template ", "namespace ", "public ", "private ")
                if any(stripped.startswith(kw) for kw in _DECL_KW):
                    continue
                label = self._id_prefix(io_ids_by_line[line]) + self._clip(src)
                # Копируем in_catch из соответствующего стейтмента
                _in_catch = 0
                if line in stmts_by_line:
                    _in_catch = int(stmts_by_line[line].get("in_catch", "0") or 0)
                filtered.append({
                    "stmt_id": f"proc_{line}",
                    "line_start": line,
                    "line_end": line,
                    "stmt_type": "process",
                    "stmt_label": label,
                    "branch_type": "",
                    "in_catch": _in_catch,
                })
                occupied_lines.add(line)

            # E. Терминаторы: throw и системные выходы (exit/abort и т.п.)
            for s in stmts:
                if s.get("stmt_type", "") not in ("expr", "other"):
                    continue
                line = _line_of(s)
                if line == 0 or line in occupied_lines:
                    continue
                src = self._get_source_line(s.get("stmt_id", ""))
                if not src:
                    continue
                _in_catch = int(s.get("in_catch", "0") or 0)
                if self._is_throw_line(src):
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"throw_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": "throw",
                        "stmt_label": self._clip(src.strip()),
                        "branch_type": "",
                        "in_catch": _in_catch,
                    })
                    occupied_lines.add(line)
                elif self._is_exit_line(src):
                    filtered.append({
                        "stmt_id": s.get("stmt_id", f"exit_{line}"),
                        "line_start": line,
                        "line_end": line,
                        "stmt_type": "exit",
                        "stmt_label": self._clip(src.strip()),
                        "branch_type": "",
                        "in_catch": _in_catch,
                    })
                    occupied_lines.add(line)

            # G. «Голый» код без ФО/ИО — узлы-заглушки "(КОД)".
            # Любая реальная строка-оператор, не ставшая узлом в секциях A–F
            # (нет вызова ФО, нет ИО из перечня), иначе тело ветки исчезает и
            # «да»/«нет» сходятся в одну точку. Подряд идущие строки ОДНОГО уровня
            # отступа схлопываем в один узел (уважает блочную структуру Python).
            _bare = []  # (line, in_catch, indent)
            _bare_seen = set()
            for s in stmts:
                line = _line_of(s)
                if line == 0 or line in occupied_lines or line in _bare_seen:
                    continue
                src = self._get_source_line(s.get("stmt_id", ""))
                if not src:
                    continue
                stripped = src.strip()
                if not stripped or all(c in "{}; \t" for c in stripped):
                    continue
                _bare_seen.add(line)
                _bare.append((line, int(s.get("in_catch", "0") or 0), len(src) - len(src.lstrip())))
            _bare.sort()
            _gi = 0
            while _gi < len(_bare):
                _gj = _gi
                while (_gj + 1 < len(_bare)
                       and _bare[_gj + 1][0] == _bare[_gj][0] + 1
                       and _bare[_gj + 1][2] == _bare[_gi][2]):
                    _gj += 1
                _first, _last = _bare[_gi][0], _bare[_gj][0]
                filtered.append({
                    "stmt_id": f"code_{_first}",
                    "line_start": _first,
                    "line_end": _last,
                    "stmt_type": "process",
                    "stmt_label": "(КОД)",
                    "branch_type": "",
                    "in_catch": _bare[_gi][1],
                })
                for _ln in range(_first, _last + 1):
                    occupied_lines.add(_ln)
                _gi = _gj + 1

            # Нумерация узлов-ветвлений (#1, #2, ...) в порядке строки кода.
            # "switch" сюда НЕ входит (как и "if" не нумерует себя отдельно
            # от "else") — нумеруются сами ветви: case/default, симметрично
            # probe_points.ql, где датчик ставится на каждую case/default
            # метку, а не на сам switch.
            branch_counter = 0
            for node in sorted(filtered, key=lambda x: int(x.get("line_start", 0) or 0)):
                if node["stmt_type"] in ("if", "else", "while", "for", "do", "try", "case", "default"):
                    branch_counter += 1
                    node["branch_num"] = branch_counter

            # Маршруты/ветви считаем отдельной фазой ПОСЛЕ SVG — здесь только
            # запоминаем подготовленную иерархию операторов данного ФО.
            route_inputs.append((func_name, func_num, filtered))

            # Кэширование: пропускаем если функция не изменилась И файл схемы
            # существует на диске (после очистки каталога кэш недействителен).
            cache_key = self._get_cache_key(func_name, func_num, filtered)
            if cache_key in cache and func_num in _files_on_disk:
                continue

            # Добавляем в очередь параллельной обработки
            # НЕ передаём func_index и var_index - они слишком большие и дублируются!
            tasks.append((func_name, func_num, filtered, cache_key))

            # Логируем каждую 500-ю функцию, чтобы видеть прогресс
            if (idx + 1) % 500 == 0:
                print(f"[DEBUG] Обработано {idx + 1}/{_total_fd} функций, tasks={len(tasks)}, routes_by_func={len(routes_by_func)}", flush=True)

        # === ОСВОБОЖДАЕМ ПАМЯТЬ ===
        print(f"[DEBUG:generate_all] Цикл завершён! Подготовлено {len(tasks)} задач для обработки", flush=True)
        print(f"[DEBUG:generate_all] routes_by_func содержит {len(routes_by_func)} маршрутов", flush=True)
        # Удаляем большие словари-индексы которые больше не нужны
        print(f"[DEBUG:generate_all] Удаляю индексы группировки", flush=True)
        del stmts_by_func, stmts_by_name, calls_by_func, calls_by_name, accesses_by_func, local_var_decl_by_func, file_io_by_func
        gc.collect()
        print(f"[DEBUG:generate_all] Память очищена перед параллельной обработкой", flush=True)

        # === ФАЗА «БЛОК-СХЕМЫ»: параллельный рендеринг SVG (если нужны) ===
        if build_flowcharts:
            from core.report_generator import progress_bar
            from concurrent.futures import as_completed
            _t_svg = time.time()
            total_tasks = len(tasks)
            completed = 0

            # Очередь от МАЛЫХ к ГИГАНТАМ: размер графа ≈ число узлов (len(filt)).
            # Тяжёлые функции (раскладка ELK суперлинейна) уходят в конец очереди —
            # основная масса строится быстро, а гиганты не блокируют ранний прогресс
            # (и НЕ пропускаются — у постоянного node-воркера таймаута нет).
            tasks.sort(key=lambda t: len(t[2]))

            # Число воркеров: по ядрам (с разумным потолком). workers<=0 → авто.
            if workers and workers > 0:
                max_workers = workers
            else:
                max_workers = min(os.cpu_count() or 1, 8)

            def _on_result(result, cache_key):
                if result:
                    generated.append(result)
                    cache[cache_key] = True  # Отмечаем что функция обработана

            # PROCESS-pool: рендер SVG и сборка ELK-JSON идут в отдельных процессах
            # (обходит GIL — Python-часть тоже параллелится). Каждый процесс держит
            # свой постоянный node. Большие словари func_index/var_index пиклятся
            # один раз на процесс через initializer.
            use_processes = max_workers > 1 and total_tasks > 4
            if use_processes:
                print(f"[DEBUG:generate_all] Начинаем обработку {total_tasks} блок-схем "
                      f"в {max_workers} процесс(ов), очередь малые->гиганты", flush=True)
                spec = self._worker_spec()
                try:
                    with ProcessPoolExecutor(max_workers=max_workers,
                                             initializer=_pp_init,
                                             initargs=(spec, func_index, var_index)) as executor:
                        futures = {executor.submit(_pp_task, t): t[3] for t in tasks}
                        for future in as_completed(futures):
                            try:
                                result, cache_key = future.result()
                            except Exception as e:
                                print(f"       Error generating flowchart: {e}", flush=True)
                                result, cache_key = "", futures[future]
                            _on_result(result, cache_key)
                            completed += 1
                            if progress:
                                progress("[БЛОК-СХЕМЫ] Генерация блок-схем (ФО)", completed, total_tasks)
                            if completed % 50 == 0 or completed == total_tasks:
                                print(f"[DEBUG:generate] {completed}/{total_tasks} блок-схем готово", flush=True)
                except Exception as e:
                    print(f"       ProcessPool недоступен ({e}); откат на потоки", flush=True)
                    use_processes = False
                    completed = 0
                    generated.clear()

            if not use_processes:
                # Малый объём или откат: потоки в текущем процессе + постоянный node.
                print(f"[DEBUG:generate_all] Обработка {total_tasks} блок-схем "
                      f"в {max_workers} поток(ов) (in-process)", flush=True)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self.generate, fname, fnum, filt, func_index, var_index): ck
                        for fname, fnum, filt, ck in tasks
                    }
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception as e:
                            print(f"       Error generating flowchart: {e}", flush=True)
                            result = ""
                        _on_result(result, futures[future])
                        completed += 1
                        if progress:
                            progress("[БЛОК-СХЕМЫ] Генерация блок-схем (ФО)", completed, total_tasks)
                        if completed % 50 == 0 or completed == total_tasks:
                            print(f"[DEBUG:generate] {completed}/{total_tasks} блок-схем готово", flush=True)
                _close = getattr(self, "close_elk_servers", None)
                if callable(_close):
                    _close()

            # Сохраняем кэш
            try:
                cache_file.write_text(json.dumps(cache))
            except:
                pass  # Игнорируем ошибки записи кэша
            if log:
                log(f"[БЛОК-СХЕМЫ] готово: {len(generated)} "
                    f"(за {time.time() - _t_svg:.1f} с)")
        else:
            print(f"[DEBUG:generate_all] Генерация блок-схем отключена (build_flowcharts=False)", flush=True)

        # === ФАЗА «МАРШРУТЫ»: формирование базисных маршрутов и ветвей по ФО ===
        _t_routes = time.time()
        _nroutes_total = 0
        _nri = len(route_inputs)
        for _i, (_fn, _fnum, _filt) in enumerate(route_inputs):
            if progress:
                progress("[МАРШРУТЫ] Формирование маршрутов (ФО)", _i + 1, _nri)
            _hier = self._build_hierarchy(_filt)
            _routes = self._enumerate_routes(_hier, _fnum, max_routes=max_routes)
            _nroutes_total += len(_routes)
            # Потоковая запись на диск (CLI) и/или накопление в памяти (графы/БД).
            if route_writer is not None:
                route_writer.add_func(_fn, _fnum, _routes)
            if need_routes_in_memory:
                # Ключ '<номер_ФО>|<имя>' (func_key.py): qualified_name неуникален
                # (static-тёзки, перегрузки) — по имени данные перезаписывались.
                _fkey = make_func_key(_fnum, _fn)
                routes_by_func[_fkey] = _routes
                # Полный граф переходов между ветками — структурно, без кэпа.
                branch_edges_by_func[_fkey] = self._branch_transitions(_hier)
                # Инвентарь ветвей #N (с позицией) для Перечень_ветвей.csv
                branch_inventory_by_func[_fkey] = [
                    {"num": n["branch_num"], "type": n["stmt_type"],
                     "line": n.get("line_start", n.get("line", 0)),
                     "line_end": n.get("line_end", n.get("line_start", n.get("line", 0)))}
                    for n in sorted(_filt, key=lambda x: int(x.get("branch_num") or 0))
                    if n.get("branch_num")
                ]
                # Добавить else-ветви из IfStmt (else — не отдельный Stmt в CodeQL AST,
                # поэтому генерируем отдельную запись в инвентаре из данных else_line).
                # ВАЖНО: else-if (when else_line указывает на строку вложенного if)
                # НЕ даёт записи "else" — это самостоятельная if-ветвь, уже учтённая
                # выше как отдельный узел. else_line у такого if нужен лишь
                # перечислителю маршрутов (_arms) для деления на «да»/«нет».
                _if_lines = {int(x.get("line_start", x.get("line", 0)) or 0)
                             for x in _filt if x.get("stmt_type") == "if"}
                _else_entries = []
                for n in _filt:
                    if n.get("stmt_type") == "if":
                        _el = int(n.get("else_line", "0") or 0)
                        _ln = int(n.get("line_start", n.get("line", 0)) or 0)
                        # else-if: else_line указывает на ДРУГОЙ (вложенный) if,
                        # а не на сам n. Условие _el != _ln отделяет однострочный
                        # `if (...) op1; else op2;` (где else на той же строке, что
                        # и сам if) — это ПЛОСКИЙ else, запись нужна.
                        _is_else_if = _el > 0 and _el != _ln and _el in _if_lines
                        if _el > 0 and not _is_else_if:        # плоский else
                            _else_entries.append({
                                "num": n.get("branch_num"),
                                "type": "else",
                                "line": _el,
                                "line_end": int(n.get("else_line_end", "0") or 0),
                            })
                branch_inventory_by_func[_fkey].extend(_else_entries)
        if log:
            log(f"[МАРШРУТЫ] готово: {_nroutes_total} для {_nri} ФО "
                f"(за {time.time() - _t_routes:.1f} с)")

        return generated, routes_by_func, branch_edges_by_func, branch_inventory_by_func
