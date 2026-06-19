"""project_db.py — слой персистентности проекта на SQLite3.

Проект = каталог + project.db внутри. В базе хранятся:
  • метаданные проекта, параметры и статус статики/динамики;
  • 9 сырых наборов результатов запросов CodeQL (на их основе строятся все отчёты);
  • производные данные выбранных проверок (перечень ветвей, маршруты, графы) — JSON;
  • блок-схемы (SVG) — отдельной таблицей;
  • реестр трасс и результаты покрытия (динамический анализ).

Цель: отчёты можно создать из базы без повторного прогона CodeQL/ELK.
Используется только стандартная библиотека (sqlite3, json) — новых зависимостей нет.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Колонки 9 сырых наборов (= as-алиасы в queries/<lang>/*.ql, одинаковы по языкам) ──
RAW_SCHEMA: Dict[str, List[str]] = {
    "q_functional": ["qualified_name", "name", "parent_type", "file", "line", "kind"],
    "q_info":       ["qualified_name", "name", "type_name", "file", "line", "kind"],
    "q_files":      ["abs_path", "base_name"],
    "q_signature":  ["cwe", "category", "signature", "function_name", "func_file", "line"],
    # callee_file — файл объявления callee (по нему различаются одноимённые
    # функции при нумерации вызываемых; legacy-БД: колонка пуста, fallback по имени)
    "q_control":    ["caller_name", "callee_name", "caller_file", "callee_file", "call_line"],
    "q_data":       ["function_name", "variable_name", "func_file", "access_line", "access_type"],
    "q_arg_flow":   ["caller_name", "callee_name", "caller_var", "param_var", "caller_file", "call_line"],
    "q_file_flow":  ["function_name", "func_file", "file_name", "access_type", "access_line"],
    # func_file обязателен: function_flow_v2.ql его возвращает, дедупликация
    # в codeql_analyzer и группировка операторов по (имя, файл) в генераторах
    # на него опираются — без него одноимённые функции сливаются.
    "q_flow":       ["func_name", "func_file", "stmt_id", "line_start", "line_end",
                     "stmt_type", "stmt_label", "else_line", "in_catch"],
}

# Сопоставление имени набора в коде (main.py) ↔ таблицы БД
DATASET_TABLE = {
    "functional":  "q_functional",
    "info":        "q_info",
    "files":       "q_files",
    "signature":   "q_signature",
    "control":     "q_control",
    "data":        "q_data",
    "arg_flow":    "q_arg_flow",
    "file_flow":   "q_file_flow",
    "flow":        "q_flow",
}

PROJECT_FILE = "project.db"


class ProjectDB:
    """Обёртка над project.db. Открывается через ProjectDB.create() / ProjectDB.open()."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.root = self.db_path.parent
        # check_same_thread=False: соединение используется и из GUI-потока,
        # и из рабочего QThread (анализ). Доступ последовательный (воркер
        # работает один, главный поток читает только после сигнала done),
        # а sqlite3 в Python собран в serialized-режиме — это безопасно.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate_schema()

    def _migrate_schema(self):
        """Миграция существующих project.db: добиваем недостающие колонки
        сырых наборов и таблицы static_state (схема могла расшириться)."""
        try:
            existing = {r["name"] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            changed = False
            for table, cols in RAW_SCHEMA.items():
                if table not in existing:
                    continue  # таблицы создаст _create_schema при create()
                have = {r["name"] for r in self.conn.execute(f'PRAGMA table_info("{table}")')}
                for col in cols:
                    if col not in have:
                        self.conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" TEXT')
                        changed = True
            # Миграция static_state: новые колонки версий
            if "static_state" in existing:
                ss_have = {r["name"] for r in self.conn.execute(
                    'PRAGMA table_info("static_state")')}
                if "simplified_flowcharts" not in ss_have:
                    self.conn.execute(
                        'ALTER TABLE "static_state" ADD COLUMN '
                        '"simplified_flowcharts" INTEGER DEFAULT 0')
                    changed = True
            # Миграция project: sql_dialect для SQL-проектов
            if "project" in existing:
                proj_have = {r["name"] for r in self.conn.execute(
                    'PRAGMA table_info("project")')}
                if "sql_dialect" not in proj_have:
                    self.conn.execute(
                        'ALTER TABLE "project" ADD COLUMN "sql_dialect" TEXT DEFAULT "mysql"')
                    changed = True
            if changed:
                self.conn.commit()
        except sqlite3.Error:
            pass  # не блокируем открытие проекта из-за миграции

    # ── Создание / открытие ──────────────────────────────────────────────────
    @classmethod
    def create(cls, location: str, name: str, codeql_db_path: str = "",
               language: str = "cpp", pattern: str = "",
               sql_dialect: str = "mysql") -> "ProjectDB":
        """Создаёт каталог <location>/<name>/ со стандартной структурой и project.db."""
        root = Path(location) / name
        for sub in ("reports/static", "reports/dynamic/traces",
                    "orig-sources", "src-instrumented"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        db = cls(root / PROJECT_FILE)
        db._create_schema()
        db.conn.execute(
            "INSERT INTO project(id, name, created_at, codeql_db_path, language, pattern, sql_dialect) "
            "VALUES (1, ?, ?, ?, ?, ?, ?)",
            (name, _now(), codeql_db_path, language, pattern, sql_dialect),
        )
        db.conn.execute(
            "INSERT INTO static_state(id, ram_mb, max_routes, selected_checks_json, status, "
            "simplified_flowcharts) VALUES (1, 4096, 1000, '[]', 'none', 0)"
        )
        db.conn.execute(
            "INSERT INTO dynamic_state(id, branches_enabled, extra_args, instrumented, status) "
            "VALUES (1, 0, '', 0, 'none')"
        )
        db.conn.commit()
        return db

    @classmethod
    def open(cls, project_db_path: str) -> "ProjectDB":
        p = Path(project_db_path)
        if p.is_dir():
            p = p / PROJECT_FILE
        if not p.exists():
            raise FileNotFoundError(f"project.db not found: {p}")
        return cls(p)

    def close(self):
        self.conn.close()

    # ── Структурные пути проекта ─────────────────────────────────────────────
    @property
    def reports_static(self) -> Path:
        return self.root / "reports" / "static"

    @property
    def reports_dynamic(self) -> Path:
        return self.root / "reports" / "dynamic"

    @property
    def traces_dir(self) -> Path:
        return self.root / "reports" / "dynamic" / "traces"

    @property
    def orig_sources(self) -> Path:
        return self.root / "orig-sources"

    @property
    def src_instrumented(self) -> Path:
        return self.root / "src-instrumented"

    # ── Схема ────────────────────────────────────────────────────────────────
    def _create_schema(self):
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS project(
            id INTEGER PRIMARY KEY, name TEXT, created_at TEXT,
            codeql_db_path TEXT, language TEXT, pattern TEXT,
            sql_dialect TEXT DEFAULT 'mysql')""")
        c.execute("""CREATE TABLE IF NOT EXISTS static_state(
            id INTEGER PRIMARY KEY, ram_mb INTEGER, max_routes INTEGER,
            selected_checks_json TEXT, status TEXT, finished_at TEXT,
            simplified_flowcharts INTEGER DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS dynamic_state(
            id INTEGER PRIMARY KEY, branches_enabled INTEGER, extra_args TEXT,
            instrumented INTEGER, status TEXT, finished_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS stats(
            key TEXT PRIMARY KEY, value TEXT)""")

        # 9 сырых наборов
        for table, cols in RAW_SCHEMA.items():
            col_defs = ", ".join(f'"{col}" TEXT' for col in cols)
            c.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (row_id INTEGER PRIMARY KEY, {col_defs})')

        # Производные данные статики (вложенные структуры — JSON).
        # derived     — мелкие значения целиком (списки шаблонов и т.п.).
        # derived_map — структуры dict[func -> value] построчно по функциям,
        #               чтобы ни одна JSON-строка не превышала лимит SQLite
        #               (routes_by_func крупного проекта целиком > 2 ГБ).
        c.execute("""CREATE TABLE IF NOT EXISTS derived(
            name TEXT PRIMARY KEY, data_json TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS derived_map(
            name TEXT, func TEXT, data_json TEXT)""")
        c.execute("""CREATE INDEX IF NOT EXISTS idx_derived_map_name
            ON derived_map(name)""")
        c.execute("""CREATE TABLE IF NOT EXISTS d_flowcharts(
            fo_num INTEGER, fo_name TEXT, filename TEXT, svg TEXT)""")

        # Динамика
        c.execute("""CREATE TABLE IF NOT EXISTS traces(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT, added_at TEXT, line_count INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS coverage_fo(
            fo_num INTEGER, fo_name TEXT, covered TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS coverage_branch(
            fo_num INTEGER, branch_num INTEGER, type TEXT, file TEXT, line TEXT, covered TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS coverage_summary(
            fo_num INTEGER, fo_name TEXT, total INTEGER, covered INTEGER, pct TEXT)""")
        c.commit()

    # ── Метаданные / параметры / статус ──────────────────────────────────────
    def get_project(self) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM project WHERE id=1").fetchone()
        return dict(row) if row else {}

    def set_static_params(self, ram_mb: int, max_routes: int, selected_checks: List[str],
                          simplified_flowcharts: bool = False):
        self.conn.execute(
            "UPDATE static_state SET ram_mb=?, max_routes=?, selected_checks_json=?, "
            "simplified_flowcharts=? WHERE id=1",
            (ram_mb, max_routes, json.dumps(selected_checks, ensure_ascii=False),
             int(simplified_flowcharts)),
        )
        self.conn.commit()

    def set_static_status(self, status: str):
        self.conn.execute(
            "UPDATE static_state SET status=?, finished_at=? WHERE id=1",
            (status, _now() if status == "done" else None),
        )
        self.conn.commit()

    def get_static_state(self) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM static_state WHERE id=1").fetchone()
        d = dict(row) if row else {}
        if d.get("selected_checks_json"):
            d["selected_checks"] = json.loads(d["selected_checks_json"])
        else:
            d["selected_checks"] = []
        d["simplified_flowcharts"] = bool(d.get("simplified_flowcharts", 0))
        return d

    def set_dynamic_state(self, *, branches_enabled: Optional[bool] = None,
                          extra_args: Optional[str] = None,
                          instrumented: Optional[bool] = None,
                          status: Optional[str] = None):
        cur = self.get_dynamic_state()
        be = int(branches_enabled) if branches_enabled is not None else cur["branches_enabled"]
        ea = extra_args if extra_args is not None else cur["extra_args"]
        ins = int(instrumented) if instrumented is not None else cur["instrumented"]
        st = status if status is not None else cur["status"]
        fin = _now() if st == "done" else cur.get("finished_at")
        self.conn.execute(
            "UPDATE dynamic_state SET branches_enabled=?, extra_args=?, instrumented=?, "
            "status=?, finished_at=? WHERE id=1", (be, ea, ins, st, fin))
        self.conn.commit()

    def get_dynamic_state(self) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM dynamic_state WHERE id=1").fetchone()
        return dict(row) if row else {}

    def set_stat(self, key: str, value: Any):
        self.conn.execute(
            "INSERT INTO stats(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self.conn.commit()

    def get_stats(self) -> Dict[str, str]:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM stats")}

    # ── 9 сырых наборов ──────────────────────────────────────────────────────
    def save_raw_data(self, datasets: Dict[str, List[Dict[str, str]]]):
        """datasets: {'functional': [...], 'info': [...], ...} — ключи из DATASET_TABLE."""
        for ds_name, rows in datasets.items():
            table = DATASET_TABLE.get(ds_name)
            if not table:
                continue
            cols = RAW_SCHEMA[table]
            self.conn.execute(f'DELETE FROM "{table}"')
            placeholders = ", ".join("?" for _ in cols)
            col_list = ", ".join(f'"{c}"' for c in cols)
            self.conn.executemany(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})',
                [tuple(str(r.get(c, "")) for c in cols) for r in (rows or [])],
            )
        self.conn.commit()

    def load_raw_data(self) -> Dict[str, List[Dict[str, str]]]:
        """Возвращает наборы в том же формате List[Dict], что потребляют генераторы."""
        out: Dict[str, List[Dict[str, str]]] = {}
        for ds_name, table in DATASET_TABLE.items():
            cols = RAW_SCHEMA[table]
            col_list = ", ".join(f'"{c}"' for c in cols)
            rows = self.conn.execute(f'SELECT {col_list} FROM "{table}" ORDER BY row_id').fetchall()
            out[ds_name] = [{c: r[c] for c in cols} for r in rows]
        return out

    # ── Производные структуры (JSON) ─────────────────────────────────────────
    def save_derived(self, name: str, data: Any):
        self.conn.execute(
            "INSERT INTO derived(name, data_json) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET data_json=excluded.data_json",
            (name, json.dumps(data, ensure_ascii=False)))
        self.conn.commit()

    def load_derived(self, name: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT data_json FROM derived WHERE name=?", (name,)).fetchone()
        return json.loads(row["data_json"]) if row else default

    def has_derived(self, name: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM derived WHERE name=?", (name,)).fetchone() is not None

    # ── Производные структуры dict[func -> value]: построчно по функциям ──────
    # Предел на одну функцию: SQLite/Python не хранят строку > INT_MAX (~2 ГБ).
    # При экстремальном max_routes одна функция (экспоненциальный взрыв путей)
    # может дать огромный список — усекаем, чтобы анализ не падал.
    _ROW_LIMIT = 256 * 1024 * 1024  # 256 МБ JSON на функцию

    def save_derived_map(self, name: str, data: Dict[str, Any]):
        """Сохраняет dict[func -> value] по одной строке на функцию (без огромных
        JSON-строк, которые упираются в лимит SQLite на крупных проектах)."""
        c = self.conn
        c.execute("DELETE FROM derived_map WHERE name=?", (name,))
        rows = []
        for k, v in (data or {}).items():
            js = json.dumps(v, ensure_ascii=False)
            # Если значение-список слишком велико — усекаем половинным делением.
            orig_len = len(v) if isinstance(v, list) else None
            while len(js) > self._ROW_LIMIT and isinstance(v, list) and len(v) > 1:
                v = v[: len(v) // 2]
                js = json.dumps(v, ensure_ascii=False)
            if orig_len is not None and isinstance(v, list) and len(v) < orig_len:
                # Усечение не должно происходить молча: перечень становится
                # неполным (важно для требований полноты РД НДВ).
                print(f"[ПРЕДУПРЕЖДЕНИЕ] {name}: данные функции '{k}' усечены "
                      f"{orig_len} -> {len(v)} элементов (лимит "
                      f"{self._ROW_LIMIT // (1024 * 1024)} МБ JSON на функцию)",
                      flush=True)
            rows.append((name, k, js))
        c.executemany(
            "INSERT INTO derived_map(name, func, data_json) VALUES (?, ?, ?)", rows)
        c.commit()

    def load_derived_map(self, name: str) -> Dict[str, Any]:
        rows = self.conn.execute(
            "SELECT func, data_json FROM derived_map WHERE name=?", (name,)).fetchall()
        return {r["func"]: json.loads(r["data_json"]) for r in rows}

    def load_derived_map_one(self, name: str, func: str, default: Any = None) -> Any:
        """Загружает значение одной функции (для потоковой обработки без
        удержания всей структуры в памяти)."""
        row = self.conn.execute(
            "SELECT data_json FROM derived_map WHERE name=? AND func=?",
            (name, func)).fetchone()
        return json.loads(row["data_json"]) if row else default

    def has_branch_reports(self) -> bool:
        """Есть ли в составе статики данные по ветвям (для гейтинга чек-бокса ветвей)."""
        return self.conn.execute(
            "SELECT 1 FROM derived_map WHERE name='branch_inventory_by_func' LIMIT 1"
        ).fetchone() is not None

    # ── Фильтры файлов (белый/чёрный списки) ─────────────────────────────────
    def set_file_filters(self, include: List[str], exclude: List[str],
                         include_list: Optional[List[str]] = None,
                         exclude_list: Optional[List[str]] = None):
        self.save_derived("include_patterns", include or [])
        self.save_derived("exclude_patterns", exclude or [])
        # include_list/exclude_list — явный список путей (см.
        # core/file_lists.py), ОБЩИЙ для статического анализа и
        # инструментации: instrument_c_make.py/instrument_cpp.py читают
        # его отсюда же, чтобы видеть то же подмножество файлов, что и
        # статика — без этого два этапа могли бы рассинхронизироваться.
        self.save_derived("include_file_list", include_list or [])
        self.save_derived("exclude_file_list", exclude_list or [])

    def get_file_filters(self) -> Dict[str, List[str]]:
        return {
            "include": self.load_derived("include_patterns", []) or [],
            "exclude": self.load_derived("exclude_patterns", []) or [],
            "include_list": self.load_derived("include_file_list", []) or [],
            "exclude_list": self.load_derived("exclude_file_list", []) or [],
        }

    # ── Блок-схемы (SVG) ─────────────────────────────────────────────────────
    def save_flowcharts(self, items: List[Dict[str, Any]]):
        """items: [{'fo_num', 'fo_name', 'filename', 'svg'}, ...]."""
        self.conn.execute("DELETE FROM d_flowcharts")
        self.conn.executemany(
            "INSERT INTO d_flowcharts(fo_num, fo_name, filename, svg) VALUES (?, ?, ?, ?)",
            [(it.get("fo_num"), it.get("fo_name", ""), it.get("filename", ""), it.get("svg", ""))
             for it in items])
        self.conn.commit()

    def load_flowcharts(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT fo_num, fo_name, filename, svg FROM d_flowcharts ORDER BY fo_num").fetchall()
        return [dict(r) for r in rows]

    # ── Динамика: трассы и покрытие ──────────────────────────────────────────
    def add_trace(self, filename: str, line_count: int = 0) -> int:
        cur = self.conn.execute(
            "INSERT INTO traces(filename, added_at, line_count) VALUES (?, ?, ?)",
            (filename, _now(), line_count))
        self.conn.commit()
        return cur.lastrowid

    def list_traces(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id, filename, added_at, line_count FROM traces ORDER BY id")]

    def trace_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM traces").fetchone()["n"]

    def save_coverage(self, fo_rows: List[tuple], branch_rows: List[tuple],
                      summary_rows: List[tuple]):
        c = self.conn
        c.execute("DELETE FROM coverage_fo")
        c.execute("DELETE FROM coverage_branch")
        c.execute("DELETE FROM coverage_summary")
        c.executemany("INSERT INTO coverage_fo(fo_num, fo_name, covered) VALUES (?,?,?)", fo_rows)
        c.executemany("INSERT INTO coverage_branch(fo_num, branch_num, type, file, line, covered) "
                      "VALUES (?,?,?,?,?,?)", branch_rows)
        c.executemany("INSERT INTO coverage_summary(fo_num, fo_name, total, covered, pct) "
                      "VALUES (?,?,?,?,?)", summary_rows)
        c.commit()

    def coverage_totals(self) -> Dict[str, int]:
        """Сводные счётчики покрытия для статистики GUI."""
        c = self.conn
        fo_total = c.execute("SELECT COUNT(*) n FROM coverage_fo").fetchone()["n"]
        fo_cov = c.execute(
            "SELECT COUNT(*) n FROM coverage_fo WHERE covered='да'").fetchone()["n"]
        br_total = c.execute("SELECT COUNT(*) n FROM coverage_branch").fetchone()["n"]
        br_cov = c.execute(
            "SELECT COUNT(*) n FROM coverage_branch WHERE covered='да'").fetchone()["n"]
        return {"fo_total": fo_total, "fo_covered": fo_cov,
                "branch_total": br_total, "branch_covered": br_cov}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
