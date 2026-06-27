"""project_runner.py — пайплайн анализа поверх project.db.

Две фазы (соответствуют двум действиям пользователя в GUI):
  1. run_static_analysis(project, ...) — выполняет запросы CodeQL и тяжёлые
     вычисления (ELK/маршруты/графы) ОДИН раз, складывает сырые наборы и
     производные данные (+SVG, +статистику) в project.db. Файлы-отчёты НЕ пишет.
  2. generate_static_reports(project) — быстрый ДАМП из project.db в reports/static
     (CSV + flowcharts/). Повторно CodeQL/ELK не запускаются.

Переиспользует существующие блоки: CodeQLAnalyzer, ReportGenerator,
ELKFlowchartGenerator, GraphBuilder, RouteStreamWriter.
"""
from __future__ import annotations

import csv
import gc
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.codeql_analyzer import CodeQLAnalyzer
from core.joern_analyzer import JoernAnalyzer
from core.sql_analyzer import SqlAnalyzer
from core.fo_filters import read_source_snapshot, filter_macro_synthesized_fo, filter_info_by_excluded_fo
from core.file_lists import path_matches_patterns as _path_matches
from core.report_generator import ReportGenerator, RouteStreamWriter, read_critical_io_numbers
from viz.elk_generator import ELKFlowchartGenerator
from viz.drakon_generator import DrakonGenerator
from viz.flowchart_generator import FlowchartGenerator
from viz.func_key import make_func_key
from viz.graph_builder import GraphBuilder
from core.project_db import ProjectDB


# Имена отчётов-«проверок» (1:1 с GUI). Используются в selected_checks.
CHECK_FUNCTIONAL = "Перечень_ФО(процедур_функций).csv"
CHECK_INFO = "Перечень_ИО.csv"
CHECK_MATRIX = "Матрица_связей_ФО(процедур_функций)_по_управлению.csv"
CHECK_DATA_MATRIX = "Матрица_связей_ФО(процедур_функций)_по_информации.csv"
CHECK_SIGNATURE = "Сигнатурный_анализ_кода.csv"
CHECK_ROUTES_BR = "Маршруты_выполнения_ФО(ветвей).csv"
CHECK_ROUTES_CALL = "Маршруты_выполнения_ФО(процедур_функций).csv"
CHECK_GRAPH_FUNC = "Граф_функций.csv"
CHECK_GRAPH_BR = "Граф_ветвей.csv"
CHECK_GRAPH_ROUTE = "Граф_маршрутов.csv"
CHECK_BRANCH_LIST = "Перечень_ветвей.csv"
CHECK_FLOWCHARTS = "flowcharts"


def _sel(selected: Optional[set], name: str) -> bool:
    return selected is None or name in selected


def _log(cb: Optional[Callable], msg: str):
    if cb:
        cb(msg)


def _dt(seconds: float) -> str:
    """Человекочитаемая длительность: '5.2 с' или '1м 03с'."""
    if seconds < 60:
        return f"{seconds:.1f} с"
    m, s = divmod(int(seconds), 60)
    return f"{m}м {s:02d}с"


def _progress(cb: Optional[Callable], label: str, cur: int, total: int):
    """Сообщает прогресс операции (label, текущее, всего) — для прогресс-бара."""
    if cb:
        cb(label, cur, total)


def _table(cb: Optional[Callable], event: str, payload: dict):
    """Структурированное событие для табличного лога GUI (воронка по
    запросам/фильтрам) — необязательный канал ОТДЕЛЬНЫЙ от log()/progress(),
    чтобы не трогать сигнатуры/поведение для CLI и тестов (cb по умолчанию
    None). См. attach_funnel_table в gui/gui_project.py."""
    if cb:
        cb(event, payload)




class FileFilterResult:
    """Результат apply_file_filters: raw — отфильтрованные (на месте)
    сырые наборы; excess_include/excess_exclude — записи списков файлов,
    не совпавшие ни с одним реальным файлом в БД (см. docstring ниже)."""
    __slots__ = ("raw", "excess_include", "excess_exclude")

    def __init__(self, raw, excess_include, excess_exclude):
        self.raw = raw
        self.excess_include = excess_include
        self.excess_exclude = excess_exclude


_FILTER_KEYS = ("functional", "info", "files", "signature", "control",
                "data", "arg_flow", "file_flow", "flow")


def apply_file_filters(raw: Dict[str, List[dict]],
                       include: Optional[List[str]],
                       exclude: Optional[List[str]],
                       log: Optional[Callable] = None,
                       include_list: Optional[List[str]] = None,
                       exclude_list: Optional[List[str]] = None,
                       table_cb: Optional[Callable] = None) -> "FileFilterResult":
    """Фильтрует сырые наборы по белому/чёрному спискам шаблонов путей
    (include/exclude — glob/подстрока) И/ИЛИ по явному списку файлов
    (include_list/exclude_list — точные ИЛИ относительные пути, см.
    core/file_lists.py — пользователь может не знать точные абсолютные
    пути build-машины, хранящиеся в БД, поэтому относительные пути
    сопоставляются по совпадению хвоста). Оба механизма комбинируются по
    ИЛИ: путь включён, если подходит хотя бы под один шаблон ИЛИ есть в
    include_list (когда что-то из этого задано); путь исключён, если
    подходит под exclude ИЛИ есть в exclude_list.

    include_list/exclude_list — тот же список, что передаётся в
    instrument_c_make.py/instrument_cpp.py при извлечении исходников из
    src.zip для инструментации, поэтому статика и инструментация всегда
    видят одно и то же подмножество файлов.

    Бел. список: если непустой — оставляем только подходящие файлы.
    Чёрный список: убираем подходящие файлы.
    Для целостности: фильтруем ФО по файлу → получаем разрешённые имена ФО →
    остальные наборы фильтруем по имени ФО (и файлу), чтобы не осталось
    «висячих» ссылок в матрицах/маршрутах.

    Возвращает FileFilterResult с raw (мутирован на месте и возвращён для
    удобства) и excess_include/excess_exclude — записи списков, которые НЕ
    совпали ни с одним реальным файлом в БД (список файлов мог оказаться
    шире фактической кодовой базы — пользователь не обязан точно знать,
    что реально попало в БД). Эти списки нужно сохранить в отчётах
    проекта — см. вызывающий код в run_static_analysis.
    """
    import time
    from core.file_lists import path_matches_list, is_generated_path

    t0 = time.perf_counter()
    include = [p for p in (include or []) if p.strip()]
    exclude = [p for p in (exclude or []) if p.strip()]
    include_list = [p for p in (include_list or []) if p.strip()]
    exclude_list = [p for p in (exclude_list or []) if p.strip()]
    if not include and not exclude and not include_list and not exclude_list:
        no_change = {k: len(raw.get(k, [])) for k in _FILTER_KEYS}
        _table(table_cb, "filter_step", {"step": "вне списка", "before": no_change,
                                         "after": no_change, "elapsed": time.perf_counter() - t0})
        return FileFilterResult(raw, [], [])

    def file_ok(path: str) -> bool:
        if include or include_list:
            ok = (include and _path_matches(path, include)) or \
                 (include_list and path_matches_list(path, include_list))
            if not ok:
                return False
        if exclude and _path_matches(path, exclude):
            return False
        if exclude_list and path_matches_list(path, exclude_list):
            return False
        return True

    all_files = raw.get("files", [])
    all_paths = [r.get("abs_path", "") for r in all_files]

    # Список файлов может быть ШИРЕ фактической кодовой базы в БД (пользователь
    # не обязан точно знать, какие пути реально попали в src.zip) — отдельно
    # фиксируем записи include_list/exclude_list, не совпавшие ни с одним
    # реальным файлом, чтобы предупредить и сохранить для проверки.
    def _unmatched(entries: List[str]) -> List[str]:
        return [e for e in entries if not any(path_matches_list(p, [e]) for p in all_paths)]

    excess_include = _unmatched(include_list) if include_list else []
    excess_exclude = _unmatched(exclude_list) if exclude_list else []
    if excess_include:
        _log(log, f"[ФИЛЬТР] Внимание: {len(excess_include)} путей из белого списка "
                  f"не найдены среди файлов БД (избыточные записи) — список сохранён "
                  f"в отчётах проекта.")
    if excess_exclude:
        _log(log, f"[ФИЛЬТР] Внимание: {len(excess_exclude)} путей из чёрного списка "
                  f"не найдены среди файлов БД (избыточные записи) — список сохранён "
                  f"в отчётах проекта.")

    # Предупреждение: сколько СГЕНЕРИРОВАННЫХ во время сборки файлов (ADLC/
    # JVMTI/JFR и т.п. — эвристика is_generated_path) реально доступны в
    # src.zip БД, но отсеяны текущим фильтром — пользователь мог не знать
    # о их существовании при составлении списка/шаблонов.
    generated_total = sum(1 for p in all_paths if is_generated_path(p))
    generated_kept = sum(1 for p in all_paths if is_generated_path(p) and file_ok(p))
    generated_skipped = generated_total - generated_kept
    if (include or include_list or exclude or exclude_list) and generated_skipped:
        _log(log, f"[ФИЛЬТР] Внимание: {generated_skipped} сгенерированных во время "
                  f"сборки файлов (ADLC/JVMTI/JFR и т.п.) потенциально доступны в "
                  f"БД, но не попадают под текущий фильтр — они есть в src.zip и "
                  f"могут быть проанализированы/инструментированы, если включить их "
                  f"в белый список.")

    before = {k: len(raw.get(k, [])) for k in _FILTER_KEYS}

    raw["functional"] = [r for r in raw["functional"] if file_ok(r.get("file", ""))]
    allowed = {r["qualified_name"] for r in raw["functional"]}

    raw["info"] = [r for r in raw.get("info", []) if file_ok(r.get("file", ""))]
    raw["files"] = [r for r in raw.get("files", []) if file_ok(r.get("abs_path", ""))]
    raw["signature"] = [r for r in raw.get("signature", [])
                        if r.get("function_name", "") in allowed]
    raw["control"] = [r for r in raw.get("control", [])
                      if r.get("caller_name") in allowed and r.get("callee_name") in allowed]
    raw["data"] = [r for r in raw.get("data", [])
                   if r.get("function_name") in allowed]
    raw["arg_flow"] = [r for r in raw.get("arg_flow", [])
                       if r.get("caller_name") in allowed and r.get("callee_name") in allowed]
    raw["file_flow"] = [r for r in raw.get("file_flow", [])
                        if r.get("function_name") in allowed]
    raw["flow"] = [r for r in raw.get("flow", []) if r.get("func_name") in allowed]

    after = {k: len(raw.get(k, [])) for k in _FILTER_KEYS}
    _table(table_cb, "filter_step", {"step": "вне списка", "before": before,
                                     "after": after, "elapsed": time.perf_counter() - t0})

    # Только cp1251-безопасные символы: лог может печататься в консоль Windows
    # (cp1251/cp866), где «→» и эмодзи роняют прогон UnicodeEncodeError.
    _log(log, f"[ФИЛЬТР] ФО: {before['functional']} -> {after['functional']} "
              f"(белый список шаблонов: {len(include)}, чёрный: {len(exclude)}; "
              f"белый список файлов: {len(include_list)}, чёрный: {len(exclude_list)})")
    return FileFilterResult(raw, excess_include, excess_exclude)


# ─────────────────────────────────────────────────────────────────────────────
# Фаза 1: статический анализ → project.db
# ─────────────────────────────────────────────────────────────────────────────
def run_static_analysis(project: ProjectDB, codeql_path: str = "codeql",
                        joern_path: str = "joern",
                        sql_dialect: str = "mysql",
                        ram_mb: int = 4096, max_routes: int = 1000,
                        selected_checks: Optional[List[str]] = None,
                        flowchart_format: str = "svg",
                        flowchart_renderer: str = "elk",
                        simplified_flowcharts: bool = False,
                        include_patterns: Optional[List[str]] = None,
                        exclude_patterns: Optional[List[str]] = None,
                        include_list: Optional[List[str]] = None,
                        exclude_list: Optional[List[str]] = None,
                        log: Optional[Callable] = None,
                        progress: Optional[Callable] = None,
                        table_cb: Optional[Callable] = None) -> Dict[str, int]:
    """Выполняет анализ и сохраняет сырые + производные данные в project.db.

    table_cb(event, payload) — необязательный канал структурированных
    событий "воронки" (запрос -> фильтры -> итог) для табличного лога GUI
    (см. attach_funnel_table в gui/gui_project.py). CLI/тесты его не
    передают (None) — поведение/вывод log()/progress() не меняется.

    include_list/exclude_list — белый/чёрный список файлов (см.
    core/file_lists.py): пути, по одному на список, относительные или
    абсолютные — тот же список, что нужно передать в instrument_c_make.py/
    instrument_cpp.py при инструментации, чтобы оба этапа видели одно и то
    же подмножество файлов. Записи, не совпавшие ни с одним реальным
    файлом в БД, сохраняются в reports/static/Избыточные_записи_списка.csv
    (см. apply_file_filters/FileFilterResult).

    log(msg)               — текстовый лог;
    progress(label,cur,tot) — прогресс операции (для прогресс-бара).
    Возвращает словарь статистики (для немедленного показа в GUI).
    """
    import time
    t_start = time.perf_counter()

    def q(tag: str, human: str, fn):
        """Выполняет этап-запрос с логом старта и времени завершения."""
        _log(log, f"[{tag}] {human}…")
        ts = time.perf_counter()
        res = fn()
        _log(log, f"[{tag}] готово: {len(res)} (за {_dt(time.perf_counter()-ts)})")
        return res

    def q_if(need: bool, tag: str, human: str, fn) -> list:
        """Как q(), но пропускает запрос если need=False."""
        if not need:
            _log(log, f"[{tag}] пропущено (не выбрано)")
            return []
        return q(tag, human, fn)

    meta = project.get_project()
    selected = set(selected_checks) if selected_checks is not None else None
    project.set_static_params(ram_mb, max_routes, selected_checks or [],
                              simplified_flowcharts=simplified_flowcharts)
    project.set_file_filters(include_patterns or [], exclude_patterns or [],
                             include_list=include_list, exclude_list=exclude_list)

    language = meta.get("language", "cpp")
    if language == "php":
        analyzer = JoernAnalyzer(
            meta["codeql_db_path"],          # stores PHP source dir for PHP projects
            joern_path=joern_path,
            path_pattern=meta.get("pattern", ""),
            work_dir=str(project.root / "work"),
            ram_mb=ram_mb,
        )
    elif language == "sql":
        analyzer = SqlAnalyzer(
            meta["codeql_db_path"],          # stores SQL source dir for SQL projects
            dialect=sql_dialect,
            path_pattern=meta.get("pattern", ""),
            work_dir=str(project.root / "work"),
            ram_mb=ram_mb,
        )
    else:
        analyzer = CodeQLAnalyzer(
            meta["codeql_db_path"], codeql_path,
            language=language,
            path_pattern=meta.get("pattern", ""),
            work_dir=str(project.root / "work"),
            ram_mb=ram_mb,
        )

    # --- Определяем что нужно для выбранных проверок ---
    # Потоковые данные нужны для блок-схем, маршрутов, графов.
    needs_flow = (
        _sel(selected, CHECK_FLOWCHARTS) or _sel(selected, CHECK_ROUTES_BR)
        or _sel(selected, CHECK_ROUTES_CALL) or _sel(selected, CHECK_GRAPH_BR)
        or _sel(selected, CHECK_GRAPH_ROUTE) or _sel(selected, CHECK_BRANCH_LIST)
    )
    # ИО: нужны для отчёта ИО, матрицы данных, блок-схем (метки переменных),
    #     маршрутов и графов ветвей/маршрутов.
    needs_info = (
        _sel(selected, CHECK_INFO) or _sel(selected, CHECK_DATA_MATRIX)
        or _sel(selected, CHECK_FLOWCHARTS) or _sel(selected, CHECK_ROUTES_BR)
        or _sel(selected, CHECK_ROUTES_CALL) or _sel(selected, CHECK_GRAPH_BR)
        or _sel(selected, CHECK_GRAPH_ROUTE) or _sel(selected, CHECK_BRANCH_LIST)
    )
    # Файлы: нужны для отчётов ФО, ИО, матриц (отображение имён файлов).
    needs_files = (
        _sel(selected, CHECK_FUNCTIONAL) or _sel(selected, CHECK_INFO)
        or _sel(selected, CHECK_MATRIX) or _sel(selected, CHECK_DATA_MATRIX)
    )
    # Сигнатурный анализ: только для своего отчёта.
    needs_sig = _sel(selected, CHECK_SIGNATURE)
    # Матрица управления (вызовы): для матрицы управления, графов, маршрутов.
    needs_control = (
        _sel(selected, CHECK_MATRIX) or _sel(selected, CHECK_GRAPH_FUNC)
        or _sel(selected, CHECK_ROUTES_BR) or _sel(selected, CHECK_ROUTES_CALL)
        or _sel(selected, CHECK_GRAPH_BR) or _sel(selected, CHECK_GRAPH_ROUTE)
        or _sel(selected, CHECK_BRANCH_LIST)
    )
    # Матрица данных: только для отчёта матрицы данных.
    needs_data = _sel(selected, CHECK_DATA_MATRIX)
    # Аргументные потоки: для маршрутов и графов.
    needs_arg_flow = (
        _sel(selected, CHECK_ROUTES_BR) or _sel(selected, CHECK_ROUTES_CALL)
        or _sel(selected, CHECK_GRAPH_BR) or _sel(selected, CHECK_GRAPH_ROUTE)
    )
    # Файловые потоки: для отчёта ИО (I/O-порядок), матрицы данных.
    needs_file_flow = (
        _sel(selected, CHECK_INFO) or _sel(selected, CHECK_DATA_MATRIX)
    )

    # --- 1. Сырые наборы — одним вызовом CodeQL (БД загружается один раз) ---
    _needed: List[str] = ["functional"]
    if needs_info:      _needed.append("info")
    if needs_files:     _needed.append("files")
    if needs_sig:       _needed.append("signature")
    if needs_control:   _needed.append("control")
    if needs_data:      _needed.append("data")
    if needs_arg_flow:  _needed.append("arg_flow")
    if needs_file_flow: _needed.append("file_flow")
    if needs_flow:      _needed.append("flow")
    # Геометрия точек вставки датчиков для инструментации: собираем в составе
    # сырых данных и сохраняем в project.db, чтобы инструментатор брал её оттуда,
    # а не делал отдельный запрос probe_points.ql (см. instrument_cpp.py,
    # instrument_java.py). Раньше список был только ("cpp", "c") — Java имеет
    # queries/java/probe_points.ql ровно того же назначения, но "probe" для него
    # никогда не собирался: --project-db в instrument_java.py читал ВСЕГДА
    # пустую таблицу q_probe, молча давая 0 точек вставки без единой ошибки.
    if language in ("cpp", "c", "java"): _needed.append("probe")

    _LABELS: Dict[str, tuple] = {
        "functional": ("ФО",      "Сбор функциональных объектов"),
        "info":       ("ИО",      "Сбор информационных объектов"),
        "files":      ("ФАЙЛЫ",   "Список файлов сборки"),
        "signature":  ("АНАЛИЗ",  "Сигнатурный анализ опасных конструкций"),
        "control":    ("МАТРИЦЫ", "Отношения управления (вызовы)"),
        "data":       ("МАТРИЦЫ", "Отношения данных (доступ к переменным)"),
        "arg_flow":   ("МАТРИЦЫ", "Аргументные потоки"),
        "file_flow":  ("МАТРИЦЫ", "Обращения к файлам"),
        "flow":       ("ПОТОК",   "Управляющие конструкции (if/for/while/...)"),
        "probe":      ("ДАТЧИКИ", "Геометрия точек вставки (вход/выход/ветви)"),
    }

    def _on_query_done(name: str, count: int):
        tag, label = _LABELS.get(name, (name.upper(), name))
        _log(log, f"[{tag}] {label}: {count}")

    _engine = "Joern" if language == "php" else "CodeQL"
    _log(log, f"[ЗАПРОСЫ] Запуск {len(_needed)} {_engine}-запросов (одна загрузка БД)...")
    _table(table_cb, "query_batch_start",
          {"rows": [(k, _LABELS.get(k, (k.upper(), k))) for k in _needed]})
    _ts = time.perf_counter()
    _batch = analyzer.run_batch_queries(_needed, log=_on_query_done)
    _batch_elapsed = time.perf_counter() - _ts
    _table(table_cb, "query_batch_done",
          {"counts": {k: len(_batch.get(k, [])) for k in _needed}, "elapsed": _batch_elapsed})
    _log(log, f"[ЗАПРОСЫ] Готово за {_dt(_batch_elapsed)}")

    raw: Dict[str, List[dict]] = {}
    for _k in _needed:
        raw[_k] = _batch.get(_k, [])
    for _k in ["functional", "info", "files", "signature", "control",
               "data", "arg_flow", "file_flow", "flow"]:
        raw.setdefault(_k, [])

    # Фильтрация по белому/чёрному спискам шаблонов И/ИЛИ явных списков файлов
    _filter_res = apply_file_filters(raw, include_patterns, exclude_patterns, log,
                                     include_list=include_list, exclude_list=exclude_list,
                                     table_cb=table_cb)
    if _filter_res.excess_include or _filter_res.excess_exclude:
        project.reports_static.mkdir(parents=True, exist_ok=True)
        _excess_path = project.reports_static / "Избыточные_записи_списка.csv"
        with open(_excess_path, "w", encoding="utf-8-sig", newline="") as _f:
            _w = csv.writer(_f, delimiter=";")
            _w.writerow(["Список", "Путь"])
            for _p in _filter_res.excess_include:
                _w.writerow(["белый", _p])
            for _p in _filter_res.excess_exclude:
                _w.writerow(["чёрный", _p])
        _log(log, f"[ФИЛЬТР] Список избыточных записей сохранён: {_excess_path}")

    # ФО, чьё короткое имя физически не встречается в исходной строке —
    # имя целиком собрано макросом (X-macro, G_DEFINE_TYPE и подобные) —
    # инструментировать их нельзя, исключаем из всех дальнейших отчётов.
    # ТОЛЬКО для cpp/c — специфика препроцессора (комментарий это всегда
    # утверждал, но условие ниже раньше реально включало ЛЮБОЙ язык кроме
    # php/sql, в т.ч. java — у которой нет ни препроцессора, ни макросов;
    # баг найден на gosjava: org.omg.CORBA.StringSeqHelper.insert/extract/
    # read ложно считались "собранными макросом" из-за коллизии basename в
    # read_source_snapshot, см. fo_filters.py — но сам факт применения
    # фильтра к Java был отдельной, более фундаментальной ошибкой).
    if language in ("cpp", "c") and raw.get("functional"):
        _macro_keys = ("functional", "info", "data", "flow", "signature")
        _t_macro = time.perf_counter()
        before_macro = {k: len(raw.get(k, [])) for k in _macro_keys}
        before_fo = before_macro["functional"]
        before_names = {r["qualified_name"] for r in raw["functional"]}
        source_by_base = read_source_snapshot(meta["codeql_db_path"])
        raw["functional"] = filter_macro_synthesized_fo(raw["functional"], source_by_base, log=log)
        if len(raw["functional"]) != before_fo:
            _log(log, f"[ФИЛЬТР] ФО (макро-имена): {before_fo} -> {len(raw['functional'])}")
            # Исключить ИО/ветви из удалённых ФО
            kept_names = {r["qualified_name"] for r in raw["functional"]}
            excluded_names = before_names - kept_names
            if excluded_names:
                raw["info"] = filter_info_by_excluded_fo(raw["info"], excluded_names)
                raw["data"] = [r for r in raw["data"]
                               if r.get("function_name", "") not in excluded_names]
                raw["flow"] = [r for r in raw["flow"]
                               if r.get("func_name", "") not in excluded_names]
                # Опасные конструкции (ПОК) исключённого ФО тоже убираем:
                # если ФО исключён, не должно остаться ни ветвей, ни ИО, ни ПОК.
                raw["signature"] = [r for r in raw["signature"]
                                    if r.get("function_name", "") not in excluded_names]
                _log(log, f"[ФИЛЬТР] ИО/ветви/ПОК: исключены данные из "
                    f"{len(excluded_names)} макро-ФО")
        after_macro = {k: len(raw.get(k, [])) for k in _macro_keys}
        _table(table_cb, "filter_step", {"step": "макро-фильтр", "before": before_macro,
                                         "after": after_macro,
                                         "elapsed": time.perf_counter() - _t_macro})

    ts = time.perf_counter()
    project.save_raw_data(raw)
    _log(log, f"[БД] Сырые наборы записаны (за {_dt(time.perf_counter()-ts)})")

    # --- 2. Производные данные (ELK/маршруты/ветви) — один раз ---
    routes_by_func: Dict = {}
    branch_edges_by_func: Dict = {}
    branch_inventory_by_func: Dict = {}
    flowchart_items: List[dict] = []

    if needs_flow and raw["flow"]:
        build_fc = _sel(selected, CHECK_FLOWCHARTS)
        tmp_fc = Path(tempfile.mkdtemp(prefix="cqfc_"))
        try:
            if flowchart_renderer == "drakon":
                fc_gen = DrakonGenerator(str(tmp_fc), db_path=meta["codeql_db_path"],
                                         simplified=simplified_flowcharts)
            elif flowchart_renderer == "elk-axis":
                fc_gen = ELKFlowchartGenerator(str(tmp_fc), db_path=meta["codeql_db_path"],
                                               output_format=flowchart_format,
                                               axis_mode=True,
                                               simplified=simplified_flowcharts)
            else:
                fc_gen = ELKFlowchartGenerator(str(tmp_fc), db_path=meta["codeql_db_path"],
                                               output_format=flowchart_format,
                                               simplified=simplified_flowcharts)
            # generate_all сам сообщает прогресс и итоги двумя секциями:
            # [БЛОК-СХЕМЫ] (рендер SVG) и [МАРШРУТЫ] (формирование маршрутов/ветвей).
            generated, routes_by_func, branch_edges_by_func, branch_inventory_by_func = \
                fc_gen.generate_all(
                    raw["functional"], raw["flow"], raw["info"], raw["control"],
                    raw["data"], raw["file_flow"], route_writer=None,
                    load_by_demand=True, build_flowcharts=build_fc,
                    need_routes_in_memory=True, max_routes=max_routes,
                    progress=lambda lbl, c, t: _progress(progress, lbl, c, t),
                    log=lambda m: _log(log, m),
                )
            # DrakonGenerator рисует SVG, но не вычисляет маршруты/ветви
            # (возвращает {}, {}, {} — см. drakon_generator.py generate_all).
            # Запускаем второй проход через FlowchartGenerator без рендеринга SVG,
            # чтобы заполнить routes_by_func / branch_edges / branch_inventory_by_func.
            if flowchart_renderer == "drakon":
                _fgen = FlowchartGenerator(str(tmp_fc), db_path=meta["codeql_db_path"],
                                           clear_output=False)
                _, routes_by_func, branch_edges_by_func, branch_inventory_by_func = \
                    _fgen.generate_all(
                        raw["functional"], raw["flow"], raw["info"], raw["control"],
                        raw["data"], raw["file_flow"], route_writer=None,
                        load_by_demand=True, build_flowcharts=False,
                        need_routes_in_memory=True, max_routes=max_routes,
                        progress=lambda lbl, c, t: _progress(progress, lbl, c, t),
                        log=lambda m: _log(log, m),
                    )
            # Считываем сгенерированные SVG в БД
            if build_fc:
                func_index = {it["qualified_name"]: i + 1
                              for i, it in enumerate(raw["functional"])}
                for svg in sorted(tmp_fc.glob("*.svg")):
                    flowchart_items.append({
                        "fo_num": _num_from_filename(svg.name),
                        "fo_name": svg.stem,
                        "filename": svg.name,
                        "svg": svg.read_text(encoding="utf-8", errors="ignore"),
                    })
        finally:
            shutil.rmtree(tmp_fc, ignore_errors=True)

    # Сохраняем производные структуры (по функциям — без гигантских JSON-строк) и SVG
    _log(log, "[БД] Запись производных данных (маршруты/ветви/графы/SVG)…")
    project.save_derived_map("routes_by_func", routes_by_func)
    project.save_derived_map("branch_edges_by_func", branch_edges_by_func)
    project.save_derived_map("branch_inventory_by_func", branch_inventory_by_func)
    if flowchart_items:
        project.save_flowcharts(flowchart_items)

    # --- 3. Статистика и статус ---
    stats = {
        "fo_total": len(raw["functional"]),
        "io_total": len(raw["info"]),
        "files_total": len(raw["files"]),
        "control_links": len(raw["control"]),
        "signatures": len(raw["signature"]),
        "branches_total": sum(len(v) for v in branch_inventory_by_func.values()),
    }
    for k, v in stats.items():
        project.set_stat(k, v)
    project.set_static_status("done")
    _log(log, f"[ИТОГО] ФО: {stats['fo_total']}, ИО: {stats['io_total']}, "
              f"файлов: {stats['files_total']}, связей управления: {stats['control_links']}, "
              f"ПОК: {stats['signatures']}, ветвей: {stats['branches_total']}")
    _log(log, f"[OK] Статический анализ завершён за {_dt(time.perf_counter()-t_start)}. "
              "Данные сохранены в project.db.")
    return stats


def _num_from_filename(name: str) -> int:
    """'12_Calculator.div.svg' → 12; иначе 0."""
    head = name.split("_", 1)[0]
    return int(head) if head.isdigit() else 0


# ─────────────────────────────────────────────────────────────────────────────
# Фаза 2: project.db → reports/static (быстрый дамп)
# ─────────────────────────────────────────────────────────────────────────────
def generate_static_reports(project: ProjectDB,
                            log: Optional[Callable] = None,
                            progress: Optional[Callable] = None,
                            critical_io_path: Optional[str] = None) -> Path:
    """Создаёт CSV-отчёты и flowcharts/ в reports/static из данных project.db.

    critical_io_path — путь к пользовательскому Перечень_критических_ИО.csv; при
    указании строится Критические_маршруты.csv (критический ИО ИЛИ опасная конструкция).
    """
    import time
    t_start = time.perf_counter()
    st = project.get_static_state()
    selected = set(st["selected_checks"]) if st["selected_checks"] else None
    out = project.reports_static
    out.mkdir(parents=True, exist_ok=True)

    raw = project.load_raw_data()
    # routes_by_func НЕ грузим целиком: на крупных проектах с большим
    # max_routes это гигабайты JSON → OOM. Маршруты читаем по одной функции
    # при записи CSV (ниже). Графу ветвей маршруты не нужны (branch_edges).
    branch_edges_by_func = project.load_derived_map("branch_edges_by_func")
    branch_inventory_by_func = project.load_derived_map("branch_inventory_by_func")

    func_data = raw["functional"]
    ctrl_data = raw["control"]
    func_index = {it["qualified_name"]: i + 1 for i, it in enumerate(func_data)}
    func_file = {it["qualified_name"]: it.get("file", "") for it in func_data}

    report = ReportGenerator(str(out))

    # Перечень файлов
    src_dir = str(project.root)
    file_ordered, file_by_abs_path = report.add_file_list(raw["files"], src_dir)

    # Сигнатурный анализ
    if _sel(selected, CHECK_SIGNATURE):
        meta = project.get_project()
        # Снимок исходников из src.zip БД — для колонки «Фрагмент кода»
        # (codeql не нужен, читается из архива). Идентично пути CLI (main.py),
        # чтобы GUI и CLI давали один и тот же отчёт по одной БД.
        lang = meta.get("language", "cpp")
        source_by_base = (read_source_snapshot(meta["codeql_db_path"])
                          if lang not in ("php", "sql") else {})
        report.add_signature_analysis(raw["signature"], func_data, file_by_abs_path,
                                      source_by_base,
                                      rule_source=f"{lang}-queries")
        report.add_signature_summary(raw["signature"])
        _log(log, "Сигнатурный анализ сохранён.")

    # Перечни ФО + матрицы управления
    report.add_functional_objects(func_data, ctrl_data)
    report.add_redundant_objects_from_usage(func_data, ctrl_data)
    if _sel(selected, CHECK_MATRIX):
        report.add_control_matrix(func_data, ctrl_data)
        report.add_module_control_matrix(func_data, ctrl_data, file_ordered, file_by_abs_path)

    # ИО + матрицы данных
    file_io_order = ReportGenerator._file_io_order(raw["file_flow"])
    if _sel(selected, CHECK_INFO):
        report.add_info_objects(raw["info"], raw["data"], raw["arg_flow"],
                                raw["file_flow"], func_data, file_ordered, file_io_order)
        report.add_redundant_info_objects_from_usage(raw["info"], raw["data"])
    if _sel(selected, CHECK_DATA_MATRIX):
        report.add_data_matrix(func_data, raw["info"], raw["data"], raw["arg_flow"],
                               raw["file_flow"], file_io_order)
        report.add_module_data_matrix(func_data, raw["info"], raw["data"], raw["arg_flow"],
                                      file_ordered, file_by_abs_path, raw["file_flow"],
                                      file_io_order)

    # Маршруты: читаем по одной функции из БД и сразу пишем (потоково),
    # чтобы не держать в памяти весь routes_by_func (гигабайты на крупных ФО).
    if _sel(selected, CHECK_ROUTES_BR) or _sel(selected, CHECK_ROUTES_CALL):
        rw = RouteStreamWriter(out)
        n = len(func_data)
        for i, it in enumerate(func_data):
            fn = it["qualified_name"]
            # Новый ключ '<номер>|<имя>'; fallback на legacy-ключ (имя) для
            # project.db, созданных прежними версиями.
            routes = project.load_derived_map_one("routes_by_func", make_func_key(i + 1, fn))
            if routes is None:
                routes = project.load_derived_map_one("routes_by_func", fn) or []
            rw.add_func(fn, i + 1, routes)
            routes = None
            if progress:
                _progress(progress, "Запись маршрутов", i + 1, n)
            if i % 200 == 0:
                gc.collect()
        rw.close()
        gc.collect()
        _log(log, "Маршруты сохранены.")

    # Критические маршруты: критический ИО ИЛИ опасная конструкция на маршруте.
    # Маршруты грузим из БД только для затронутых ФО (без OOM на крупных проектах).
    if critical_io_path:
        crit_nums = read_critical_io_numbers(critical_io_path)
        info_index = report._filtered_info_index(raw["info"])
        affected = set()
        for d in raw["data"]:
            if info_index.get(d.get("variable_name", "")) in crit_nums:
                affected.add(d.get("function_name", ""))
        for s in raw["signature"]:
            affected.add(s.get("function_name", ""))
        routes_subset: Dict[str, list] = {}
        for i, it in enumerate(func_data):
            fn = it["qualified_name"]
            if fn not in affected:
                continue
            key = make_func_key(i + 1, fn)
            r = project.load_derived_map_one("routes_by_func", key)
            if r is None:
                r = project.load_derived_map_one("routes_by_func", fn) or []
            routes_subset[key] = r
        report.add_critical_routes(func_data, routes_subset, branch_inventory_by_func,
                                   raw["info"], raw["data"], raw["signature"], crit_nums)
        _log(log, f"Критические маршруты сохранены (критических ИО: {len(crit_nums)}).")

    # Графы (дешёвая пересборка из ctrl_data + branch_edges; маршруты не нужны)
    gb = GraphBuilder()
    if _sel(selected, CHECK_GRAPH_FUNC):
        report.add_function_graph(gb.build_function_graph(ctrl_data), func_index, func_data)
    if _sel(selected, CHECK_GRAPH_BR) or _sel(selected, CHECK_GRAPH_ROUTE):
        branch_graph = gb.build_branch_graph(func_data, {}, branch_edges_by_func)
        if _sel(selected, CHECK_GRAPH_BR):
            report.add_branch_graph(branch_graph, func_index)
        if _sel(selected, CHECK_GRAPH_ROUTE):
            report.add_route_graph(gb.build_route_graph(func_data, ctrl_data, branch_graph),
                                   func_index)

    # Перечень ветвей
    if _sel(selected, CHECK_BRANCH_LIST) and branch_inventory_by_func:
        report.add_branch_inventory(branch_inventory_by_func, func_index, func_file, func_data)

    report.save()

    # Блок-схемы: дамп SVG из БД (с прогрессом по файлам)
    if _sel(selected, CHECK_FLOWCHARTS):
        fc_dir = out / "flowcharts"
        fc_dir.mkdir(parents=True, exist_ok=True)
        items = project.load_flowcharts()
        total = len(items)
        for i, item in enumerate(items):
            (fc_dir / item["filename"]).write_text(item["svg"], encoding="utf-8")
            if progress and (i % 20 == 0 or i == total - 1):
                _progress(progress, "Выгрузка блок-схем", i + 1, total)
        _log(log, f"[ОТЧЁТЫ] Блок-схемы сохранены: {total}")

    _log(log, f"[OK] Отчёты созданы за {_dt(time.perf_counter()-t_start)}: {out}")
    return out
