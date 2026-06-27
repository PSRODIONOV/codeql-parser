"""Тесты слоя персистентности project_db.ProjectDB (Фаза 1)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.project_db import ProjectDB, DATASET_TABLE  # noqa: E402


@pytest.fixture
def proj(tmp_path):
    db = ProjectDB.create(str(tmp_path), "demo", codeql_db_path="/x/db",
                          language="python", pattern="%demo%")
    yield db
    db.close()


def test_structure_created(tmp_path):
    db = ProjectDB.create(str(tmp_path), "p1")
    root = tmp_path / "p1"
    assert (root / "project.db").exists()
    assert (root / "reports" / "static").is_dir()
    assert (root / "reports" / "dynamic" / "traces").is_dir()
    assert (root / "orig-sources").is_dir()
    assert (root / "src-instrumented").is_dir()
    db.close()


def test_project_meta(proj):
    p = proj.get_project()
    assert p["name"] == "demo"
    assert p["language"] == "python"
    assert p["pattern"] == "%demo%"


def test_static_params_roundtrip(proj):
    proj.set_static_params(8192, 2000, ["Перечень_ФО(процедур_функций).csv", "flowcharts"])
    st = proj.get_static_state()
    assert st["ram_mb"] == 8192
    assert st["max_routes"] == 2000
    assert "flowcharts" in st["selected_checks"]
    assert st["status"] == "none"
    proj.set_static_status("done")
    assert proj.get_static_state()["status"] == "done"


def test_raw_data_roundtrip(proj):
    datasets = {
        "functional": [
            {"qualified_name": "Calculator.add", "name": "add", "parent_type": "Calculator",
             "file": "calc.py", "line": "10", "kind": "member function"},
            {"qualified_name": "main", "name": "main", "parent_type": "(global)",
             "file": "main.py", "line": "17", "kind": "function"},
        ],
        "control": [
            {"caller_name": "main", "callee_name": "Calculator.add",
             "caller_file": "main.py", "callee_file": "calc.py", "call_line": "25"},
        ],
        "flow": [
            {"func_name": "Calculator.div", "func_file": "calc.py",
             "stmt_id": "calc.py:25", "line_start": "25",
             "line_end": "25", "stmt_type": "if", "stmt_label": "if (b == 0)",
             "else_line": "", "in_catch": "0"},
        ],
    }
    proj.save_raw_data(datasets)
    loaded = proj.load_raw_data()
    # функциональные объекты восстановлены 1:1
    assert loaded["functional"] == datasets["functional"]
    assert loaded["control"] == datasets["control"]
    assert loaded["flow"] == datasets["flow"]
    # незаполненные наборы — пустые списки
    assert loaded["info"] == []
    assert loaded["signature"] == []


def test_all_datasets_known():
    # ключи наборов должны совпадать с тем, что использует main.py / project_runner.
    # 'probe' — геометрия точек вставки датчиков (probe_points.ql), собирается в
    # сырые данные для инструментации без отдельного запроса (см. instrument_cpp.py).
    assert set(DATASET_TABLE) == {
        "functional", "info", "files", "signature", "control",
        "data", "arg_flow", "file_flow", "flow", "probe",
    }


def test_probe_dataset_roundtrip(proj):
    """Геометрия точек вставки датчиков (раздел 'probe') сохраняется/читается
    из project.db 1:1 — инструментатор берёт её отсюда без отдельного запроса."""
    probe = [
        {"kind": "entry", "func": "f", "file": "a.cpp", "ref_line": "5",
         "ins_line": "5", "ins_col": "10", "has_block": "1", "btype": "-",
         "end_line": "9", "end_col": "1"},
        {"kind": "branch", "func": "f", "file": "a.cpp", "ref_line": "6",
         "ins_line": "6", "ins_col": "16", "has_block": "0", "btype": "if",
         "end_line": "6", "end_col": "20"},
    ]
    proj.save_raw_data({"probe": probe})
    loaded = proj.load_raw_data()
    assert loaded["probe"] == probe


def test_derived_roundtrip(proj):
    # мелкие значения — через kv-таблицу derived
    proj.save_derived("include_patterns", ["*/src/*"])
    assert proj.load_derived("include_patterns") == ["*/src/*"]


def test_sensor_filters_roundtrip(proj):
    """Белый/чёрный список вставки датчиков (вкладка «Динамический анализ»)
    — отдельно от set_file_filters (область статического анализа),
    сохраняется и читается в рамках проекта."""
    assert proj.get_sensor_filters() == {"include": [], "exclude": []}
    proj.set_sensor_filters(["*/com/example/*"], ["java/lang/ref/*", "java/util/concurrent/*"])
    assert proj.get_sensor_filters() == {
        "include": ["*/com/example/*"],
        "exclude": ["java/lang/ref/*", "java/util/concurrent/*"],
    }


def test_derived_map_roundtrip(proj):
    # dict[func -> value] — построчно (без гигантских JSON-строк)
    branch_inv = {
        "Calculator.div": [{"branch_num": 1, "type": "if", "line": "25"}],
        "factorial": [{"branch_num": 1, "type": "if", "line": "5"},
                      {"branch_num": 2, "type": "for", "line": "10"}],
    }
    proj.save_derived_map("branch_inventory_by_func", branch_inv)
    assert proj.load_derived_map("branch_inventory_by_func") == branch_inv
    assert proj.has_branch_reports() is True


def test_has_branch_reports_false_by_default(proj):
    assert proj.has_branch_reports() is False


def test_flowcharts_roundtrip(proj):
    items = [
        {"fo_num": 1, "fo_name": "Calculator.add", "filename": "1_Calculator.add.svg",
         "svg": "<svg>...</svg>"},
        {"fo_num": 5, "fo_name": "Calculator.div", "filename": "5_Calculator.div.svg",
         "svg": "<svg>branch</svg>"},
    ]
    proj.save_flowcharts(items)
    loaded = proj.load_flowcharts()
    assert len(loaded) == 2
    assert loaded[0]["svg"] == "<svg>...</svg>"
    assert loaded[1]["fo_name"] == "Calculator.div"


def test_traces_and_counter(proj):
    assert proj.trace_count() == 0
    proj.add_trace("python-1.log", 42)
    proj.add_trace("python-2.log", 13)
    assert proj.trace_count() == 2
    names = [t["filename"] for t in proj.list_traces()]
    assert names == ["python-1.log", "python-2.log"]


def test_coverage_roundtrip(proj):
    proj.save_coverage(
        fo_rows=[(1, "Calculator.add", "да"), (2, "Calculator.div", "нет")],
        branch_rows=[(2, 1, "if", "calc.py", "25", "да"),
                     (2, 2, "if", "calc.py", "25", "нет")],
        summary_rows=[(2, "Calculator.div", 2, 1, "50.0%")],
    )
    t = proj.coverage_totals()
    assert t["fo_total"] == 2 and t["fo_covered"] == 1
    assert t["branch_total"] == 2 and t["branch_covered"] == 1


def test_coverage_totals_excludes_not_instrumented(proj):
    """fo_total/branch_total — ВСЕ объекты статики (включая "не инстр."),
    fo_instrumented/branch_instrumented — без них (см. coverage_report.py:
    fo_status/br_status проставляют "не инстр." самодостаточным макросам/
    идиоме CHECK, у которых нет датчика)."""
    proj.save_coverage(
        fo_rows=[(1, "foo", "да"), (2, "bar", "нет"), (3, "macro_fo", "не инстр.")],
        branch_rows=[(1, 1, "if", "f.cpp", "10", "да"),
                     (1, 2, "if", "f.cpp", "20", "не инстр.")],
        summary_rows=[],
    )
    t = proj.coverage_totals()
    assert t["fo_total"] == 3 and t["fo_instrumented"] == 2 and t["fo_covered"] == 1
    assert t["branch_total"] == 2 and t["branch_instrumented"] == 1 and t["branch_covered"] == 1


def test_clear_dynamic_coverage(proj):
    """Обнуление покрытия: трассы (БД + файлы в traces_dir) и
    coverage_*-таблицы очищаются; instrumented/src-instrumented — нет."""
    proj.traces_dir.mkdir(parents=True, exist_ok=True)
    (proj.traces_dir / "run-1.log").write_text("hit", encoding="utf-8")
    proj.add_trace("run-1.log", 1)
    proj.save_coverage(
        fo_rows=[(1, "Calculator.add", "да")],
        branch_rows=[(1, 1, "if", "calc.py", "10", "да")],
        summary_rows=[(1, "Calculator.add", 1, 1, "100.0%")],
    )
    proj.set_dynamic_state(instrumented=True, status="done")
    proj.reports_dynamic.mkdir(parents=True, exist_ok=True)
    (proj.reports_dynamic / "Покрытие_ФО.csv").write_text("x", encoding="utf-8")

    proj.clear_dynamic_coverage()

    assert proj.trace_count() == 0
    assert list(proj.traces_dir.glob("*")) == []
    assert not (proj.reports_dynamic / "Покрытие_ФО.csv").exists()
    t = proj.coverage_totals()
    assert t["fo_total"] == 0 and t["branch_total"] == 0
    st = proj.get_dynamic_state()
    assert st["status"] == "none"
    assert st["instrumented"] == 1  # инструментация не сбрасывается


def test_dynamic_state_roundtrip(proj):
    proj.set_dynamic_state(branches_enabled=True, extra_args="--foo", instrumented=True)
    st = proj.get_dynamic_state()
    assert st["branches_enabled"] == 1
    assert st["extra_args"] == "--foo"
    assert st["instrumented"] == 1
    proj.set_dynamic_state(status="done")
    assert proj.get_dynamic_state()["status"] == "done"


def test_reopen_persists(tmp_path):
    db = ProjectDB.create(str(tmp_path), "reopen")
    db.set_static_params(2048, 500, ["x"])
    db.set_static_status("done")
    db.set_stat("fo_total", 42)
    db.close()
    # повторное открытие
    db2 = ProjectDB.open(str(tmp_path / "reopen"))
    assert db2.get_static_state()["status"] == "done"
    assert db2.get_static_state()["ram_mb"] == 2048
    assert db2.get_stats()["fo_total"] == "42"
    db2.close()
