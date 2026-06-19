"""sql_analyzer.py — SQL source code analyzer.

Parses .sql files (stored procedures, functions, triggers, views) and returns
the same 9-dataset dict as CodeQLAnalyzer / JoernAnalyzer so that
project_runner.py can use it transparently for SQL projects.

Requires: sqlglot  (pip install sqlglot)
Falls back to regex-based extraction when sqlglot is not installed.

Supported dialects (--sql-dialect):
  mysql / mariadb, postgres / postgresql, tsql / mssql / sqlserver,
  oracle, sqlite, spark, bigquery, generic
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    import sqlglot
    import sqlglot.expressions as exp
    from sqlglot.errors import ErrorLevel
    _SQLGLOT_OK = True
except ImportError:
    _SQLGLOT_OK = False

# ── Dataset column schema (mirrors project_db.RAW_SCHEMA) ─────────────────────
DATASETS: Dict[str, List[str]] = {
    "functional": ["qualified_name", "name", "parent_type", "file", "line", "kind"],
    "info":       ["qualified_name", "name", "type_name", "file", "line", "kind"],
    "files":      ["abs_path", "base_name"],
    "control":    ["caller_name", "callee_name", "caller_file", "callee_file", "call_line"],
    "data":       ["function_name", "variable_name", "func_file", "access_line", "access_type"],
    "arg_flow":   ["caller_name", "callee_name", "caller_var", "param_var", "caller_file", "call_line"],
    "file_flow":  ["function_name", "func_file", "file_name", "access_type", "access_line"],
    "signature":  ["cwe", "category", "signature", "function_name", "func_file", "line"],
    "flow":       ["func_name", "func_file", "stmt_id", "line_start", "line_end",
                   "stmt_type", "stmt_label", "else_line", "in_catch"],
}

DIALECT_ALIASES: Dict[str, Optional[str]] = {
    "mysql":      "mysql",
    "mariadb":    "mysql",
    "postgres":   "postgres",
    "postgresql": "postgres",
    "tsql":       "tsql",
    "mssql":      "tsql",
    "sqlserver":  "tsql",
    "oracle":     "oracle",
    "sqlite":     "sqlite",
    "spark":      "spark",
    "bigquery":   "bigquery",
    "generic":    None,
}

# ── Regex patterns (dialect-independent) ──────────────────────────────────────

# CREATE [OR REPLACE] [DEFINER=...] PROCEDURE/FUNCTION/TRIGGER/VIEW [IF NOT EXISTS] [schema.]name
_RE_CREATE = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?'
    r'(?:DEFINER\s*=\s*\S+\s+)?'
    r'(?:GLOBAL\s+|LOCAL\s+)?'
    r'(PROCEDURE|FUNCTION|TRIGGER|VIEW|PACKAGE(?:\s+BODY)?)'
    r'\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(?:(`[\w$]+`|"[\w$]+"|\[[\w$]+\]|[\w$]+)\s*\.\s*)?'
    r'(`[\w$]+`|"[\w$]+"|\[[\w$]+\]|[\w$]+)',
    re.IGNORECASE,
)

_RE_CALL = re.compile(
    r'\b(?:CALL|EXEC(?:UTE)?)\s+'
    r'(?:dbo\s*\.\s*|[\w$]+\s*\.\s*)?'
    r'(`[\w$]+`|[\w$]+)'
    r'\s*\(([^)]*)\)',
    re.IGNORECASE,
)

# Per-operation DML patterns to avoid false positives:
#   SELECT uses FROM <table> (not SELECT <col>)
#   INSERT requires INTO (avoids TRIGGER "INSERT ON <table>")
#   UPDATE requires SET after the name
#   DELETE requires FROM after the keyword
_ID = r'(`[\w$]+`|"[\w$]+"|\[[\w$]+\]|[\w$]+(?:\s*\.\s*(?:`[\w$]+`|[\w$]+))?)'
_RE_DML_FROM   = re.compile(r'\bFROM\s+'   + _ID + r'(?!\s*\()',          re.IGNORECASE)
_RE_DML_INSERT = re.compile(r'\bINSERT\s+INTO\s+' + _ID,                  re.IGNORECASE)
_RE_DML_UPDATE = re.compile(r'\bUPDATE\s+' + _ID + r'(?=\s+SET\b)',        re.IGNORECASE)
_RE_DML_DELETE = re.compile(r'\bDELETE\s+FROM\s+' + _ID,                  re.IGNORECASE)
_RE_DML_MERGE  = re.compile(r'\bMERGE\s+(?:INTO\s+)?' + _ID,              re.IGNORECASE)

_RE_DECLARE = re.compile(
    r'\bDECLARE\s+@?([\w$]+)\s+([\w$]+(?:\s*\([^)]*\))?)',
    re.IGNORECASE,
)

# T-SQL @variables, Oracle :variables
_RE_TSQL_VAR = re.compile(r'@([\w$]+)', re.IGNORECASE)
_RE_ORACLE_VAR = re.compile(r':(?!:)([\w$]+)', re.IGNORECASE)

# Strip identifier quoting: `name`, "name", [name]
_RE_UNQUOTE = re.compile(r'^[`"\[]|[`"\]]$')

# ── Dangerous SQL patterns (signature analysis) ────────────────────────────────
_SQL_SIGS: List[Tuple[str, str, str, re.Pattern]] = [
    ("CWE-89",  "SQL Injection",     "EXEC(@sql)",         re.compile(r'\bEXEC\s*\(\s*@\w+', re.I)),
    ("CWE-89",  "SQL Injection",     "EXECUTE(@sql)",      re.compile(r'\bEXECUTE\s*\(\s*@\w+', re.I)),
    ("CWE-89",  "SQL Injection",     "sp_executesql",      re.compile(r'\bsp_executesql\b', re.I)),
    ("CWE-89",  "SQL Injection",     "PREPARE..FROM",      re.compile(r'\bPREPARE\s+\w+\s+FROM\s+@', re.I)),
    ("CWE-89",  "SQL Injection",     "EXECUTE IMMEDIATE",  re.compile(r'\bEXECUTE\s+IMMEDIATE\b', re.I)),
    ("CWE-78",  "OS Command Inj.",   "xp_cmdshell",        re.compile(r'\bxp_cmdshell\b', re.I)),
    ("CWE-78",  "OS Command Inj.",   "sp_OACreate",        re.compile(r'\bsp_OACreate\b', re.I)),
    ("CWE-798", "Hardcoded Creds",   "hardcoded password",  re.compile(r"PASSWORD\s*=\s*['\"][^'\"]{3,}['\"]", re.I)),
    ("CWE-269", "Privilege Mgmt",    "GRANT ALL",          re.compile(r'\bGRANT\s+ALL\b', re.I)),
    ("CWE-400", "Resource Destruct", "TRUNCATE TABLE",     re.compile(r'\bTRUNCATE\s+TABLE\b', re.I)),
    ("CWE-284", "Improper Access",   "WITH NOCHECK",       re.compile(r'\bWITH\s+NOCHECK\b', re.I)),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _unquote(s: str) -> str:
    return _RE_UNQUOTE.sub("", s.strip()) if s else s


def _line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def _dedup(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: Set[tuple] = set()
    out = []
    for r in rows:
        k = tuple(r.values())
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ── Object boundary splitter ───────────────────────────────────────────────────

def _split_objects(text: str) -> List[Tuple[re.Match, str, int]]:
    """Return list of (create_match, body_text, body_start_pos) for each object."""
    matches = list(_RE_CREATE.finditer(text))
    result = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end]
        result.append((m, body, m.end()))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
class SqlAnalyzer:
    """Analyzes SQL source files and returns the 9 standard datasets.

    Public interface mirrors CodeQLAnalyzer.run_batch_queries() so that
    project_runner.py can use it without language-specific branching.
    """

    def __init__(
        self,
        source_path: str,
        dialect: str = "mysql",
        path_pattern: str = "",
        work_dir: Optional[str] = None,
        ram_mb: int = 4096,
    ):
        self.source_path = Path(source_path).resolve()
        self.dialect: Optional[str] = DIALECT_ALIASES.get(
            dialect.lower(), dialect.lower() if dialect else None
        )
        # Strip CodeQL-style % wildcards — SqlAnalyzer uses substring matching
        self.path_pattern = path_pattern.strip().replace("%", "")
        self.ram_mb = ram_mb

        if not self.source_path.exists():
            raise FileNotFoundError(f"SQL source path not found: {self.source_path}")

        if not _SQLGLOT_OK:
            print(
                "[sql_analyzer] sqlglot not installed — using regex fallback.\n"
                "               Install with: pip install sqlglot",
                file=sys.stderr,
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_batch_queries(
        self,
        query_names: Optional[List[str]] = None,
        log: Optional[Callable] = None,
    ) -> Dict[str, List[Dict[str, str]]]:
        """Analyse all .sql files and return the 9 standard datasets."""
        results: Dict[str, List[Dict[str, str]]] = {k: [] for k in DATASETS}

        for sql_file in self._collect_files():
            try:
                self._process_file(sql_file, results)
            except Exception as exc:
                print(f"[sql_analyzer] ERROR {sql_file.name}: {exc}", file=sys.stderr)

        # Dedup relational datasets (same pair may appear from several files)
        for key in ("control", "data", "flow", "arg_flow", "file_flow", "signature"):
            results[key] = _dedup(results[key])

        for name, rows in results.items():
            if query_names is None or name in query_names:
                if log:
                    log(name, len(rows))

        if query_names is not None:
            return {k: v for k, v in results.items() if k in query_names}
        return results

    # ── File collection ────────────────────────────────────────────────────────

    def _matches(self, path: str) -> bool:
        if not self.path_pattern:
            return True
        return self.path_pattern in path.replace("\\", "/")

    def _collect_files(self) -> List[Path]:
        if self.source_path.is_file():
            return [self.source_path] if self._matches(str(self.source_path)) else []
        return sorted(
            f for f in self.source_path.rglob("*.sql")
            if self._matches(str(f))
        )

    # ── File processing ────────────────────────────────────────────────────────

    def _process_file(self, path: Path, results: Dict[str, List[Dict[str, str]]]):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        abs_path = str(path)
        results["files"].append({"abs_path": abs_path, "base_name": path.name})

        if _SQLGLOT_OK:
            objects = self._extract_sqlglot(text, abs_path)
        else:
            objects = self._extract_regex(text, abs_path)

        for obj in objects:
            results["functional"].append(obj["meta"])
            results["info"].extend(obj["info"])
            results["control"].extend(obj["control"])
            results["data"].extend(obj["data"])
            results["flow"].extend(obj["flow"])
            results["arg_flow"].extend(obj["arg_flow"])
            results["file_flow"].extend(obj["file_flow"])
            results["signature"].extend(obj["signature"])

    # ══════════════════════════════════════════════════════════════════════════
    # sqlglot-based extraction
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_sqlglot(self, text: str, abs_path: str) -> List[Dict[str, Any]]:
        try:
            statements = sqlglot.parse(
                text, dialect=self.dialect, error_level=ErrorLevel.WARN
            )
        except Exception:
            return self._extract_regex(text, abs_path)

        objects = []
        # Build a line-offset map for statements: use regex to find positions
        # because sqlglot doesn't always expose reliable per-statement line numbers.
        create_positions = {
            m.group(3) and _unquote(m.group(3)): _line_of(text, m.start())
            for m in _RE_CREATE.finditer(text)
        }

        for stmt in statements:
            if stmt is None or not isinstance(stmt, exp.Create):
                continue
            obj = self._process_create(stmt, abs_path, text, create_positions)
            if obj:
                objects.append(obj)

        # Fall back to regex for any objects sqlglot missed
        found_names = {o["meta"]["name"] for o in objects}
        for m, body, _ in _split_objects(text):
            name = _unquote(m.group(3))
            if name and name not in found_names:
                obj = self._object_from_regex_match(m, body, abs_path, text)
                if obj:
                    objects.append(obj)

        return objects

    def _obj_name_parts(self, stmt: "exp.Create") -> Tuple[str, str]:
        """Return (schema, name) from a CREATE statement."""
        this = stmt.this
        if this is None:
            return "", ""

        def _parts_of(node) -> List[str]:
            if hasattr(node, "parts"):
                return [p.name for p in node.parts if p.name]
            if hasattr(node, "name") and node.name:
                return [node.name]
            return []

        if isinstance(this, exp.Schema):
            parts = _parts_of(this.this)
        else:
            parts = _parts_of(this)

        if len(parts) >= 2:
            return parts[-2], parts[-1]
        if parts:
            return "", parts[-1]
        return "", ""

    def _process_create(
        self,
        stmt: "exp.Create",
        abs_path: str,
        text: str,
        line_map: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        kind_str = (stmt.args.get("kind") or "").upper()
        if kind_str not in ("PROCEDURE", "FUNCTION", "TRIGGER", "VIEW"):
            return None

        schema_name, obj_name = self._obj_name_parts(stmt)
        if not obj_name:
            return None

        qualified_name = f"{schema_name}.{obj_name}" if schema_name else obj_name
        parent_type = schema_name if schema_name else "(global)"
        line = str(line_map.get(obj_name, 1))

        kind_label = {
            "PROCEDURE": "procedure",
            "FUNCTION":  "function",
            "TRIGGER":   "trigger",
            "VIEW":      "view",
        }[kind_str]

        meta = {
            "qualified_name": qualified_name,
            "name": obj_name,
            "parent_type": parent_type,
            "file": abs_path,
            "line": line,
            "kind": kind_label,
        }

        params = self._params_sqlglot(stmt, qualified_name, abs_path, line)
        info, control, data, flow, arg_flow, file_flow, sigs = (
            self._body_sqlglot(stmt, qualified_name, abs_path, kind_str, text)
        )

        return {
            "meta": meta,
            "info": params + info,
            "control": control,
            "data": data,
            "flow": flow,
            "arg_flow": arg_flow,
            "file_flow": file_flow,
            "signature": sigs,
        }

    def _params_sqlglot(
        self,
        stmt: "exp.Create",
        qname: str,
        abs_path: str,
        obj_line: str,
    ) -> List[Dict[str, str]]:
        params = []
        this = stmt.this
        if not isinstance(this, exp.Schema):
            return params
        for col in this.expressions:
            p_name = col.name if hasattr(col, "name") else ""
            if not p_name or p_name in ("self", "this"):
                continue
            # Try to find the data type
            type_name = ""
            for attr in ("kind", "dtype"):
                v = col.args.get(attr) if hasattr(col, "args") else None
                if v is not None:
                    type_name = str(v)
                    break
            params.append({
                "qualified_name": f"{qname}.{p_name}",
                "name": p_name,
                "type_name": type_name,
                "file": abs_path,
                "line": obj_line,
                "kind": "parameter",
            })
        return params

    def _node_line(self, node: "exp.Expression") -> int:
        """Best-effort line number from sqlglot node metadata."""
        if hasattr(node, "meta") and node.meta:
            return node.meta.get("line", 0)
        return 0

    def _subtree_end_line(self, node: "exp.Expression") -> int:
        best = self._node_line(node)
        for sub, _, _ in node.walk():
            l = self._node_line(sub)
            if l > best:
                best = l
        return best

    def _body_sqlglot(
        self,
        stmt: "exp.Create",
        qname: str,
        abs_path: str,
        kind_str: str,
        full_text: str,
    ) -> Tuple[list, list, list, list, list, list, list]:
        info: List[Dict] = []
        control: List[Dict] = []
        data: List[Dict] = []
        flow: List[Dict] = []
        arg_flow: List[Dict] = []
        file_flow: List[Dict] = []
        sigs: List[Dict] = []

        base = Path(abs_path).name
        dlct = self.dialect

        def add_flow(ls: int, le: int, stype: str, label: str, else_l: int, ic: bool):
            flow.append({
                "func_name":  qname,
                "func_file":  abs_path,
                "stmt_id":    f"{base}:{ls}",
                "line_start": str(ls),
                "line_end":   str(le or ls),
                "stmt_type":  stype,
                "stmt_label": label[:200],
                "else_line":  str(else_l),
                "in_catch":   "1" if ic else "0",
            })

        def safe_sql(node) -> str:
            try:
                return node.sql(dialect=dlct)
            except Exception:
                return str(node)

        # For VIEW: just collect table reads and return early
        if kind_str == "VIEW":
            obj_name = qname.rsplit(".", 1)[-1]
            for sub, _, _ in stmt.walk():
                if isinstance(sub, exp.Table) and sub.name and sub.name != obj_name:
                    file_flow.append({
                        "function_name": qname,
                        "func_file": abs_path,
                        "file_name": sub.name,
                        "access_type": "read",
                        "access_line": str(self._node_line(sub)),
                    })
            return info, control, data, flow, arg_flow, file_flow, sigs

        # Walk all AST nodes
        for sub, _, _ in stmt.walk():

            # ── DECLARE ───────────────────────────────────────────────────
            if isinstance(sub, exp.Declare):
                for item in sub.expressions:
                    v_name = item.name if hasattr(item, "name") else ""
                    if not v_name or v_name.startswith("<"):
                        continue
                    v_type = ""
                    if hasattr(item, "args"):
                        for k in ("kind", "dtype"):
                            v = item.args.get(k)
                            if v:
                                v_type = str(v); break
                    info.append({
                        "qualified_name": f"{qname}.{v_name}",
                        "name": v_name,
                        "type_name": v_type,
                        "file": abs_path,
                        "line": str(self._node_line(sub)),
                        "kind": "local variable",
                    })

            # ── IF ────────────────────────────────────────────────────────
            elif isinstance(sub, exp.If):
                ls = self._node_line(sub)
                le = self._subtree_end_line(sub)
                cond = safe_sql(sub.this) if sub.this else ""
                false_br = sub.args.get("false")
                else_l = self._node_line(false_br) if false_br else 0
                add_flow(ls, le, "if", f"IF {cond}", else_l, False)

            # ── WHILE ─────────────────────────────────────────────────────
            elif isinstance(sub, exp.While):
                ls = self._node_line(sub)
                le = self._subtree_end_line(sub)
                cond = safe_sql(sub.this) if sub.this else ""
                add_flow(ls, le, "while", f"WHILE {cond}", 0, False)

            # ── CASE ──────────────────────────────────────────────────────
            elif isinstance(sub, exp.Case):
                ls = self._node_line(sub)
                le = self._subtree_end_line(sub)
                add_flow(ls, le, "if", f"CASE {safe_sql(sub)[:80]}", 0, False)

            # ── RETURN ────────────────────────────────────────────────────
            elif isinstance(sub, exp.Return):
                ls = self._node_line(sub)
                label = safe_sql(sub)[:200]
                add_flow(ls, ls, "return", label, 0, False)

            # ── SELECT → file_flow (table reads) ──────────────────────────
            elif isinstance(sub, exp.Select):
                ls = self._node_line(sub)
                for tbl in sub.find_all(exp.Table):
                    if tbl.name:
                        file_flow.append({
                            "function_name": qname,
                            "func_file": abs_path,
                            "file_name": tbl.name,
                            "access_type": "read",
                            "access_line": str(ls or self._node_line(tbl)),
                        })

            # ── INSERT ────────────────────────────────────────────────────
            elif isinstance(sub, exp.Insert):
                ls = self._node_line(sub)
                tbl = sub.find(exp.Table)
                if tbl and tbl.name:
                    file_flow.append({
                        "function_name": qname, "func_file": abs_path,
                        "file_name": tbl.name, "access_type": "write",
                        "access_line": str(ls),
                    })

            # ── UPDATE ────────────────────────────────────────────────────
            elif isinstance(sub, exp.Update):
                ls = self._node_line(sub)
                tbl = sub.find(exp.Table)
                if tbl and tbl.name:
                    file_flow.append({
                        "function_name": qname, "func_file": abs_path,
                        "file_name": tbl.name, "access_type": "write",
                        "access_line": str(ls),
                    })

            # ── DELETE ────────────────────────────────────────────────────
            elif isinstance(sub, exp.Delete):
                ls = self._node_line(sub)
                tbl = sub.find(exp.Table)
                if tbl and tbl.name:
                    file_flow.append({
                        "function_name": qname, "func_file": abs_path,
                        "file_name": tbl.name, "access_type": "delete",
                        "access_line": str(ls),
                    })

            # ── CALL / Anonymous function call ────────────────────────────
            elif isinstance(sub, (exp.Anonymous, exp.Call)):
                callee = getattr(sub, "name", "") or ""
                if callee and callee.upper() not in (
                    "IF", "WHILE", "CASE", "COALESCE", "ISNULL", "NVL",
                    "CONVERT", "CAST", "NULLIF",
                ):
                    ls = self._node_line(sub)
                    control.append({
                        "caller_name": qname, "callee_name": callee,
                        "caller_file": abs_path, "callee_file": "",
                        "call_line": str(ls),
                    })
                    for i, arg in enumerate(sub.expressions, 1):
                        caller_var = arg.name if hasattr(arg, "name") and arg.name else safe_sql(arg)[:80]
                        arg_flow.append({
                            "caller_name": qname, "callee_name": callee,
                            "caller_var": caller_var, "param_var": str(i),
                            "caller_file": abs_path, "call_line": str(ls),
                        })

            # ── Variable access (T-SQL @var as Var or Parameter) ──────────
            elif isinstance(sub, (exp.Var, exp.Parameter)):
                v_name = sub.name if hasattr(sub, "name") else ""
                if v_name and not v_name.startswith("<"):
                    ls = self._node_line(sub)
                    data.append({
                        "function_name": qname, "variable_name": v_name,
                        "func_file": abs_path, "access_line": str(ls),
                        "access_type": "read",
                    })

        # Signature scan on the rendered SQL text of this statement
        try:
            stmt_text = stmt.sql(dialect=dlct)
        except Exception:
            stmt_text = ""
        if not stmt_text:
            # Locate body text in original file using regex
            m = _RE_CREATE.search(full_text)
            stmt_text = full_text[m.start():] if m else full_text

        for cwe, cat, sig_name, regex in _SQL_SIGS:
            m = regex.search(stmt_text)
            if m:
                sigs.append({
                    "cwe": cwe, "category": cat, "signature": sig_name,
                    "function_name": qname, "func_file": abs_path,
                    "line": "0",
                })

        return info, control, data, flow, arg_flow, file_flow, sigs

    # ══════════════════════════════════════════════════════════════════════════
    # Regex-based extraction (fallback / supplement)
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_regex(self, text: str, abs_path: str) -> List[Dict[str, Any]]:
        objects = []
        for m, body, _ in _split_objects(text):
            obj = self._object_from_regex_match(m, body, abs_path, text)
            if obj:
                objects.append(obj)
        return objects

    def _object_from_regex_match(
        self,
        m: re.Match,
        body: str,
        abs_path: str,
        full_text: str,
    ) -> Optional[Dict[str, Any]]:
        kind_str = m.group(1).upper()
        schema_raw = m.group(2) or ""
        name_raw = m.group(3) or ""

        schema_name = _unquote(schema_raw)
        obj_name = _unquote(name_raw)
        if not obj_name:
            return None

        qualified_name = f"{schema_name}.{obj_name}" if schema_name else obj_name
        parent_type = schema_name if schema_name else "(global)"
        line_no = _line_of(full_text, m.start())

        kind_map = {
            "PROCEDURE":    "procedure",
            "FUNCTION":     "function",
            "TRIGGER":      "trigger",
            "VIEW":         "view",
            "PACKAGE":      "package",
            "PACKAGE BODY": "package body",
        }
        kind = kind_map.get(kind_str, kind_str.lower())

        meta = {
            "qualified_name": qualified_name,
            "name": obj_name,
            "parent_type": parent_type,
            "file": abs_path,
            "line": str(line_no),
            "kind": kind,
        }

        info, control, data, flow, arg_flow, file_flow, sigs = (
            self._body_regex(body, qualified_name, abs_path, line_no)
        )

        return {
            "meta": meta,
            "info": info,
            "control": control,
            "data": data,
            "flow": flow,
            "arg_flow": arg_flow,
            "file_flow": file_flow,
            "signature": sigs,
        }

    def _body_regex(
        self,
        body: str,
        qname: str,
        abs_path: str,
        start_line: int,
    ) -> Tuple[list, list, list, list, list, list, list]:
        info: List[Dict] = []
        control: List[Dict] = []
        data: List[Dict] = []
        flow: List[Dict] = []
        arg_flow: List[Dict] = []
        file_flow: List[Dict] = []
        sigs: List[Dict] = []

        base = Path(abs_path).name
        body_lines = body.splitlines()

        def abs_ln(pos: int) -> int:
            return start_line + body[:pos].count("\n")

        # ── DECLARE (local variables) ──────────────────────────────────────
        for m in _RE_DECLARE.finditer(body):
            v_name, v_type = m.group(1), m.group(2)
            info.append({
                "qualified_name": f"{qname}.{v_name}",
                "name": v_name,
                "type_name": v_type,
                "file": abs_path,
                "line": str(abs_ln(m.start())),
                "kind": "local variable",
            })

        # ── CALL / EXEC ────────────────────────────────────────────────────
        for m in _RE_CALL.finditer(body):
            callee = _unquote(m.group(1))
            args_str = m.group(2).strip()
            ln = str(abs_ln(m.start()))
            control.append({
                "caller_name": qname, "callee_name": callee,
                "caller_file": abs_path, "callee_file": "",
                "call_line": ln,
            })
            for i, arg in enumerate(
                [a.strip() for a in args_str.split(",") if a.strip()], 1
            ):
                caller_var = arg.lstrip("@:").strip("'\"")
                arg_flow.append({
                    "caller_name": qname, "callee_name": callee,
                    "caller_var": caller_var, "param_var": str(i),
                    "caller_file": abs_path, "call_line": ln,
                })

        # ── Table DML (file_flow) ──────────────────────────────────────────
        # Exclude reserved words that appear as false-positive table names
        _SKIP_NAMES = frozenset((
            "DUAL", "INFORMATION_SCHEMA", "SYS", "SYSIBM",
            "SELECT", "FROM", "WHERE", "SET", "ON", "INTO",
        ))

        def _add_table(m: re.Match, access_type: str):
            tname = _unquote(m.group(1)).split(".")[-1]  # strip schema prefix
            if tname and tname.upper() not in _SKIP_NAMES:
                file_flow.append({
                    "function_name": qname, "func_file": abs_path,
                    "file_name": tname, "access_type": access_type,
                    "access_line": str(abs_ln(m.start())),
                })

        for m in _RE_DML_FROM.finditer(body):
            _add_table(m, "read")
        for m in _RE_DML_INSERT.finditer(body):
            _add_table(m, "write")
        for m in _RE_DML_UPDATE.finditer(body):
            _add_table(m, "write")
        for m in _RE_DML_DELETE.finditer(body):
            _add_table(m, "delete")
        for m in _RE_DML_MERGE.finditer(body):
            _add_table(m, "write")

        # ── Variable accesses (@var / :var) ────────────────────────────────
        for regex in (_RE_TSQL_VAR, _RE_ORACLE_VAR):
            for m in regex.finditer(body):
                v = m.group(1)
                if v:
                    data.append({
                        "function_name": qname, "variable_name": v,
                        "func_file": abs_path,
                        "access_line": str(abs_ln(m.start())),
                        "access_type": "read",
                    })

        # ── Control flow (line-by-line) ────────────────────────────────────
        _IF_RE    = re.compile(r'^\s*IF\b', re.I)
        _ELIF_RE  = re.compile(r'^\s*(?:ELSE\s+IF|ELSIF|ELSEIF)\b', re.I)
        _ELSE_RE  = re.compile(r'^\s*ELSE\b', re.I)
        _WHILE_RE = re.compile(r'^\s*WHILE\b', re.I)
        _LOOP_RE  = re.compile(r'^\s*(?:LOOP|REPEAT)\b', re.I)
        _CASE_RE  = re.compile(r'^\s*CASE\b', re.I)
        _RET_RE   = re.compile(r'^\s*RETURN\b', re.I)
        _RAISE_RE = re.compile(r'^\s*(?:RAISE|SIGNAL|THROW)\b', re.I)
        _FOR_RE   = re.compile(r'^\s*FOR\b', re.I)
        _CURSOR_RE = re.compile(r'^\s*OPEN\b', re.I)

        in_catch = False
        for i, line_text in enumerate(body_lines):
            ln = start_line + i
            stripped = line_text.strip()
            if not stripped:
                continue

            # Track CATCH/EXCEPTION for in_catch flag
            upper = stripped.upper()
            if "CATCH" in upper or "EXCEPTION" in upper:
                in_catch = True
            if re.match(r'^\s*END\b', stripped, re.I) and in_catch:
                in_catch = False

            ic = "1" if in_catch else "0"
            label = stripped[:200]

            if _IF_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "if",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _ELIF_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "if",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _WHILE_RE.match(stripped) or _LOOP_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "while",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _FOR_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "for",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _CASE_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "if",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _RET_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "return",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })
            elif _RAISE_RE.match(stripped):
                flow.append({
                    "func_name": qname, "func_file": abs_path,
                    "stmt_id": f"{base}:{ln}", "line_start": str(ln),
                    "line_end": str(ln), "stmt_type": "throw",
                    "stmt_label": label, "else_line": "0", "in_catch": ic,
                })

        # ── Signatures ─────────────────────────────────────────────────────
        for cwe, cat, sig_name, regex in _SQL_SIGS:
            m = regex.search(body)
            if m:
                sigs.append({
                    "cwe": cwe, "category": cat, "signature": sig_name,
                    "function_name": qname, "func_file": abs_path,
                    "line": str(abs_ln(m.start())),
                })

        return info, control, data, flow, arg_flow, file_flow, sigs
