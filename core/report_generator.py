import csv
import html
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

from viz.func_key import split_func_key


def read_critical_io_numbers(path) -> set:
    """Читает пользовательский Перечень_критических_ИО.csv (подмножество
    Перечень_ИО.csv) и возвращает множество номеров ИО (№ из первого столбца).

    Сопоставление с данными — строго по № ИО (как договорено). Заголовок
    пропускается; из первого столбца берётся ведущее целое (формат «5» или «5(...)»).
    """
    import re
    nums: set = set()
    p = Path(path)
    if not p.exists():
        return nums
    with open(p, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        for i, row in enumerate(reader):
            if i == 0 or not row:
                continue  # шапка / пустые строки
            m = re.match(r"\s*(\d+)", row[0])
            if m:
                nums.add(int(m.group(1)))
    return nums


def progress_bar(current: int, total: int, label: str, width: int = 30,
                 force: bool = False):
    """Рисует интерактивный прогресс-бар в одну строку (через \\r).

    В неинтерактивном режиме (фон/пайп) печатает только финальную строку при
    завершении (current == total), чтобы не засорять лог.
    """
    if total <= 0:
        return
    interactive = sys.stdout.isatty()
    done = current >= total
    # В неинтерактивном режиме выводим только по завершении.
    if not interactive and not done:
        return
    frac = current / total
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    end = "\n" if done else ""
    prefix = "" if not interactive else "\r"
    line = f"{prefix}       {label}: [{bar}] {current}/{total} ({frac*100:5.1f}%)"
    try:
        print(line, end=end, flush=True)
    except UnicodeEncodeError:
        safe = line.encode("ascii", "replace").decode("ascii")
        print(safe, end=end, flush=True)


class RouteStreamWriter:
    """Потоковая запись отчётов о маршрутах выполнения ФО.

    Маршруты пишутся функция-за-функцией в оба CSV сразу: после обработки
    каждой функции её маршруты сбрасываются на диск и освобождаются. Это
    исключает накопление маршрутов всех ФО в памяти (причина 10+ ГБ ОЗУ),
    сохраняя полноту перечня (требование РД НДВ № 114).
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        # Файл 1 — маршруты ветвей; Файл 2 — последовательности вызовов ФО.
        self._f_br = open(self.output_dir / "Маршруты_выполнения_ФО(ветвей).csv",
                          "w", newline="", encoding="utf-8-sig")
        self._f_call = open(self.output_dir / "Маршруты_выполнения_ФО(процедур_функций).csv",
                            "w", newline="", encoding="utf-8-sig")
        self._w_br = csv.writer(self._f_br, delimiter=";")
        self._w_call = csv.writer(self._f_call, delimiter=";")
        self._w_br.writerow(["№ п/п", "№ ФО", "Функциональный объект", "№ маршрута", "Маршрут"])
        self._w_call.writerow(["№ п/п", "№ ФО", "Функциональный объект", "№ маршрута", "Маршрут"])

    def add_func(self, func_name: str, func_num: int, routes: List[Dict]):
        """Записывает маршруты одной функции в оба отчёта."""
        self._seq += 1
        seq = self._seq

        if not routes:
            routes = [{"route_num": 1, "route_str": "Начало->Конец", "calls": [func_num]}]

        # Файл 1: маршруты ветвей (по строке на маршрут)
        for r_idx, r in enumerate(routes):
            self._w_br.writerow([
                seq if r_idx == 0 else "",
                func_num if r_idx == 0 else "",
                func_name if r_idx == 0 else "",
                r["route_num"],
                r["route_str"],
            ])

        # Файл 2: цепочки вызовов ФО с объединением одинаковых
        groups: Dict[tuple, List[int]] = {}
        for r in routes:
            groups.setdefault(tuple(r["calls"]), []).append(r["route_num"])
        for g_idx, (calls_key, route_nums) in enumerate(groups.items()):
            self._w_call.writerow([
                seq if g_idx == 0 else "",
                func_num if g_idx == 0 else "",
                func_name if g_idx == 0 else "",
                ",".join(str(n) for n in route_nums),
                "->".join(f"({n})" for n in calls_key),
            ])

    def close(self):
        self._f_br.close()
        self._f_call.close()
        print(f"       Saved: Маршруты_выполнения_ФО(ветвей).csv  ({self._seq} объектов)")
        print(f"       Saved: Маршруты_выполнения_ФО(процедур_функций).csv  ({self._seq} объектов)")


class ReportGenerator:
    """Генерирует набор CSV-отчётов в указанной директории."""

    _SPARSE_THRESHOLD = 50

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _write_csv(self, filename: str, headers: List[str], rows: List[List[Any]]):
        """Пишет CSV с интерактивным счётчиком основных объектов отчёта.

        Основной объект — строка с непустым первым столбцом (№ п/п). Строки
        продолжения (с пустым первым полем) — это дополнительные использования
        того же объекта и в счётчик не входят.
        """
        path = self.output_dir / filename
        interactive = sys.stdout.isatty()
        count = 0
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            for i, row in enumerate(rows):
                writer.writerow(row)
                if row and str(row[0]).strip():
                    count += 1
                    # Обновляем счётчик на месте; не на каждой строке, чтобы
                    # не тормозить запись больших отчётов.
                    if interactive and count % 100 == 0:
                        print(f"\r       {filename}: {count} объектов...", end="", flush=True)
        if interactive:
            print("\r\033[K", end="")  # очистить строку прогресса
        print(f"       Saved: {filename}  ({count} объектов)")

    def _write_csv_stream(self, filename: str, headers: List[str], row_iter):
        """Потоковая запись CSV из итератора/генератора строк.

        Не материализует все строки в памяти — пишет по одной. Подходит для
        огромных отчётов (миллионы строк), где список целиком не помещается в RAM.
        Счётчик основных объектов — по непустому первому столбцу.
        """
        path = self.output_dir / filename
        interactive = sys.stdout.isatty()
        count = 0
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            for row in row_iter:
                writer.writerow(row)
                if row and str(row[0]).strip():
                    count += 1
                    if interactive and count % 1000 == 0:
                        print(f"\r       {filename}: {count}...", end="", flush=True)
        if interactive:
            print("\r\033[K", end="")
        print(f"       Saved: {filename}  ({count} объектов)")

    @staticmethod
    def _make_matrix(n: int):
        """Выбирает dense или sparse матрицу в зависимости от размера."""
        if n > ReportGenerator._SPARSE_THRESHOLD:
            return True, {}
        return False, [[set() for _ in range(n)] for _ in range(n)]

    @staticmethod
    def _matrix_add(sparse: bool, storage: Any, r: int, c: int, val: Any):
        """Добавить значение в матрицу (dense или sparse)."""
        if sparse:
            storage.setdefault((r, c), set()).add(val)
        else:
            storage[r][c].add(val)

    @staticmethod
    def _matrix_get(sparse: bool, storage: Any, r: int, c: int) -> set:
        """Получить значение из матрицы (dense или sparse)."""
        if sparse:
            return storage.get((r, c), set())
        return storage[r][c]

    def _write_individual_functional_objects(
        self,
        data: List[Dict[str, str]],
        callers_map: Dict[str, List[Dict[str, str]]],
        func_index: Dict[str, int],
    ):
        """Создаёт отдельный HTML-файл для каждого ФО со всеми сведениями."""
        fo_dir = self.output_dir / "functional_objects"
        fo_dir.mkdir(parents=True, exist_ok=True)

        for i, item in enumerate(data, 1):
            func_name = item["qualified_name"]
            safe_name = (
                func_name.replace("::", "_")
                .replace("<", "_")
                .replace(">", "_")
                .replace(" ", "_")
                .replace("(", "_")
                .replace(")", "_")
                .replace("[", "_")
                .replace("]", "_")
                .replace(",", "_")
            )
            
            # Собираем все данные о ФО
            declared_file = item.get("file", "")
            declared_line = item.get("line", "")
            declared = f"{declared_file}({declared_line})" if declared_file else "N/A"
            parent_type = item.get("parent_type", "(global)")
            kind = item.get("kind", "function")
            
            callers = callers_map.get(func_name, [])
            
            # Генерируем HTML
            html_content = self._generate_functional_object_html(
                index=i,
                qualified_name=func_name,
                name=item.get("name", ""),
                parent_type=parent_type,
                kind=kind,
                declared=declared,
                callers=callers,
                func_index=func_index
            )
            
            filepath = fo_dir / f"{safe_name}.html"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

    def _generate_functional_object_html(
        self,
        index: int,
        qualified_name: str,
        name: str,
        parent_type: str,
        kind: str,
        declared: str,
        callers: List[Dict[str, str]],
        func_index: Dict[str, int],
    ) -> str:
        """Генерирует HTML-содержимое для одного ФО."""
        
        # Таблица вызывающих функций
        callers_rows = ""
        if callers:
            for caller_info in callers:
                caller_name = caller_info.get("caller", "")
                caller_num = func_index.get(caller_name, "")
                caller_formatted = f"({caller_num}){caller_name}" if caller_num else caller_name
                caller_file = caller_info.get("caller_file", "")
                call_line = caller_info.get("call_line", "")
                callers_rows += f"""
                <tr>
                    <td>{caller_formatted}</td>
                    <td>{caller_file}({call_line})</td>
                </tr>"""
        else:
            callers_rows = """<tr><td colspan="2" style="color: #999;">Не вызывается другими функциями</td></tr>"""
        
        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>ФО: {html.escape(qualified_name)}</title>
    <style>
        body {{
            font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            margin-top: 30px;
            border-left: 4px solid #4CAF50;
            padding-left: 10px;
        }}
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .info-table th, .info-table td {{
            padding: 12px;
            border: 1px solid #ddd;
            text-align: left;
        }}
        .info-table th {{
            background-color: #4CAF50;
            color: white;
            width: 200px;
        }}
        .info-table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .info-table tr:hover {{
            background-color: #f1f1f1;
        }}
        .callers-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            background: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .callers-table th, .callers-table td {{
            padding: 10px;
            border: 1px solid #ddd;
            text-align: left;
        }}
        .callers-table th {{
            background-color: #2196F3;
            color: white;
        }}
        .callers-table tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}
        .kind-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: bold;
        }}
        .kind-member {{ background-color: #4CAF50; color: white; }}
        .kind-function {{ background-color: #2196F3; color: white; }}
        .kind-constructor {{ background-color: #FF9800; color: white; }}
        .kind-destructor {{ background-color: #f44336; color: white; }}
        .kind-entry {{ background-color: #9C27B0; color: white; }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #999;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Функциональный объект #{index}</h1>
        
        <table class="info-table">
            <tr>
                <th>Полное имя (qualified name)</th>
                <td><code>{html.escape(qualified_name)}</code></td>
            </tr>
            <tr>
                <th>Имя</th>
                <td><code>{html.escape(name)}</code></td>
            </tr>
            <tr>
                <th>Родительский тип</th>
                <td><code>{html.escape(parent_type)}</code></td>
            </tr>
            <tr>
                <th>Тип объекта</th>
                <td><span class="kind-badge kind-{kind}">{html.escape(kind)}</span></td>
            </tr>
            <tr>
                <th>Объявлен в</th>
                <td><code>{html.escape(declared)}</code></td>
            </tr>
        </table>
        
        <h2>Вызывающие функции</h2>
        <table class="callers-table">
            <tr>
                <th>Вызывающая функция</th>
                <th>Место вызова</th>
            </tr>
            {callers_rows}
        </table>
        
        <div class="footer">
            <p>Сгенерировано CodeQL Database Analyzer</p>
            <p>Файл: functional_objects/{html.escape(qualified_name)}.html</p>
        </div>
    </div>
</body>
</html>"""
        
        return html_content

    def add_functional_objects(self, data: List[Dict[str, str]], ctrl_data: List[Dict[str, str]]):
        # Строим маппинг: вызываемая функция -> список вызывающих с информацией о месте вызова
        callers_map: Dict[str, List[Dict[str, str]]] = {}
        for item in ctrl_data:
            callee = item.get("callee_name", "")
            caller = item.get("caller_name", "")
            caller_file = item.get("caller_file", "")
            call_line = item.get("call_line", "")
            callers_map.setdefault(callee, []).append({
                "caller": caller,
                "caller_file": caller_file,
                "call_line": call_line
            })
        
        # Создаем маппинг имен к номерам; точный номер — по (имя, файл объявления):
        # caller_file в control_matrix.ql — файл объявления вызывающего, поэтому
        # одноимённые вызывающие получают свои номера (fallback — по имени).
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(data)}
        num_by_nf = {(item["qualified_name"], item.get("file", "")): i + 1
                     for i, item in enumerate(data)}

        def _caller_fmt(caller_info):
            cname = caller_info['caller']
            cnum = (num_by_nf.get((cname, caller_info.get('caller_file', '')))
                    or func_index.get(cname, ""))
            return f"({cnum}){cname}" if cnum else cname

        # Расщепление (по аналогии с ИО): «шапка» Перечень_ФО (1 строка на объект)
        # и деталь Использования_ФО (по строке на каждый вызов). Нумерация ФО
        # сохраняется (i = позиция в data), её используют матрицы, динамика и тесты.
        # Обе таблицы пишутся потоково.
        def _declared(item):
            return f"{item.get('file', '')}({item.get('line', '')})" if item.get("file") else ""

        # Шапка: №; объект; объявлен_в; число_использований
        def fo_header_rows():
            for i, item in enumerate(data, 1):
                callers = callers_map.get(item["qualified_name"], [])
                yield [i, item["qualified_name"], _declared(item), len(callers)]

        self._write_csv_stream(
            "Перечень_ФО(процедур_функций).csv",
            ["№ п/п", "Объект", "Объявлен в", "Число использований"],
            fo_header_rows(),
        )

        # Деталь: №ФО; объект; используется_в; вызывается_объектом
        def fo_usage_rows():
            for i, item in enumerate(data, 1):
                func_name = item["qualified_name"]
                for caller in callers_map.get(func_name, []):
                    used_in = (f"{caller['caller_file']}({caller['call_line']})"
                               if caller['caller_file'] else "")
                    yield [i, func_name, used_in, _caller_fmt(caller)]

        self._write_csv_stream(
            "Использования_ФО(процедур_функций).csv",
            ["№ ФО", "Объект", "Используется в", "Вызывается объектом"],
            fo_usage_rows(),
        )

    # Точки входа программы — никогда не вызываются извне, но не являются избыточными
    _ENTRY_POINTS = {"main", "WinMain", "wWinMain", "wmain"}

    def add_redundant_objects_from_usage(self, data: List[Dict[str, str]], ctrl_data: List[Dict[str, str]]):
        # Строим маппинг: вызываемая функция -> есть ли вызовы
        called_functions = set()
        for item in ctrl_data:
            callee = item.get("callee_name", "")
            called_functions.add(callee)

        # Избыточные = те, у кого нет вызовов и кто не является точкой входа
        redundant = [
            item for item in data
            if item["qualified_name"] not in called_functions
            and item["qualified_name"] not in self._ENTRY_POINTS
        ]
        
        # Создаем маппинг имен к номерам
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(data)}
        
        rows = []
        for i, item in enumerate(redundant, 1):
            main_idx = func_index.get(item["qualified_name"], "")
            if main_idx:
                num = f"{i}({main_idx})"
            else:
                num = str(i)
            declared = f"{item.get('file', '')}({item.get('line', '')})" if item.get("file") else ""
            rows.append([num, item["qualified_name"], declared])
        self._write_csv(
            "Перечень_избыточных_ФО(процедур_функций).csv",
            ["№ п/п", "Избыточный объект", "Объявлен в"],
            rows,
        )

    def add_info_objects(
        self,
        data: List[Dict[str, str]],
        data_matrix_data: List[Dict[str, str]],
        arg_flow_data: List[Dict[str, str]] = None,
        file_flow_data: List[Dict[str, str]] = None,
        func_data: List[Dict[str, str]] = None,
        file_ordered: List[Dict[str, Any]] = None,
        file_io_order: List[str] | None = None,
    ):
        # Исключаем аргументы (параметры) ФО из перечня ИО
        data = [item for item in data if item.get("kind") != "parameter"]

        # Приоритет типов: аргумент > запись > чтение
        _type_priority = {"аргумент": 3, "запись": 2, "чтение": 1}

        # Один проход: одновременно собираем access_type_map и var_usage_map
        access_type_map: Dict[tuple, str] = {}
        var_usage_map: Dict[str, List[Dict[str, str]]] = {}
        seen_uids: set = set()

        for item in data_matrix_data:
            var  = item.get("variable_name", "")
            func = item.get("function_name", "")
            ff   = item.get("func_file", "")
            line = item.get("access_line", "")
            atype = item.get("access_type", "чтение")

            # Приоритет доступа: аргумент > запись > чтение.
            # Ключ включает файл: обращения к одной переменной из разных файлов
            # на совпадающих номерах строк не должны перетирать тип друг друга.
            key = (var, ff, line)
            prev = access_type_map.get(key, "чтение")
            if _type_priority.get(atype, 1) >= _type_priority.get(prev, 1):
                access_type_map[key] = atype

            # Дедупликация: одна запись на (var, func, line)
            uid = (var, func, line)
            if uid not in seen_uids:
                seen_uids.add(uid)
                var_usage_map.setdefault(var, []).append({
                    "function": func,
                    "func_file": ff,
                    "access_line": line,
                })

        # Аргументные потоки: (caller_var, caller_file, call_line) -> "аргумент"
        if arg_flow_data:
            for af in arg_flow_data:
                key = (af.get("caller_var", ""), af.get("caller_file", ""),
                       af.get("call_line", ""))
                access_type_map[key] = "аргумент"

        var_index = {item["qualified_name"]: i + 1 for i, item in enumerate(data)}
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data or [])}
        file_index = {f["abs_path"]: f["id"] for f in (file_ordered or [])}

        def func_label(fn):
            fnum = func_index.get(fn, "")
            return f"({fnum}){fn}" if fnum else fn

        def place(ff, line):
            fnum = file_index.get(ff, "")
            ffmt = f"({fnum}){ff}" if fnum else ff
            return f"{ffmt}({line})" if ff else ""

        # Расщепление (пункт ②): «шапка» Перечень_ИО (1 строка на объект) и
        # деталь Использования_ИО (по строке на каждое использование). Это
        # держит Перечень_ИО в пределах лимита строк Excel даже для огромных БД,
        # а деталь грузится отдельно. Обе таблицы пишутся потоково (пункт ④).

        # Шапка: №; объект; объявлен_в; тип_объекта; число_использований
        def io_header_rows():
            _total = len(data)
            for i, item in enumerate(data, 1):
                var_name = item["qualified_name"]
                usages = var_usage_map.get(var_name, [])
                yield [i, var_name, place(item.get('file', ''), item.get('line', '')),
                       item.get("kind", ""), len(usages)]
            # Файловые ИО — нумерация продолжается после переменных.
            if file_flow_data:
                file_order = file_io_order if file_io_order is not None else self._file_io_order(file_flow_data)
                next_num = len(data) + 1
                ub = {}
                for fr in file_flow_data:
                    ub.setdefault(fr.get("file_name", ""), []).append(fr)
                for fname in file_order:
                    yield [next_num, fname, "(файл)", "файл", len(ub.get(fname, []))]
                    next_num += 1

        self._write_csv_stream(
            "Перечень_ИО.csv",
            ["№ п/п", "Объект", "Объявлен в", "Тип объекта", "Число использований"],
            io_header_rows(),
        )

        # Деталь: io_id; объект; используется_в; тип_использования; ФО
        def io_usage_rows():
            for i, item in enumerate(data, 1):
                var_name = item["qualified_name"]
                for usage in var_usage_map.get(var_name, []):
                    atype = access_type_map.get(
                        (var_name, usage['func_file'], usage['access_line']), "чтение")
                    yield [i, var_name, place(usage['func_file'], usage['access_line']),
                           atype, func_label(usage['function'])]
            if file_flow_data:
                file_order = file_io_order if file_io_order is not None else self._file_io_order(file_flow_data)
                next_num = len(data) + 1
                ub = {}
                for fr in file_flow_data:
                    ub.setdefault(fr.get("file_name", ""), []).append(fr)
                for fname in file_order:
                    for u in ub.get(fname, []):
                        yield [next_num, fname, place(u['func_file'], u['access_line']),
                               u["access_type"], u["function_name"]]
                    next_num += 1

        self._write_csv_stream(
            "Использования_ИО.csv",
            ["№ ИО", "Объект", "Используется в", "Тип использования", "Вызывается объектом"],
            io_usage_rows(),
        )

    def add_redundant_info_objects_from_usage(self, data: List[Dict[str, str]], data_matrix_data: List[Dict[str, str]]):
        # Строим маппинг: переменная -> есть ли использования
        used_variables = set()
        for item in data_matrix_data:
            var = item.get("variable_name", "")
            used_variables.add(var)
        
        # Избыточные = те, у которых нет использований
        redundant = [item for item in data if item["qualified_name"] not in used_variables]
        
        # Создаем маппинг имен к номерам
        var_index = {item["qualified_name"]: i + 1 for i, item in enumerate(data)}
        
        rows = []
        for i, item in enumerate(redundant, 1):
            main_idx = var_index.get(item["qualified_name"], "")
            if main_idx:
                num = f"{i}({main_idx})"
            else:
                num = str(i)
            declared = f"{item.get('file', '')}({item.get('line', '')})" if item.get("file") else ""
            rows.append([num, item["qualified_name"], declared])
        self._write_csv(
            "Перечень_избыточных_ИО.csv",
            ["№ п/п", "Избыточный объект", "Объявлен в"],
            rows,
        )

    def add_control_matrix(
        self,
        func_data: List[Dict[str, str]],
        ctrl_data: List[Dict[str, str]],
    ):
        fo_list = [item["qualified_name"] for item in func_data]
        fo_idx = {name: i + 1 for i, name in enumerate(fo_list)}
        n = len(fo_list)

        # Точный номер ФО по (имя, файл объявления): одноимённые функции
        # (static-тёзки, перегрузки) занимают СВОИ оси матрицы. caller_file /
        # callee_file приходят из control_matrix.ql тем же API, что `file`
        # в functional_objects.ql. Fallback по имени — для legacy-данных.
        num_by_nf = {(item["qualified_name"], item.get("file", "")): i + 1
                     for i, item in enumerate(func_data)}

        def _num(name: str, file: str):
            return (num_by_nf.get((name, file)) if file else None) or fo_idx.get(name)

        # Считаем количество вызовов для каждой пары (номер_вызывающего, номер_вызываемого)
        ctrl_counts: Dict[tuple, int] = {}
        for item in ctrl_data:
            ci = _num(item["caller_name"], item.get("caller_file", ""))
            ce = _num(item["callee_name"], item.get("callee_file", ""))
            if ci and ce:
                ctrl_counts[(ci, ce)] = ctrl_counts.get((ci, ce), 0) + 1

        fname = "Матрица_связей_ФО(процедур_функций)_по_управлению.csv"

        # Большие проекты — разреженный список рёбер (изоморфен матрице,
        # но без O(N²) ячеек). Ячейка матрицы = «кто-кого-сколько раз».
        if n > self._SPARSE_THRESHOLD:
            self._write_csv_stream(
                fname,
                ["Вызывающий_ФО", "Вызываемый_ФО", "Кол-во_вызовов"],
                ([ci, ce, cnt] for (ci, ce), cnt in sorted(ctrl_counts.items())),
            )
            return

        # Малые проекты — привычный плотный матричный вид.
        headers = [""]
        for i, name in enumerate(fo_list, 1):
            headers.append(f"({i}){name}")
        rows = []
        for i, caller in enumerate(fo_list, 1):
            row = [f"({i}){caller}"]
            for j in range(1, n + 1):
                row.append(ctrl_counts.get((i, j), ""))
            rows.append(row)
        self._write_csv(fname, headers, rows)

    def add_data_matrix(
        self,
        func_data: List[Dict[str, str]],
        info_data: List[Dict[str, str]],
        data_matrix_data: List[Dict[str, str]],
        arg_flow_data: List[Dict[str, str]] = None,
        file_flow_data: List[Dict[str, str]] = None,
        file_io_order: List[str] | None = None,
    ):
        fo_list = [item["qualified_name"] for item in func_data]
        fo_index = {name: i for i, name in enumerate(fo_list)}
        n = len(fo_list)

        # Нумерация ИО строго как в Перечень_ИО.csv (без параметров).
        info_index = self._filtered_info_index(info_data)
        file_index = self._file_io_index(info_data, file_flow_data, file_io_order)

        # direct[r][c]   = ИО-номера через прямой доступ к общей переменной
        # arg[r][c]      = ИО-номера через передачу аргументом
        # fileflow[r][c] = ИО-номера файлов, через которые связаны функции
        sparse_d, direct = self._make_matrix(n)
        sparse_a, arg    = self._make_matrix(n)
        sparse_f, fileflow = self._make_matrix(n)

        # Прямые обращения к общим переменным (глобальные, поля классов)
        var_to_funcs: Dict[str, set] = {}
        for item in data_matrix_data:
            var_to_funcs.setdefault(item["variable_name"], set()).add(item["function_name"])

        for var, funcs in var_to_funcs.items():
            if var not in info_index:
                continue
            vnum = info_index[var]
            fl = sorted(funcs)
            for f1 in fl:
                for f2 in fl:
                    i1, i2 = fo_index.get(f1), fo_index.get(f2)
                    if i1 is not None and i2 is not None:
                        self._matrix_add(sparse_d, direct, i1, i2, vnum)

        # Потоки через передачу аргументов (caller → callee)
        # Обозначение: номер ИО с суффиксом «*»  (например, «39*»)
        if arg_flow_data:
            for item in arg_flow_data:
                caller_var = item.get("caller_var", "")
                if caller_var not in info_index:
                    continue
                ic = fo_index.get(item.get("caller_name", ""))
                ie = fo_index.get(item.get("callee_name", ""))
                if ic is not None and ie is not None:
                    self._matrix_add(sparse_a, arg, ic, ie, info_index[caller_var])

        # Связи через файлы: функции, обращающиеся к одному файлу, связаны
        # по информации (запись→чтение или совместный доступ) — симметрично,
        # как разделяемая переменная. Обозначение — суффикс «ф».
        if file_flow_data:
            file_to_funcs: Dict[str, set] = {}
            for item in file_flow_data:
                fn = item.get("file_name", "")
                if fn in file_index:
                    file_to_funcs.setdefault(fn, set()).add(item.get("function_name", ""))
            for fn, funcs in file_to_funcs.items():
                fnum = file_index[fn]
                fl = sorted(funcs)
                for f1 in fl:
                    for f2 in fl:
                        i1, i2 = fo_index.get(f1), fo_index.get(f2)
                        if i1 is not None and i2 is not None:
                            self._matrix_add(sparse_f, fileflow, i1, i2, fnum)

        # Формирование строки-метки ячейки из наборов direct/arg/file.
        def cell_label(d_set, a_set, f_set):
            all_nums = d_set | a_set | f_set
            if not all_nums:
                return ""
            parts = []
            for num in sorted(all_nums):
                if num in f_set:
                    parts.append(f"{num}ф")
                elif num in a_set:
                    parts.append(f"{num}*")
                else:
                    parts.append(str(num))
            return ",".join(parts)

        fname = "Матрица_связей_ФО(процедур_функций)_по_информации.csv"

        # Большие проекты — разреженный список рёбер: только связанные пары ФО.
        if n > self._SPARSE_THRESHOLD:
            all_keys = set(direct.keys() if sparse_d else []) | \
                       set(arg.keys() if sparse_a else []) | \
                       set(fileflow.keys() if sparse_f else [])

            def edge_rows():
                for (r, c) in sorted(all_keys):
                    lbl = cell_label(
                        self._matrix_get(sparse_d, direct, r, c),
                        self._matrix_get(sparse_a, arg, r, c),
                        self._matrix_get(sparse_f, fileflow, r, c),
                    )
                    if lbl:
                        yield [r + 1, c + 1, lbl]

            self._write_csv_stream(
                fname,
                ["ФО_источник", "ФО_приёмник", "ИО (через что связаны)"],
                edge_rows(),
            )
            return

        # Малые проекты — привычный плотный матричный вид.
        matrix: List[List[str]] = [["" for _ in range(n)] for _ in range(n)]
        for r in range(n):
            for c in range(n):
                matrix[r][c] = cell_label(direct[r][c], arg[r][c], fileflow[r][c])

        headers = [""]
        for i, name in enumerate(fo_list, 1):
            headers.append(f"({i}){name}")
        rows = []
        for i, name in enumerate(fo_list, 1):
            row = [f"({i}){name}"]
            row.extend(matrix[i - 1])
            rows.append(row)
        self._write_csv(fname, headers, rows)

    def add_execution_routes(
        self,
        func_data: List[Dict[str, str]],
        routes_by_func: Dict[str, List[Dict]],
    ):
        """Страница 1: маршруты ветвлений внутри каждого ФО."""
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data)}
        rows = []
        for seq, item in enumerate(func_data, 1):
            fname = item["qualified_name"]
            fnum  = seq
            routes = (routes_by_func.get(f"{fnum}|{fname}")        # новый ключ
                      or routes_by_func.get(fname)                 # legacy-ключ
                      or [{"route_num": 1, "route_str": "Начало->Конец", "calls": [fnum]}])
            for r_idx, r in enumerate(routes):
                rows.append([
                    seq        if r_idx == 0 else "",
                    fnum       if r_idx == 0 else "",
                    fname      if r_idx == 0 else "",
                    r["route_num"],
                    r["route_str"],
                ])
        self._write_csv(
            "Маршруты_выполнения_ФО(ветвей).csv",
            ["№ п/п", "№ ФО", "Функциональный объект", "№ маршрута", "Маршрут"],
            rows,
        )

    def add_call_routes(
        self,
        func_data: List[Dict[str, str]],
        routes_by_func: Dict[str, List[Dict]],
    ):
        """Страница 2: маршруты как последовательности номеров ФО, с объединением одинаковых."""
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data)}
        rows = []
        for seq, item in enumerate(func_data, 1):
            fname = item["qualified_name"]
            fnum  = seq
            routes = (routes_by_func.get(f"{fnum}|{fname}")        # новый ключ
                      or routes_by_func.get(fname)                 # legacy-ключ
                      or [{"route_num": 1, "calls": [fnum]}])

            # Группируем маршруты с одинаковой цепочкой вызовов
            groups: Dict[tuple, List[int]] = {}
            for r in routes:
                key = tuple(r["calls"])
                groups.setdefault(key, []).append(r["route_num"])

            for g_idx, (calls_key, route_nums) in enumerate(groups.items()):
                call_str  = "->".join(f"({n})" for n in calls_key)
                rnum_str  = ",".join(str(n) for n in route_nums)
                rows.append([
                    seq        if g_idx == 0 else "",
                    fnum       if g_idx == 0 else "",
                    fname      if g_idx == 0 else "",
                    rnum_str,
                    call_str,
                ])
        self._write_csv(
            "Маршруты_выполнения_ФО(процедур_функций).csv",
            ["№ п/п", "№ ФО", "Функциональный объект", "№ маршрута", "Маршрут"],
            rows,
        )

    def add_critical_routes(
        self,
        func_data: List[Dict[str, str]],
        routes_by_func: Dict[str, List[Dict]],
        branch_inventory_by_func: Dict[str, List[Dict]],
        info_data: List[Dict[str, str]],
        data_matrix_data: List[Dict[str, str]],
        sig_data: List[Dict[str, str]],
        critical_io_nums: set,
    ):
        """Выделяет маршруты выполнения, на которых есть критический ИО ИЛИ опасная
        конструкция (критерий — ИЛИ).

        Сопоставление «точка → ветвь → маршрут»:
          - строка использования критического ИО / опасной конструкции отображается
            в самую вложенную ветвь ФО, чей диапазон строк [line..line_end] её содержит;
          - код вне ветвей (ствол ФО) принадлежит ВСЕМ маршрутам ФО;
          - маршрут выделяется, если содержит эту ветвь (её номер есть в conds
            маршрута) либо точка на стволе.

        Критические ИО сопоставляются строго по № ИО (как в Перечень_ИО.csv).
        """
        info_index = self._filtered_info_index(info_data)        # var_name -> № ИО
        crit_nums = set(critical_io_nums or set())

        # Использования критических ИО по функциям: fname -> [(№ИО, строка)]
        crit_points: Dict[str, list] = {}
        for item in data_matrix_data or []:
            num = info_index.get(item.get("variable_name", ""))
            if num is None or num not in crit_nums:
                continue
            try:
                line = int(item.get("access_line", 0) or 0)
            except (ValueError, TypeError):
                continue
            crit_points.setdefault(item.get("function_name", ""), []).append((num, line))

        # Опасные конструкции по функциям: fname -> [(метка, строка)]
        danger_points: Dict[str, list] = {}
        for item in sig_data or []:
            try:
                line = int(item.get("line", 0) or 0)
            except (ValueError, TypeError):
                continue
            label = "/".join(x for x in (item.get("cwe", ""), item.get("category", "")) if x) \
                or item.get("signature", "")
            danger_points.setdefault(item.get("function_name", ""), []).append((label, line))

        def enclosing_branch(spans, line):
            """Самая вложенная ветвь (макс. line_start), чей [start..end] содержит
            line; None — точка на стволе ФО (вне ветвей)."""
            best = None
            for num, start, end in spans:
                if start <= line <= end and (best is None or start > best[1]):
                    best = (num, start, end)
            return best[0] if best else None

        def route_branch_nums(route):
            nums = set()
            for c in route.get("conds", []):  # conds: (stype, num, outcome), кортеж/список
                if isinstance(c, (list, tuple)) and len(c) >= 2:
                    try:
                        nums.add(int(c[1]))
                    except (ValueError, TypeError):
                        pass
            return nums

        rows = []
        seq = 0
        for fidx, item in enumerate(func_data, 1):
            fname = item["qualified_name"]
            fnum = fidx
            if fname not in crit_points and fname not in danger_points:
                continue  # в ФО нет ни критических ИО, ни опасных конструкций
            key = f"{fnum}|{fname}"
            routes = (routes_by_func.get(key) or routes_by_func.get(fname)
                      or [{"route_num": 1, "route_str": "Начало->Конец", "conds": []}])
            inv = branch_inventory_by_func.get(key) or branch_inventory_by_func.get(fname) or []
            spans = []
            for br in inv:
                try:
                    spans.append((int(br["num"]), int(br.get("line", 0) or 0),
                                  int(br.get("line_end", br.get("line", 0)) or 0)))
                except (ValueError, TypeError, KeyError):
                    continue
            cpts = crit_points.get(fname, [])
            dpts = danger_points.get(fname, [])
            for route in routes:
                rbn = route_branch_nums(route)

                def on_route(line):
                    enc = enclosing_branch(spans, line)
                    return enc is None or enc in rbn

                crit_hit = sorted({f"{n}@{ln}" for (n, ln) in cpts if on_route(ln)})
                dang_hit = sorted({f"{lbl}@{ln}" for (lbl, ln) in dpts if on_route(ln)})
                if not crit_hit and not dang_hit:
                    continue
                seq += 1
                rows.append([
                    seq, fnum, fname,
                    route.get("route_num", ""), route.get("route_str", ""),
                    "; ".join(crit_hit), "; ".join(dang_hit),
                ])
        self._write_csv(
            "Критические_маршруты.csv",
            ["№ п/п", "№ ФО", "Функциональный объект", "№ маршрута", "Маршрут",
             "Критические ИО на маршруте", "Опасные конструкции на маршруте"],
            rows,
        )

    # ── Перечень файлов (модулей) ─────────────────────────────────────────────

    @staticmethod
    def _relpath(abs_path: str, root_name: str) -> str:
        """Относительный путь файла от корня исходников (root_name)."""
        norm = abs_path.replace("\\", "/")
        marker = "/" + root_name + "/"
        idx = norm.rfind(marker)
        if idx >= 0:
            return norm[idx + len(marker):]
        return norm.rsplit("/", 1)[-1]

    def add_file_list(self, files: List[Dict[str, str]], source_dir: str):
        """Перечень файлов, участвующих в сборке. Возвращает (ordered, by_abs_path)."""
        root_name = Path(source_dir).name
        ordered: List[Dict[str, Any]] = []
        by_abs_path: Dict[str, int] = {}
        for i, f in enumerate(files, 1):
            rel = self._relpath(f.get("abs_path", ""), root_name)
            base = f.get("base_name", "")
            abs_path = f.get("abs_path", "")
            ordered.append({"id": i, "rel": rel, "base": base, "abs_path": abs_path})
            by_abs_path[abs_path] = i
        # Используем полный путь вместо относительного
        rows = [[f["id"], f["abs_path"]] for f in ordered]
        self._write_csv("Перечень_ФО(модулей).csv", ["№ п/п", "Файл"], rows)
        return ordered, by_abs_path

    def _filtered_info_index(self, info_data: List[Dict[str, str]]) -> Dict[str, int]:
        """Нумерация ИО-переменных как в Перечень_ИО.csv (без параметров)."""
        filtered = [it for it in info_data if it.get("kind") != "parameter"]
        return {it["qualified_name"]: i + 1 for i, it in enumerate(filtered)}

    @staticmethod
    def _file_io_order(file_flow_data: List[Dict[str, str]]) -> List[str]:
        """Уникальные имена файлов-ИО в порядке первого появления."""
        order: List[str] = []
        seen: set = set()
        for r in (file_flow_data or []):
            fn = r.get("file_name", "")
            if fn and fn not in seen:
                seen.add(fn)
                order.append(fn)
        return order

    def _file_io_index(
        self,
        info_data: List[Dict[str, str]],
        file_flow_data: List[Dict[str, str]],
        file_io_order: List[str] | None = None,
    ) -> Dict[str, int]:
        """Нумерация файлов-ИО: продолжается после ИО-переменных (без параметров)."""
        base = len([it for it in info_data if it.get("kind") != "parameter"])
        order = file_io_order if file_io_order is not None else self._file_io_order(file_flow_data)
        return {fn: base + i + 1 for i, fn in enumerate(order)}

    # ── Матрицы связей модулей ────────────────────────────────────────────────

    def add_module_control_matrix(
        self,
        func_data: List[Dict[str, str]],
        ctrl_data: List[Dict[str, str]],
        file_ordered: List[Dict[str, Any]],
        file_by_base: Dict[str, int],
    ):
        """Матрица связей модулей по управлению. Ячейки — id ФО (callee) по Перечень_ФО.csv."""
        func_index = {it["qualified_name"]: i + 1 for i, it in enumerate(func_data)}
        func_file = {it["qualified_name"]: it.get("file", "") for it in func_data}
        n = len(file_ordered)
        pos = {f["id"]: idx for idx, f in enumerate(file_ordered)}

        # Точная нумерация callee по (имя, файл объявления); модуль callee —
        # прямо из callee_file (control_matrix.ql). Fallback'и — для legacy-данных.
        num_by_nf = {(it["qualified_name"], it.get("file", "")): i + 1
                     for i, it in enumerate(func_data)}

        cells: Dict[tuple, set] = {}
        for item in ctrl_data:
            callee = item.get("callee_name", "")
            callee_file = item.get("callee_file", "")
            caller_mod = file_by_base.get(item.get("caller_file", ""))
            callee_mod = file_by_base.get(callee_file or func_file.get(callee, ""))
            cid = (num_by_nf.get((callee, callee_file)) if callee_file else None) \
                  or func_index.get(callee)
            if not caller_mod or not callee_mod or not cid:
                continue
            cells.setdefault((pos[caller_mod], pos[callee_mod]), set()).add(cid)

        fname = "Матрица_связей_ФО(модулей)_по_управлению.csv"
        ids = [str(f["id"]) for f in file_ordered]

        # Большие проекты — разреженный список рёбер «модуль→модуль (id ФО)».
        if n > self._SPARSE_THRESHOLD:
            def edge_rows():
                for (r, c) in sorted(cells.keys()):
                    s = cells[(r, c)]
                    yield [ids[r], ids[c], ",".join(f"({x})" for x in sorted(s))]
            self._write_csv_stream(
                fname,
                ["Модуль_источник", "Модуль_приёмник", "Вызываемые_ФО"],
                edge_rows(),
            )
            return

        headers = [""] + ids
        rows = []
        for r in range(n):
            row = [ids[r]]
            for c in range(n):
                s = cells.get((r, c))
                row.append(",".join(f"({x})" for x in sorted(s)) if s else "")
            rows.append(row)
        self._write_csv(fname, headers, rows)

    def add_module_data_matrix(
        self,
        func_data: List[Dict[str, str]],
        info_data: List[Dict[str, str]],
        data_data: List[Dict[str, str]],
        arg_flow_data: List[Dict[str, str]],
        file_ordered: List[Dict[str, Any]],
        file_by_base: Dict[str, int],
        file_flow_data: List[Dict[str, str]] = None,
        file_io_order: List[str] | None = None,
    ):
        """Матрица связей модулей по информации. Ячейки — id ИО по Перечень_ИО.csv (* — аргумент, ф — файл)."""
        info_index = self._filtered_info_index(info_data)
        file_index = self._file_io_index(info_data, file_flow_data, file_io_order)
        func_file = {it["qualified_name"]: it.get("file", "") for it in func_data}
        n = len(file_ordered)
        pos = {f["id"]: idx for idx, f in enumerate(file_ordered)}

        sparse_d, direct = self._make_matrix(n)
        sparse_a, arg    = self._make_matrix(n)
        sparse_f, fileflow = self._make_matrix(n)

        # Прямой доступ: переменная, к которой обращаются функции из разных модулей
        var_mods: Dict[str, set] = {}
        for item in data_data:
            var = item.get("variable_name", "")
            if var not in info_index:
                continue
            mod = file_by_base.get(item.get("func_file", ""))
            if mod:
                var_mods.setdefault(var, set()).add(mod)
        for var, mods in var_mods.items():
            vid = info_index[var]
            ml = sorted(mods)
            for m1 in ml:
                for m2 in ml:
                    self._matrix_add(sparse_d, direct, pos[m1], pos[m2], vid)

        # Передача аргументом: caller-модуль → callee-модуль
        if arg_flow_data:
            for item in arg_flow_data:
                cv = item.get("caller_var", "")
                if cv not in info_index:
                    continue
                cmod = file_by_base.get(item.get("caller_file", ""))
                emod = file_by_base.get(func_file.get(item.get("callee_name", ""), ""))
                if cmod and emod:
                    self._matrix_add(sparse_a, arg, pos[cmod], pos[emod], info_index[cv])

        # Связь модулей через файлы (по func_file обращающихся функций)
        if file_flow_data:
            file_to_mods: Dict[str, set] = {}
            for item in file_flow_data:
                fn = item.get("file_name", "")
                if fn not in file_index:
                    continue
                mod = file_by_base.get(item.get("func_file", ""))
                if mod:
                    file_to_mods.setdefault(fn, set()).add(mod)
            for fn, mods in file_to_mods.items():
                fnum = file_index[fn]
                ml = sorted(mods)
                for m1 in ml:
                    for m2 in ml:
                        self._matrix_add(sparse_f, fileflow, pos[m1], pos[m2], fnum)

        def cell_label(d_set, a_set, f_set):
            all_nums = d_set | a_set | f_set
            if not all_nums:
                return ""
            parts = []
            for num in sorted(all_nums):
                if num in f_set:
                    parts.append(f"{num}ф")
                elif num in a_set:
                    parts.append(f"{num}*")
                else:
                    parts.append(str(num))
            return ",".join(parts)

        fname = "Матрица_связей_ФО(модулей)_по_информации.csv"
        ids = [str(f["id"]) for f in file_ordered]

        # Большие проекты — разреженный список рёбер «модуль→модуль (id ИО)».
        if n > self._SPARSE_THRESHOLD:
            all_keys = set(direct.keys() if sparse_d else []) | \
                       set(arg.keys() if sparse_a else []) | \
                       set(fileflow.keys() if sparse_f else [])

            def edge_rows():
                for (r, c) in sorted(all_keys):
                    lbl = cell_label(
                        self._matrix_get(sparse_d, direct, r, c),
                        self._matrix_get(sparse_a, arg, r, c),
                        self._matrix_get(sparse_f, fileflow, r, c),
                    )
                    if lbl:
                        yield [ids[r], ids[c], lbl]

            self._write_csv_stream(
                fname,
                ["Модуль_источник", "Модуль_приёмник", "ИО (через что связаны)"],
                edge_rows(),
            )
            return

        headers = [""] + ids
        rows = []
        for r in range(n):
            row = [ids[r]]
            for c in range(n):
                row.append(cell_label(direct[r][c], arg[r][c], fileflow[r][c]))
            rows.append(row)
        self._write_csv(fname, headers, rows)

    # ── Сигнатурный анализ кода (этап 1: поиск ПОК) ───────────────────────────

    def add_signature_analysis(
        self,
        sig_data: List[Dict[str, str]],
        func_data: List[Dict[str, str]],
        file_by_base: Dict[str, int],
        source_by_base: Dict[str, List[str]] = None,
        rule_source: str = "cpp-queries",
    ):
        """Плоский перечень потенциально опасных конструкций (ПОК) с привязкой к ФО/модулю."""
        func_index = {it["qualified_name"]: i + 1 for i, it in enumerate(func_data)}

        def fragment(func_file: str, line: str) -> str:
            if not source_by_base:
                return ""
            lines = source_by_base.get(func_file)
            try:
                ln = int(line) - 1
            except (ValueError, TypeError):
                return ""
            if lines and 0 <= ln < len(lines):
                return lines[ln].strip()
            return ""

        rows = []
        for i, item in enumerate(sig_data, 1):
            fname = item.get("function_name", "")
            ffile = item.get("func_file", "")
            line  = item.get("line", "")
            fnum  = func_index.get(fname)
            mnum  = file_by_base.get(ffile)
            fo_fmt  = f"({fnum}){fname}" if fnum else fname
            mod_fmt = f"({mnum}){ffile}" if mnum else ffile
            rows.append([
                i,
                item.get("cwe", ""),
                item.get("category", ""),
                item.get("signature", ""),
                mod_fmt,
                fo_fmt,
                f"{ffile}:{line}",
                fragment(ffile, line),
                rule_source,
            ])
        self._write_csv(
            "Сигнатурный_анализ_кода.csv",
            ["№ п/п", "CWE", "Категория ПОК", "Сигнатура", "Модуль", "ФО",
             "Местоположение", "Фрагмент кода", "Источник правила"],
            rows,
        )

    def add_signature_summary(self, sig_data: List[Dict[str, str]]):
        """Сводка ПОК по категориям CWE."""
        agg: Dict[tuple, int] = {}
        for item in sig_data:
            key = (item.get("cwe", ""), item.get("category", ""))
            agg[key] = agg.get(key, 0) + 1
        rows = []
        for i, ((cwe, cat), cnt) in enumerate(sorted(agg.items()), 1):
            rows.append([i, cwe, cat, cnt])
        rows.append(["", "", "ВСЕГО", sum(agg.values())])
        self._write_csv(
            "Сигнатурный_анализ_сводка.csv",
            ["№ п/п", "CWE", "Категория ПОК", "Количество"],
            rows,
        )

    # ── Графы маршрутов ───────────────────────────────────────────────────

    def add_function_graph(self, function_edges: List[Dict], func_index: Dict[str, int] = None,
                           func_data: List[Dict[str, str]] = None):
        """Сохранить граф функций.

        Номер ФО определяется по (имя, файл объявления) — рёбра содержат
        from_file/to_file из control_matrix.ql, поэтому одноимённые функции
        получают СВОИ номера. Fallback по имени — для legacy-данных без файлов.
        """
        num_by_nf = {(it["qualified_name"], it.get("file", "")): i + 1
                     for i, it in enumerate(func_data or [])}

        def _num(name, file):
            n = num_by_nf.get((name, file)) if file else None
            if n:
                return n
            return func_index.get(name, "") if func_index else ""

        rows = []
        for i, edge in enumerate(function_edges, 1):
            from_num = _num(edge["from_func"], edge.get("from_file", ""))
            to_num = _num(edge["to_func"], edge.get("to_file", ""))
            rows.append([
                i,
                from_num,
                edge["from_func"],
                to_num,
                edge["to_func"],
                edge["call_type"],
                edge.get("count", 1),
            ])
        headers = ["№ п/п", "№ От ФО", "От ФО", "№ К ФО", "К ФО", "Тип связи", "Вызовов"]
        self._write_csv("Граф_функций.csv", headers, rows)

    def add_branch_graph(self, branch_graph: Dict[str, List[Dict]], func_index: Dict[str, int] = None):
        """Сохранить графы ветвей для каждой функции.

        Ключ branch_graph — '<номер_ФО>|<имя>' (func_key.py); номер берём из
        ключа (уникален даже для одноимённых функций). Для legacy-ключей
        (просто имя, старые project.db) номер ищем по func_index.
        """
        def _parts(key):
            num, name = split_func_key(key)
            if not num and func_index:
                num = func_index.get(name, "")
            return num, name

        rows = []
        row_num = 1
        for fkey in sorted(branch_graph.keys(), key=lambda k: (_parts(k)[0] or 0, _parts(k)[1])):
            func_num, func_name = _parts(fkey)
            edges = branch_graph[fkey]
            for edge in edges:
                rows.append([
                    row_num,
                    func_num,
                    func_name,
                    edge["from_branch"],
                    edge["to_branch"],
                    edge["transition_type"],
                    edge.get("contains_call", ""),
                ])
                row_num += 1
        self._write_csv(
            "Граф_ветвей.csv",
            ["№ п/п", "№ ФО", "ФО", "От ветки", "К ветке", "Тип перехода", "Содержит вызов"],
            rows,
        )

    def add_branch_inventory(self, branch_inventory: Dict[str, List[Dict]],
                             func_index: Dict[str, int] = None,
                             func_file: Dict[str, str] = None,
                             func_data: List[Dict[str, str]] = None):
        """Сохранить Перечень ветвей: последовательный номер ветви (#N, как в
        Граф_ветвей и на блок-схемах) и местоположение в исходниках.

        Нужен для сверки: ветви статики и динамики должны совпадать по составу,
        нумерации (#N) и количеству.

        Ключ branch_inventory — '<номер_ФО>|<имя>' (func_key.py): номер и файл
        берём по номеру из ключа (точно даже для одноимённых функций). Для
        legacy-ключей (просто имя) — fallback на func_index/func_file по имени.
        """
        func_file = func_file or {}
        file_by_num = {i + 1: it.get("file", "") for i, it in enumerate(func_data or [])}

        def _parts(key):
            num, name = split_func_key(key)
            if not num and func_index:
                try:
                    num = int(func_index.get(name, 0) or 0)
                except (ValueError, TypeError):
                    num = 0
            return num, name

        rows = []
        row_num = 1
        # Сортировка по номеру ФО, затем по номеру ветви
        for fkey in sorted(branch_inventory.keys(), key=lambda k: (_parts(k)[0], _parts(k)[1])):
            func_num, func_name = _parts(fkey)
            path = file_by_num.get(func_num) or func_file.get(func_name, "")
            func_num = func_num or ""
            for br in branch_inventory[fkey]:
                rows.append([
                    row_num,
                    func_num,
                    func_name,
                    br["num"],
                    br["type"],
                    path,
                    br["line"],
                ])
                row_num += 1
        self._write_csv(
            "Перечень_ветвей.csv",
            ["№ п/п", "№ ФО", "ФО", "№ ветви", "Тип", "Файл", "Строка"],
            rows,
        )

    def add_route_graph(self, route_edges: List[Dict], func_index: Dict[str, int] = None):
        """Сохранить граф маршрутов (функция, ветка)."""
        rows = []
        for i, edge in enumerate(route_edges, 1):
            from_num = func_index.get(edge["from_func"], "") if func_index else ""
            to_num = func_index.get(edge["to_func"], "") if func_index else ""
            rows.append([
                i,
                from_num,
                edge["from_func"],
                edge["from_branch"],
                to_num,
                edge["to_func"],
                edge["to_branch"],
                edge["link_type"],
                edge.get("description", ""),
            ])
        self._write_csv(
            "Граф_маршрутов.csv",
            ["№ п/п", "№ От ФО", "От ФО", "От ветка", "№ К ФО", "К ФО", "К ветка", "Тип связи", "Описание"],
            rows,
        )

    def save(self):
        pass
