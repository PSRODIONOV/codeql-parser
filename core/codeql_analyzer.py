import csv
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import third_party, PROJECT_ROOT


QUERY_MAP: Dict[str, str] = {
    "functional": "functional_objects.ql",
    "info":       "info_objects.ql",
    "files":      "files.ql",
    "control":    "control_matrix.ql",
    "data":       "data_matrix.ql",
    "arg_flow":   "arg_flow.ql",
    "file_flow":  "file_flow.ql",
    "signature":  "signature_analysis.ql",
    "flow":       "function_flow_v2.ql",
}


def _find_codeql(codeql_path: str) -> str:
    """Находит исполняемый файл CodeQL: по указанному пути, в PATH или локально."""
    # Существующий путь нормализуем в абсолютный: относительный путь с прямым
    # слэшем ('codeql-win/codeql.exe') Windows CreateProcess не принимает
    # (FileNotFoundError), хотя файл существует.
    if os.path.exists(codeql_path):
        return str(Path(codeql_path).resolve())
    if os.path.isabs(codeql_path):
        return codeql_path
    # Ищем в PATH
    find_cmd = "where" if os.name == "nt" else "which"
    try:
        cmd = subprocess.run([find_cmd, codeql_path], capture_output=True, text=True)
        if cmd.returncode == 0:
            return cmd.stdout.strip().splitlines()[0]
    except FileNotFoundError:
        pass
    # Локальный fallback — заимствованный CodeQL в third-party/
    if os.name == "nt":
        local_candidates = [
            third_party("codeql-win", "codeql.exe"),
            third_party("codeql-win", "codeql.cmd"),
            third_party("codeql-linux", "codeql"),
        ]
    else:
        local_candidates = [
            third_party("codeql-linux", "codeql"),
        ]
    for candidate in local_candidates:
        if candidate.exists():
            return str(candidate)
    return codeql_path


class CodeQLAnalyzer:
    """Выполняет QL-запросы к CodeQL БД и парсит результаты."""

    def __init__(self, db_path: str, codeql_path: str = "codeql", language: str = "cpp", path_pattern: str = "", work_dir: str = None, ram_mb: int = 4096):
        self.db_path = Path(db_path).resolve()
        self.codeql = _find_codeql(codeql_path)
        self.language = language
        self.ram_mb = ram_mb
        # Пустой паттерн = «взять все файлы проекта» (matches("%")).
        # ВАЖНО: раньше тут подставлялся дефолт %test-project-<lang>%, из-за чего
        # на реальных проектах (пути не содержат "test-project-...") получалось 0 ФО,
        # хотя БД корректна. Теперь пусто = % (без фильтра), а для точного отбора
        # пользователь задаёт свою маску через --pattern / поле Pattern в GUI.
        self.path_pattern = path_pattern.strip() if path_pattern.strip() else "%"
        # Запросы разложены по языкам: queries/<lang>/*.ql
        self.queries_dir = PROJECT_ROOT / "queries" / language
        if not self.queries_dir.exists():
            raise FileNotFoundError(
                f"Query directory for language '{language}' not found: {self.queries_dir}"
            )
        self.temp_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "codeql_analyzer"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        if not self.db_path.exists():
            raise FileNotFoundError(f"CodeQL database not found: {self.db_path}")

    def _run_query_isolated(self, query_file: str, output_name: str) -> List[Dict[str, str]]:
        """Запускает QL-запрос через CodeQL CLI с изолированным temp dir."""
        query_path = self.queries_dir / query_file
        if not query_path.exists():
            raise FileNotFoundError(f"Query file not found: {query_path}")

        # Подставляем паттерн ВСЕГДА, когда в запросе есть плейсхолдер
        # ${PROJECT_PATTERN} (это whitelist по пути в isProjectFile). Раньше
        # подстановка пропускалась для стандартных масок, из-за чего C++-запросы
        # (где isProjectFile — чёрный список без плейсхолдера) не фильтровали по
        # маске и захватывали системные заголовки (C:/Strawberry/.../include).
        query_content = query_path.read_text(encoding="utf-8")
        temp_query: Path = None
        if "${PROJECT_PATTERN}" in query_content:
            # Пустой паттерн = «взять всё»: matches("%") совпадает с любым путём.
            # Иначе matches("") дало бы 0 файлов (совпадение только с пустой строкой).
            effective_pattern = self.path_pattern.strip() or "%"
            query_content = query_content.replace("${PROJECT_PATTERN}", effective_pattern)
            # Сохраняем в исходной папке с префиксом, чтобы работал qlpack.yml.
            # Имя должно заканчиваться на .ql для CodeQL. PID в имени исключает
            # гонку между параллельными анализами разных проектов (раньше два
            # процесса с разными паттернами перезаписывали один и тот же файл —
            # один из них молча выполнял запрос с чужим фильтром).
            name_without_ext = query_file[:-3]  # убираем .ql
            temp_query = self.queries_dir / f".{name_without_ext}.{os.getpid()}.ql"
            temp_query.write_text(query_content, encoding="utf-8")
            query_to_run = temp_query
        else:
            query_to_run = query_path

        try:
            # Изолированный subdir для каждого запроса (параллельное выполнение)
            subdir = self.temp_dir / output_name
            subdir.mkdir(parents=True, exist_ok=True)
            output_path = subdir / f"{output_name}.csv"
            output_path_bqrs = subdir / f"{output_name}.bqrs"

            # 1. Выполняем запрос, получаем BQRS
            cmd_run = [
                self.codeql, "query", "run",
                str(query_to_run),
                "--database", str(self.db_path),
                "--output", str(output_path_bqrs),
                f"--ram={self.ram_mb}",
                "--threads=0",  # использовать все доступные ядра
            ]
            result_run = subprocess.run(cmd_run, capture_output=True, text=True)
            if result_run.returncode != 0:
                raise RuntimeError(
                    f"CodeQL query run failed for {query_file}:\n"
                    f"stdout: {result_run.stdout}\nstderr: {result_run.stderr}"
                )

            # 2. Декодируем BQRS в CSV
            cmd_decode = [
                self.codeql, "bqrs", "decode",
                str(output_path_bqrs),
                "--format=csv",
                "--output", str(output_path),
            ]
            result_decode = subprocess.run(cmd_decode, capture_output=True, text=True)
            if result_decode.returncode != 0:
                raise RuntimeError(
                    f"CodeQL query decode failed for {query_file}:\n"
                    f"stdout: {result_decode.stdout}\nstderr: {result_decode.stderr}"
                )

            # 3. Читаем CSV
            data: List[Dict[str, str]] = []
            if output_path.exists():
                with open(output_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    headers = next(reader, [])
                    for row in reader:
                        data.append(dict(zip(headers, row)))
            return data
        finally:
            if temp_query is not None:
                try:
                    temp_query.unlink()
                except OSError:
                    pass

    def _run_query(self, query_file: str, output_name: str) -> List[Dict[str, str]]:
        """Обёртка для обратной совместимости."""
        return self._run_query_isolated(query_file, output_name)

    # ── Батч-выполнение (одна загрузка БД) ───────────────────────────────────

    def _prepare_queries(self, tasks: Dict[str, str]):
        """
        Подготавливает query-файлы: подставляет ${PROJECT_PATTERN}.
        Возвращает (dict dataset→Path, список temp-файлов для удаления).
        """
        query_files: Dict[str, Path] = {}
        temp_files: List[Path] = []
        for name, ql_file in tasks.items():
            query_path = self.queries_dir / ql_file
            if not query_path.exists():
                raise FileNotFoundError(f"Query file not found: {query_path}")
            content = query_path.read_text(encoding="utf-8")
            if "${PROJECT_PATTERN}" in content:
                content = content.replace("${PROJECT_PATTERN}", self.path_pattern or "%")
                stem = Path(ql_file).stem
                temp_path = self.queries_dir / f".{stem}.{os.getpid()}.ql"
                temp_path.write_text(content, encoding="utf-8")
                temp_files.append(temp_path)
                query_files[name] = temp_path
            else:
                query_files[name] = query_path
        return query_files, temp_files

    def _decode_bqrs(self, bqrs_path: Path) -> List[Dict[str, str]]:
        """Декодирует BQRS → CSV → список словарей."""
        csv_path = bqrs_path.with_suffix(".csv")
        cmd = [
            self.codeql, "bqrs", "decode",
            str(bqrs_path), "--format=csv", "--output", str(csv_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"bqrs decode failed for {bqrs_path.name}:\n{result.stderr}"
            )
        data: List[Dict[str, str]] = []
        if csv_path.exists():
            with open(csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader, [])
                for row in reader:
                    data.append(dict(zip(headers, row)))
        return data

    def run_batch_queries(self, query_names: Optional[List[str]] = None,
                          log=None) -> Dict[str, List[Dict[str, str]]]:
        """
        Запускает запросы одним вызовом `codeql database run-queries`
        (БД загружается один раз — существенно быстрее N отдельных вызовов).

        query_names: список ключей из QUERY_MAP. None = все доступные.
        log(name, count): опциональный callback — вызывается после декодирования
            каждого датасета с именем ключа и числом строк.
        Возвращает {dataset: rows}.
        """
        tasks = {k: v for k, v in QUERY_MAP.items()
                 if query_names is None or k in query_names}
        if not tasks:
            return {}

        # run-queries всегда пишет результаты в <db>/results/ — флага --output нет.
        db_results_dir = Path(self.db_path) / "results"

        query_files, temp_files = self._prepare_queries(tasks)
        try:
            cmd = [
                self.codeql, "database", "run-queries",
                f"--ram={self.ram_mb}",
                "--threads=0",
                str(self.db_path),
            ] + [str(p) for p in query_files.values()]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"codeql database run-queries failed:\n"
                    f"stdout: {result.stdout}\nstderr: {result.stderr}"
                )

            # run-queries создаёт вложенную структуру внутри <db>/results/.
            # Ищем рекурсивно, индексируем по stem — temp-файлы имеют уникальный
            # PID-суффикс, обычные файлы перезаписываются при каждом запуске.
            bqrs_files = list(db_results_dir.rglob("*.bqrs")) if db_results_dir.exists() else []
            bqrs_by_stem: Dict[str, Path] = {p.stem: p for p in bqrs_files}

            results: Dict[str, List[Dict[str, str]]] = {}
            decode_errors: List[str] = []
            for name, qpath in query_files.items():
                bqrs = bqrs_by_stem.get(qpath.stem)
                if bqrs is None:
                    decode_errors.append(
                        f"BQRS not found for '{name}' (stem={qpath.stem})"
                    )
                    results[name] = []
                    continue
                try:
                    results[name] = self._decode_bqrs(bqrs)
                except Exception as exc:
                    decode_errors.append(str(exc))
                    results[name] = []
                if log:
                    log(name, len(results[name]))
            if decode_errors:
                raise RuntimeError(
                    "Errors decoding results:\n" + "\n".join(decode_errors)
                )

            # Дедупликация flow по (func_name, func_file, stmt_id)
            if "flow" in results:
                _prio = {"if": 10, "for": 10, "while": 10, "do": 10, "try": 10,
                         "return": 5, "throw": 5, "break": 5, "continue": 5,
                         "other": 1, "expr": 1}
                best: Dict[Any, Dict[str, str]] = {}
                for item in results["flow"]:
                    key = (item["func_name"], item.get("func_file", ""), item["stmt_id"])
                    if key not in best or (
                        _prio.get(item.get("stmt_type", ""), 0)
                        > _prio.get(best[key].get("stmt_type", ""), 0)
                    ):
                        best[key] = item
                results["flow"] = list(best.values())

            return results
        finally:
            for p in temp_files:
                try:
                    p.unlink()
                except OSError:
                    pass

    def get_functional_objects(self) -> List[Dict[str, str]]:
        return self._run_query("functional_objects.ql", "functional")

    def get_files(self) -> List[Dict[str, str]]:
        """Возвращает список файлов проекта, участвующих в сборке."""
        return self._run_query("files.ql", "files")

    def get_redundant_objects(self) -> List[Dict[str, str]]:
        return self._run_query("redundant_objects.ql", "redundant")

    def get_info_objects(self) -> List[Dict[str, str]]:
        return self._run_query("info_objects.ql", "info")

    def get_control_matrix(self) -> List[Dict[str, str]]:
        return self._run_query("control_matrix.ql", "control")

    def get_data_matrix(self) -> List[Dict[str, str]]:
        return self._run_query("data_matrix.ql", "data")

    def get_function_flow(self) -> List[Dict[str, str]]:
        # При дублировании stmt_id (напр. DeclStmt и ForStmt на одной строке)
        # оставляем управляющий тип: for/while/if/try > return/throw > other.
        _prio = {"if": 10, "for": 10, "while": 10, "do": 10, "try": 10,
                 "return": 5, "throw": 5, "break": 5, "continue": 5,
                 "other": 1, "expr": 1}
        data = self._run_query("function_flow_v2.ql", "flow")
        best: Dict[Any, Dict[str, str]] = {}
        for item in data:
            key = (item["func_name"], item.get("func_file", ""), item["stmt_id"])
            if key not in best:
                best[key] = item
            else:
                cur_prio = _prio.get(best[key].get("stmt_type", ""), 0)
                new_prio = _prio.get(item.get("stmt_type", ""), 0)
                if new_prio > cur_prio:
                    best[key] = item
        return list(best.values())

    def _deduplicate_flow(self, data: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Дедупликация потоков функций с приоритетом типов."""
        _prio = {"if": 10, "for": 10, "while": 10, "do": 10, "try": 10,
                 "return": 5, "throw": 5, "break": 5, "continue": 5,
                 "other": 1, "expr": 1}
        best: Dict[Any, Dict[str, str]] = {}
        for item in data:
            key = (item["func_name"], item["stmt_id"])
            if key not in best:
                best[key] = item
            else:
                cur_prio = _prio.get(best[key].get("stmt_type", ""), 0)
                new_prio = _prio.get(item.get("stmt_type", ""), 0)
                if new_prio > cur_prio:
                    best[key] = item
        return list(best.values())

    def run_all_queries(self, max_workers: int = 0) -> Dict[str, List[Dict[str, str]]]:
        """Запускает все запросы (max_workers игнорируется — используется батч)."""
        return self.run_batch_queries()

    def get_function_calls(self) -> List[Dict[str, str]]:
        """Возвращает список всех вызовов функций: caller -> callee"""
        return self._run_query("function_calls.ql", "calls")

    def get_redundant_info_objects(self) -> List[Dict[str, str]]:
        return self._run_query("redundant_info_objects.ql", "redundant_info")

    def get_arg_flow(self) -> List[Dict[str, str]]:
        """Возвращает потоки аргумент→параметр для всех вызовов функций."""
        return self._run_query("arg_flow.ql", "arg_flow")

    def get_file_flow(self) -> List[Dict[str, str]]:
        """Возвращает обращения функций к файлам через файловые потоки."""
        return self._run_query("file_flow.ql", "file_flow")

    def get_signature_analysis(self) -> List[Dict[str, str]]:
        """Возвращает потенциально опасные конструкции (ПОК) с привязкой к CWE."""
        return self._run_query("signature_analysis.ql", "signature")

