"""Построение трёх типов графов маршрутов: функций, ветвей, маршрутов."""

from typing import List, Dict, Set, Tuple
from collections import defaultdict, deque

from viz.func_key import split_func_key


class GraphBuilder:
    """Строит графы маршрутов для анализа потоков управления."""

    def __init__(self):
        self.function_edges: List[Dict] = []  # граф функций
        self.branch_edges: Dict[str, List[Dict]] = defaultdict(list)  # граф ветвей (по функциям)
        self.route_edges: List[Dict] = []  # граф маршрутов (функция, ветка)

    # ── Граф функций ───────────────────────────────────────────────────────

    def add_function_edge(self, from_func: str, to_func: str, call_type: str = "прямой"):
        """Добавить ребро в граф функций."""
        self.function_edges.append({
            "from_func": from_func,
            "to_func": to_func,
            "call_type": call_type,
        })

    def build_function_graph(self, control_data: List[Dict]) -> List[Dict]:
        """Построить граф функций из данных вызовов.

        Количество вызовов каждой пары считается одним проходом по словарю —
        раньше для каждого уникального ребра выполнялся полный скан control_data
        (O(E×E_uniq)), что на крупных проектах растягивало построение на часы.

        Пары различаются с учётом файлов объявления (caller_file/callee_file из
        control_matrix.ql): одноимённые функции из разных файлов дают РАЗНЫЕ
        рёбра. Для legacy-данных без callee_file файл пуст — пары схлопываются
        по имени, как раньше.
        """
        counts: Dict[tuple, int] = {}
        for call in control_data:
            from_func = call.get("caller_name", "")
            to_func = call.get("callee_name", "")
            if not from_func or not to_func:
                continue
            key = (from_func, call.get("caller_file", ""),
                   to_func, call.get("callee_file", ""))
            counts[key] = counts.get(key, 0) + 1

        # dict сохраняет порядок вставки — порядок рёбер как у первого вызова пары.
        # Рекурсия — то же имя И тот же файл (или файлы неизвестны):
        # одноимённые функции из разных файлов — это «прямой» вызов тёзки.
        edges = [
            {
                "from_func": from_func,
                "from_file": from_file,
                "to_func": to_func,
                "to_file": to_file,
                "call_type": ("рекурсия"
                              if from_func == to_func
                              and (not from_file or not to_file or from_file == to_file)
                              else "прямой"),
                "count": cnt,
            }
            for (from_func, from_file, to_func, to_file), cnt in counts.items()
        ]

        self.function_edges = edges
        return edges

    # ── Граф ветвей ───────────────────────────────────────────────────────

    def add_branch_edge(self, func_name: str, from_branch: str, to_branch: str,
                       transition_type: str = "условный", contains_call: str = ""):
        """Добавить ребро в граф ветвей функции."""
        self.branch_edges[func_name].append({
            "from_branch": from_branch,
            "to_branch": to_branch,
            "transition_type": transition_type,
            "contains_call": contains_call,
        })

    def build_branch_graph(self, func_data: List[Dict], routes_by_func: Dict,
                           branch_edges_by_func: Dict = None) -> Dict[str, List[Dict]]:
        """Построить граф ветвей для каждой функции.

        Граф ветвей: переходы между ветками условий внутри функции.

        Если передан branch_edges_by_func (полный структурный граф переходов,
        вычисленный по иерархии в flowchart_generator), используем его напрямую —
        он покрывает ВСЕ ветки. Иначе (обратная совместимость) извлекаем переходы
        из маршрутов, что для функций с экспоненциальным ветвлением неполно
        из-за ограничения числа маршрутов.

        Ключи словарей — '<номер_ФО>|<имя>' (func_key.py) либо legacy-имя;
        здесь они прозрачно передаются дальше (декодируют потребители).
        """
        if branch_edges_by_func:
            # Гарантируем непустой граф для функций без ветвлений
            branch_graph = {}
            for func_name, edges in branch_edges_by_func.items():
                branch_graph[func_name] = edges if edges else [{
                    "from_branch": "entry", "to_branch": "return",
                    "transition_type": "прямой", "contains_call": "",
                }]
            self.branch_edges = branch_graph
            return branch_graph

        branch_graph = {}

        for func_name, routes in routes_by_func.items():
            edges = []
            seen = set()

            # Из каждого маршрута извлечём переходы между ветками
            for route in routes:
                conds = route.get("conds", [])  # [(stype, num, outcome), ...]
                calls = route.get("calls", [])

                # Построить цепочку переходов: entry → if#1 → if#2 → ... → return
                current = "entry"
                for i, (stype, num, outcome) in enumerate(conds):
                    branch_id = f"{stype}#{num}-{outcome}"

                    key = (current, branch_id)
                    if key not in seen:
                        seen.add(key)
                        edges.append({
                            "from_branch": current,
                            "to_branch": branch_id,
                            "transition_type": "ветвление" if i == 0 else "условный",
                            "contains_call": "",
                        })

                    current = branch_id

                # Переход к return
                key = (current, "return")
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "from_branch": current,
                        "to_branch": "return",
                        "transition_type": "возврат",
                        "contains_call": "",
                    })

            if not edges:
                # Пустая функция или без ветвлений
                edges.append({
                    "from_branch": "entry",
                    "to_branch": "return",
                    "transition_type": "прямой",
                    "contains_call": "",
                })

            branch_graph[func_name] = edges

        self.branch_edges = branch_graph
        return branch_graph

    # ── Граф маршрутов (функция, ветка) ───────────────────────────────────

    def add_route_edge(self, from_func: str, from_branch: str, to_func: str, to_branch: str,
                      link_type: str, description: str = ""):
        """Добавить ребро в граф маршрутов."""
        self.route_edges.append({
            "from_func": from_func,
            "from_branch": from_branch,
            "to_func": to_func,
            "to_branch": to_branch,
            "link_type": link_type,
            "description": description,
        })

    def build_route_graph(self, func_data: List[Dict], control_data: List[Dict],
                         branch_graph: Dict) -> List[Dict]:
        """Построить граф маршрутов: (функция, ветка) → (функция, ветка).

        Граф маршрутов объединяет функции и ветви, показывая как они взаимодействуют.
        """
        edges = []
        seen = set()

        # Шаг 1: Внутри каждой функции - переходы между ветками.
        # Ключ branch_graph — '<номер_ФО>|<имя>' или legacy-имя: декодируем имя.
        for fkey, func_branches in branch_graph.items():
            func_name = split_func_key(fkey)[1]
            for edge in func_branches:
                key = (func_name, edge["from_branch"], func_name, edge["to_branch"])
                if key not in seen:
                    seen.add(key)
                    edges.append({
                        "from_func": func_name,
                        "from_branch": edge["from_branch"],
                        "to_func": func_name,
                        "to_branch": edge["to_branch"],
                        "link_type": edge["transition_type"],
                        "description": f"переход в {func_name}",
                    })

        # Шаг 2: Между функциями - вызовы
        for call in control_data:
            from_func = call.get("caller_name", "")
            to_func = call.get("callee_name", "")
            if not from_func or not to_func:
                continue

            # Вызов может быть в разных ветках from_func, входит в entry to_func
            # Упрощённо: вызов переходит из from_func в entry to_func
            key = (from_func, "entry", to_func, "entry")
            if key not in seen:
                seen.add(key)
                edges.append({
                    "from_func": from_func,
                    "from_branch": "entry",
                    "to_func": to_func,
                    "to_branch": "entry",
                    "link_type": "вызов",
                    "description": f"вызов {to_func}",
                })

            # Возврат из to_func в from_func
            key = (to_func, "return", from_func, "entry")
            if key not in seen:
                seen.add(key)
                edges.append({
                    "from_func": to_func,
                    "from_branch": "return",
                    "to_func": from_func,
                    "to_branch": "entry",
                    "link_type": "возврат",
                    "description": f"возврат в {from_func}",
                })

        self.route_edges = edges
        return edges

    # ── Поиск маршрутов (BFS) ─────────────────────────────────────────────

    def find_function_routes(self, from_func: str, to_func: str, max_depth: int = 10) -> List[List[str]]:
        """Найти все пути в графе функций от from_func к to_func."""
        # Построить граф смежности
        graph = defaultdict(list)
        for edge in self.function_edges:
            graph[edge["from_func"]].append(edge["to_func"])

        paths = []

        def dfs(current, target, path, visited, depth):
            if depth > max_depth:
                return
            if current == target:
                paths.append(path + [current])
                return

            for next_node in graph[current]:
                if next_node not in visited:
                    visited.add(next_node)
                    dfs(next_node, target, path + [current], visited, depth + 1)
                    visited.remove(next_node)

        dfs(from_func, to_func, [], {from_func}, 0)
        return paths

    def find_branch_routes(self, func_name: str) -> List[List[str]]:
        """Найти все пути в графе ветвей от entry к return."""
        edges = self.branch_edges.get(func_name, [])
        graph = defaultdict(list)

        for edge in edges:
            graph[edge["from_branch"]].append(edge["to_branch"])

        paths = []

        def dfs(current, path):
            if current == "return":
                paths.append(path + [current])
                return

            for next_node in graph[current]:
                dfs(next_node, path + [current])

        dfs("entry", [])
        return paths

    def find_route_paths(self, from_node: Tuple[str, str], to_node: Tuple[str, str],
                        max_depth: int = 10) -> List[List[Tuple[str, str]]]:
        """Найти пути в графе маршрутов от (от_func, от_ветка) к (к_func, к_ветка)."""
        # Построить граф смежности
        graph = defaultdict(list)
        for edge in self.route_edges:
            graph[(edge["from_func"], edge["from_branch"])].append(
                (edge["to_func"], edge["to_branch"])
            )

        paths = []

        def dfs(current, target, path, visited, depth):
            if depth > max_depth:
                return
            if current == target:
                paths.append(path + [current])
                return

            for next_node in graph[current]:
                if next_node not in visited:
                    visited.add(next_node)
                    dfs(next_node, target, path + [current], visited, depth + 1)
                    visited.remove(next_node)

        dfs(from_node, to_node, [], {from_node}, 0)
        return paths
