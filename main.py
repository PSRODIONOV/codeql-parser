#!/usr/bin/env python3
import sys
from pathlib import Path

# Локальные Python-пакеты (Pillow и др.) — добавляем в sys.path первыми
from paths import third_party
_local_pkg = third_party("python-packages")
if _local_pkg.exists() and str(_local_pkg) not in sys.path:
    sys.path.insert(0, str(_local_pkg))

import argparse
import json
import time
from datetime import datetime

from core.codeql_analyzer import CodeQLAnalyzer
from core.joern_analyzer import JoernAnalyzer
from core.sql_analyzer import SqlAnalyzer
from core.fo_filters import read_source_snapshot, filter_macro_synthesized_fo, filter_info_by_excluded_fo
from core.report_generator import ReportGenerator, RouteStreamWriter, read_critical_io_numbers
from viz.elk_generator import ELKFlowchartGenerator
from viz.drakon_generator import DrakonGenerator
from viz.flowchart_generator import FlowchartGenerator
from viz.graph_builder import GraphBuilder


def _should_create_report(selected_reports, report_name: str) -> bool:
    """Проверить нужно ли создавать отчёт"""
    if selected_reports is None:
        return True  # Если нет конфига, создаём всё
    return report_name in selected_reports


def _log_action(start_time, stage, action, details=""):
    """Логирует действие с затраченным временем"""
    elapsed = int(time.time() - start_time)
    minutes = elapsed // 60
    seconds = elapsed % 60
    time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
    msg = f"[{time_str:>6}] [{stage}] {action}"
    if details:
        msg += f": {details}"
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze CodeQL database and generate CSV reports"
    )
    parser.add_argument("db_path", help="Path to CodeQL database directory")
    parser.add_argument(
        "-o", "--output", default="reports", help="Output directory for CSV reports"
    )
    parser.add_argument(
        "--codeql", default="codeql", help="Path to codeql executable (default: codeql)"
    )
    parser.add_argument(
        "--language", default="cpp",
        choices=["cpp", "java", "javascript", "python", "php", "sql"],
        help="Source language of the analysed project (selects queries/<lang>/ or Joern for php, "
             "or SqlAnalyzer for sql)"
    )
    parser.add_argument(
        "--joern", default="joern",
        help="Path to joern executable (used when --language php)"
    )
    parser.add_argument(
        "--sql-dialect", default="mysql",
        choices=["mysql", "mariadb", "postgres", "postgresql",
                 "tsql", "mssql", "sqlserver", "oracle", "sqlite",
                 "spark", "bigquery", "generic"],
        help="SQL dialect for --language sql (default: mysql)"
    )
    parser.add_argument(
        "--pattern", default="",
        help="File path pattern for isProjectFile predicate (e.g. '%%test-project-cpp%%' or '%%asobuild%%')"
    )
    parser.add_argument(
        "--work-dir", default=None,
        help="Working directory for intermediate CodeQL output (default: <output>/work)"
    )
    parser.add_argument(
        "--ram", type=int, default=4096,
        help="Maximum memory (in MB) for CodeQL queries (default: 4096)"
    )
    parser.add_argument(
        "--max-routes", type=int, default=1000,
        help="Maximum number of execution routes enumerated per functional object (default: 1000)"
    )
    parser.add_argument(
        "--flowchart-format", default="svg", choices=["svg", "png"],
        help="Flowchart output format: svg (вектор, компактно — по умолчанию) или png (растр)"
    )
    parser.add_argument(
        "--flowchart-renderer", default="elk", choices=["elk", "drakon"],
        help="Flowchart layout engine: elk (ELK+Graphviz, default) or drakon (DRAKON-style pure-Python SVG)"
    )
    parser.add_argument(
        "--simplified-flowcharts", action="store_true", default=False,
        help="Упрощённый вид блок-схем: типовые метки узлов, последовательные действия -> 'Базовый блок'"
    )
    parser.add_argument(
        "--source-dir", default=None,
        help="Каталог с исходниками для отображения путей в «Перечень файлов в сборке.csv». "
             "По умолчанию — родительский каталог БД."
    )
    parser.add_argument(
        "--critical-io", default=None,
        help="Путь к пользовательскому Перечень_критических_ИО.csv (подмножество "
             "Перечень_ИО.csv). При указании строится отчёт Критические_маршруты.csv "
             "— маршруты с критическим ИО ИЛИ опасной конструкцией."
    )
    args = parser.parse_args()
    start_time = time.time()

    print("\n" + "="*70, flush=True)
    print(f"Начало создание отчетности [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]", flush=True)
    print("="*70, flush=True)

    # Определяем работную директорию (дефолт: output/work)
    work_dir = args.work_dir if args.work_dir else str(Path(args.output) / "work")

    _log_action(start_time, "БД", "Начало загрузки кодовой базы", args.db_path)
    try:
        if args.language == "php":
            analyzer = JoernAnalyzer(
                args.db_path,             # for PHP this is the source directory
                joern_path=args.joern,
                path_pattern=args.pattern,
                work_dir=work_dir,
                ram_mb=args.ram,
            )
        elif args.language == "sql":
            analyzer = SqlAnalyzer(
                args.db_path,             # for SQL this is the source directory
                dialect=args.sql_dialect,
                path_pattern=args.pattern,
                work_dir=work_dir,
                ram_mb=args.ram,
            )
        else:
            analyzer = CodeQLAnalyzer(
                args.db_path, args.codeql,
                language=args.language,
                path_pattern=args.pattern,
                work_dir=work_dir,
                ram_mb=args.ram,
            )
        _log_action(start_time, "БД", "Конец загрузки кодовой базы", "успешно")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", flush=True)
        sys.exit(1)

    report = ReportGenerator(args.output)

    # Загружаем конфиг выбранных отчётов (если создан GUI)
    selected_reports = None
    config_file = Path(args.output) / ".reports_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
            selected_reports = set(config.get("selected_reports", []))
            _log_action(start_time, "КОНФИГ", "Создание конфига для создания отчетов", f"{len(selected_reports)} отчетов")
        except Exception as e:
            print(f"ERROR: Ошибка чтения конфига: {e}", flush=True)
            selected_reports = None

    # Определяем нужные запросы до их запуска
    needs_flowcharts = _should_create_report(selected_reports, "flowcharts")
    needs_routes = any(_should_create_report(selected_reports, f) for f in
                      ["Маршруты_выполнения_ФО(ветвей).csv", "Маршруты_выполнения_ФО(процедур_функций).csv"])
    needs_graphs = any(_should_create_report(selected_reports, f) for f in
                      ["Граф_функций.csv", "Граф_ветвей.csv", "Граф_маршрутов.csv"])
    needs_branch_list = _should_create_report(selected_reports, "Перечень_ветвей.csv")
    needs_branch_routes = needs_branch_list or any(_should_create_report(selected_reports, f) for f in
                             ["Граф_ветвей.csv", "Граф_маршрутов.csv"])

    # Отчёт «Критические маршруты» требует маршрутов и инвентаря ветвей в памяти.
    needs_critical_routes = bool(getattr(args, "critical_io", None))
    if needs_critical_routes:
        needs_branch_routes = True

    # Все запросы — одним вызовом CodeQL (БД загружается один раз)
    _needed = ["functional", "info", "files", "signature", "control",
               "data", "arg_flow", "file_flow"]
    if needs_flowcharts or needs_routes or needs_branch_routes:
        _needed.append("flow")

    _log_action(start_time, "ЗАПРОСЫ", f"Запуск {len(_needed)} CodeQL-запросов (одна загрузка БД)")
    _all_raw = analyzer.run_batch_queries(_needed)
    func_data     = _all_raw.get("functional", [])
    info_data     = _all_raw.get("info", [])
    files_data    = _all_raw.get("files", [])
    sig_data      = _all_raw.get("signature", [])
    ctrl_data     = _all_raw.get("control", [])
    data_data     = _all_raw.get("data", [])
    arg_flow_data = _all_raw.get("arg_flow", [])
    file_flow_data = _all_raw.get("file_flow", [])
    flow_data     = _all_raw.get("flow", [])
    _log_action(start_time, "ЗАПРОСЫ", "Запросы выполнены",
                f"ФО:{len(func_data)}, ИО:{len(info_data)}, управление:{len(ctrl_data)}, "
                f"данные:{len(data_data)}, файлов:{len(files_data)}")

    source_dir_for_files = args.source_dir if args.source_dir else str(Path(args.db_path).parent)
    file_ordered, file_by_abs_path = report.add_file_list(files_data, source_dir_for_files)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень файлов в сборке.csv")

    source_by_base = read_source_snapshot(args.db_path)
    all_func_names = {it["qualified_name"] for it in func_data}
    func_data = filter_macro_synthesized_fo(func_data, source_by_base, log=print)
    kept_func_names = {it["qualified_name"] for it in func_data}
    excluded_func_names = all_func_names - kept_func_names
    if excluded_func_names:
        info_data = filter_info_by_excluded_fo(info_data, excluded_func_names)
        # Также фильтруем data_data — связи из удалённых ФО
        data_data = [r for r in data_data
                     if r.get("function_name", "") not in excluded_func_names]
        # Фильтруем flow_data — ветви из удалённых ФО
        flow_data = [r for r in flow_data
                     if r.get("func_name", "") not in excluded_func_names]
        # Опасные конструкции (ПОК) удалённых ФО тоже убираем — исключённый ФО
        # не должен оставлять следов ни в ветвях, ни в ИО, ни в сигнатурном анализе.
        sig_data = [r for r in sig_data
                    if r.get("function_name", "") not in excluded_func_names]
        print(f"[ИО] Исключено {len(excluded_func_names)} ФО (макро-имена) -> "
              f"ИО/ветви/ПОК из этих ФО удалены из отчётов")
    report.add_signature_analysis(sig_data, func_data, file_by_abs_path, source_by_base,
                                  rule_source=f"{args.language}-queries")
    report.add_signature_summary(sig_data)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Сигнатурный_анализ_кода.csv")
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Сигнатурный_анализ_сводка.csv")

    report.add_functional_objects(func_data, ctrl_data)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_ФО(процедур_функций).csv")
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Использования_ФО(процедур_функций).csv")
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_ФО(модулей).csv")
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Избыточные_ФО.csv")

    report.add_redundant_objects_from_usage(func_data, ctrl_data)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_избыточных_ФО(процедур_функций).csv")

    report.add_control_matrix(func_data, ctrl_data)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Матрица_связей_ФО(процедур_функций)_по_управлению.csv")
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Матрица_связей_ФО(модулей)_по_управлению.csv")

    report.add_module_control_matrix(func_data, ctrl_data, file_ordered, file_by_abs_path)
    _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Модульная_матрица_управления.csv")

    # Кэшируем порядок файлов ИО — вычисляем один раз вместо трёх
    file_io_order = ReportGenerator._file_io_order(file_flow_data)

    # Создаём отчёты в зависимости от конфига
    if _should_create_report(selected_reports, "Перечень_ИО.csv"):
        report.add_info_objects(info_data, data_data, arg_flow_data, file_flow_data, func_data, file_ordered, file_io_order)
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_ИО.csv")

        report.add_redundant_info_objects_from_usage(info_data, data_data)
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_избыточных_ИО.csv")

    # Матрицы (проверяем основной файл)
    if _should_create_report(selected_reports, "Матрица_связей_ФО(процедур_функций)_по_управлению.csv"):
        report.add_data_matrix(func_data, info_data, data_data, arg_flow_data, file_flow_data, file_io_order)
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Матрица_связей_ФО(процедур_функций)_по_информации.csv")
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Матрица_связей_ФО(модулей)_по_информации.csv")
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Использования_ИО.csv")

        report.add_module_data_matrix(func_data, info_data, data_data, arg_flow_data, file_ordered, file_by_abs_path, file_flow_data, file_io_order)
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Модульная_матрица_информации.csv")

    routes_by_func = {}
    branch_edges_by_func = {}
    branch_inventory_by_func = {}
    if needs_flowcharts or needs_routes or needs_branch_routes:
        _log_action(start_time, "БЛОК-СХЕМЫ", "Найдено утверждений", str(len(flow_data)))

        if needs_flowcharts:
            flowcharts_dir = str(Path(args.output) / "flowcharts")
            renderer = getattr(args, "flowchart_renderer", "elk")
            _simplified = getattr(args, "simplified_flowcharts", False)
            if renderer == "drakon":
                fc_gen = DrakonGenerator(flowcharts_dir, db_path=args.db_path,
                                         simplified=_simplified)
            else:
                fc_gen = ELKFlowchartGenerator(flowcharts_dir, db_path=args.db_path,
                                               output_format=args.flowchart_format,
                                               simplified=_simplified)
        else:
            fc_gen = None

        # RouteStreamWriter создаёт файлы в конструкторе, поэтому создаём его ТОЛЬКО если нужны маршруты
        route_writer = RouteStreamWriter(Path(args.output)) if needs_routes else None

        if fc_gen or needs_routes or needs_branch_routes:
            if fc_gen:
                _log_action(start_time, "БЛОК-СХЕМЫ", "Старт генерации блок-схем")
                print(f"[DEBUG] === ИНФОРМАЦИЯ О ДАННЫХ ПЕРЕД ГЕНЕРАЦИЕЙ ===", flush=True)
                print(f"[DEBUG] func_data: {len(func_data)} функций", flush=True)
                print(f"[DEBUG] flow_data: {len(flow_data)} statements (~{sys.getsizeof(flow_data)/1024/1024:.1f} MB)", flush=True)
                print(f"[DEBUG] info_data: {len(info_data)} переменных (~{sys.getsizeof(info_data)/1024/1024:.1f} MB)", flush=True)
                print(f"[DEBUG] ctrl_data: {len(ctrl_data)} вызовов (~{sys.getsizeof(ctrl_data)/1024/1024:.1f} MB)", flush=True)
                print(f"[DEBUG] data_data: {len(data_data) if data_data else 0} доступов (~{sys.getsizeof(data_data)/1024/1024:.1f} MB) *** БОЛЬШОЙ!", flush=True)
                print(f"[DEBUG] file_flow_data: {len(file_flow_data) if file_flow_data else 0} файловых опер.", flush=True)
            else:
                _log_action(start_time, "МАРШРУТЫ", "Генерирую маршруты/ветви (без создания файлов блок-схем)")
                flowcharts_dir = str(Path(args.output) / "flowcharts")
                renderer = getattr(args, "flowchart_renderer", "elk")
                _simplified = getattr(args, "simplified_flowcharts", False)
                # clear_output=False: блок-схемы не запрошены — не трогаем
                # SVG предыдущих запусков в каталоге flowcharts.
                if renderer == "drakon":
                    fc_gen = DrakonGenerator(flowcharts_dir, db_path=args.db_path,
                                             clear_output=False, simplified=_simplified)
                else:
                    fc_gen = ELKFlowchartGenerator(flowcharts_dir, db_path=args.db_path,
                                                   output_format=args.flowchart_format,
                                                   clear_output=False, simplified=_simplified)

            # DrakonGenerator только рисует SVG: маршруты/ветви он не вычисляет
            # и route_writer игнорирует — для него второй проход ниже.
            is_drakon = getattr(args, "flowchart_renderer", "elk") == "drakon"

            # Передаём ТОЛЬКО данные, относящиеся к ФО, чтобы не грузить всё в памяти
            generated, routes_by_func, branch_edges_by_func, branch_inventory_by_func = fc_gen.generate_all(
                func_data, flow_data, info_data, ctrl_data,
                data_data, file_flow_data,
                route_writer=None if is_drakon else route_writer,
                load_by_demand=True,  # Загружать данные по требованию
                build_flowcharts=_should_create_report(selected_reports, "flowcharts"),  # Файлы только если нужны
                need_routes_in_memory=needs_branch_routes,  # Накапливать routes_by_func для Граф_ветвей/маршрутов
                max_routes=args.max_routes  # Лимит маршрутов на ФО
            )
            if is_drakon and (needs_routes or needs_branch_routes):
                # Второй проход (как в project_runner): FlowchartGenerator без
                # рендеринга SVG заполняет маршруты/ветви и пишет route_writer.
                _fgen = FlowchartGenerator(str(Path(args.output) / "flowcharts"),
                                           db_path=args.db_path, clear_output=False)
                _, routes_by_func, branch_edges_by_func, branch_inventory_by_func = _fgen.generate_all(
                    func_data, flow_data, info_data, ctrl_data,
                    data_data, file_flow_data, route_writer=route_writer,
                    load_by_demand=True, build_flowcharts=False,
                    need_routes_in_memory=needs_branch_routes,
                    max_routes=args.max_routes
                )
            if _should_create_report(selected_reports, "flowcharts"):
                _log_action(start_time, "БЛОК-СХЕМЫ", "Сгенерировано блок-схем", str(len(generated)))
                _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Блок-схемы (PNG) в папке flowcharts")
        else:
            generated, routes_by_func = [], {}

        if route_writer:
            route_writer.close()
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Маршруты_выполнения_ФО(ветвей).csv")
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Маршруты_выполнения_ФО(процедур_функций).csv")
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Аргументные_потоки.csv")

    # Построение графов маршрутов
    if needs_graphs:
        _log_action(start_time, "ГРАФЫ", "Старт построения графов анализа")

        # Создаём индекс функций для нумерации
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data)}

        graph_builder = GraphBuilder()

        # Граф функций
        if _should_create_report(selected_reports, "Граф_функций.csv"):
            _log_action(start_time, "ГРАФЫ", "Старт создания графа функций")
            func_edges = graph_builder.build_function_graph(ctrl_data)
            report.add_function_graph(func_edges, func_index, func_data)
            _log_action(start_time, "ГРАФЫ", "Граф функций создан", f"{len(func_data)} узлов/{len(func_edges)} рёбер")
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Граф_функций.csv")

        # Граф ветвей — используем полный структурный граф переходов (branch_edges_by_func),
        # покрывающий все ветки (в отличие от извлечения из ограниченных кэпом маршрутов).
        if _should_create_report(selected_reports, "Граф_ветвей.csv"):
            _log_action(start_time, "ГРАФЫ", "Старт создания графа ветвей")
            branch_graph = graph_builder.build_branch_graph(func_data, routes_by_func, branch_edges_by_func)
            report.add_branch_graph(branch_graph, func_index)
            total_branches = sum(len(edges) for edges in branch_graph.values())
            _log_action(start_time, "ГРАФЫ", "Граф ветвей создан", f"{total_branches} рёбер")
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Граф_ветвей.csv")

        # Граф маршрутов
        if _should_create_report(selected_reports, "Граф_маршрутов.csv"):
            _log_action(start_time, "ГРАФЫ", "Старт создания графа маршрутов")
            branch_graph = graph_builder.build_branch_graph(func_data, routes_by_func, branch_edges_by_func)
            route_edges = graph_builder.build_route_graph(func_data, ctrl_data, branch_graph)
            report.add_route_graph(route_edges, func_index)
            _log_action(start_time, "ГРАФЫ", "Граф маршрутов создан", f"{len(route_edges)} рёбер")
            _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Граф_маршрутов.csv")

    # Перечень ветвей: последовательный номер (#N) и местоположение в исходниках.
    # Для сверки состава/количества ветвей между статикой и динамикой.
    if needs_branch_list:
        _log_action(start_time, "ВЕТВИ", "Старт создания перечня ветвей")
        func_index = {item["qualified_name"]: i + 1 for i, item in enumerate(func_data)}
        func_file = {item["qualified_name"]: item.get("file", "") for item in func_data}
        report.add_branch_inventory(branch_inventory_by_func, func_index, func_file, func_data)
        total_branches = sum(len(v) for v in branch_inventory_by_func.values())
        _log_action(start_time, "ВЕТВИ", "Перечень ветвей создан", f"{total_branches} ветвей в {len(branch_inventory_by_func)} ФО")
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет", "Перечень_ветвей.csv")

    # Критические маршруты: критический ИО ИЛИ опасная конструкция на маршруте.
    if needs_critical_routes:
        crit_nums = read_critical_io_numbers(args.critical_io)
        report.add_critical_routes(func_data, routes_by_func, branch_inventory_by_func,
                                   info_data, data_data, sig_data, crit_nums)
        _log_action(start_time, "ОТЧЕТЫ", "Создан отчет",
                    f"Критические_маршруты.csv (критических ИО: {len(crit_nums)})")

    _log_action(start_time, "ОТЧЕТЫ", "Старт сохранения отчётов")
    report.save()
    _log_action(start_time, "ОТЧЕТЫ", "Конец сохранения отчётов", "все файлы сохранены")

    elapsed = time.time() - start_time
    minutes = int(elapsed) // 60
    seconds = int(elapsed) % 60
    time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
    print(f"[ИТОГО] Анализ завершён за {time_str}", flush=True)
    print("="*70, flush=True)


if __name__ == "__main__":
    main()
