"""joern_analyzer.py — Joern wrapper for PHP source code analysis.

Mirrors CodeQLAnalyzer's run_batch_queries() interface so project_runner.py
can use it transparently for PHP projects.

Joern is invoked with a Scala script (queries/php/all_queries.sc) that
imports the PHP source, runs all queries, and writes JSONL to a temp file.
Parameters are passed base64-encoded to avoid comma/space issues in
Joern's --params parsing.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from paths import third_party, PROJECT_ROOT


# Maps dataset name → expected column names (same schema as CodeQL queries).
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


def _b64enc(s: str) -> str:
    """URL-safe base64 encode without padding — safe for Joern --params."""
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def _to_wsl_path(p: str) -> str:
    """Convert Windows path (F:\\foo\\bar) to WSL mount path (/mnt/f/foo/bar)."""
    s = str(p).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = f"/mnt/{s[0].lower()}{s[2:]}"
    return s


def _wsl_mode(joern_path: str) -> bool:
    """True when running on Windows with a non-.bat joern (needs WSL)."""
    return os.name == "nt" and not str(joern_path).lower().endswith(".bat")


def _find_wsl() -> str:
    """Return full path to wsl.exe (not just 'wsl' which may not be on PATH)."""
    found = shutil.which("wsl")
    if found:
        return found
    default = r"C:\Windows\System32\wsl.exe"
    if os.path.exists(default):
        return default
    return "wsl"


def _find_java_home(joern_path: str) -> str:
    """Find a bundled JDK directory in third-party/."""
    candidates = (
        ["jdk25-win", "jdk11-win"] if os.name == "nt"
        else ["jdk25-linux", "jdk11-linux", "jdk11"]
    )
    for name in candidates:
        jdk = third_party(name)
        java_bin = jdk / "bin" / ("java.exe" if os.name == "nt" else "java")
        if java_bin.exists():
            return str(jdk)
    return ""


def _resolve_php_calls(results: Dict[str, List[Dict[str, str]]]) -> Dict[str, List[Dict[str, str]]]:
    """Resolve <unresolvedNamespace>.X and parent.X call names in PHP CPG output.

    Joern's PHP frontend has no type inference, so method calls via object variables
    are emitted as <unresolvedNamespace>.shortName.  We fix this post-hoc:

      1. Build a short-name index from the `functional` dataset.
      2. For each unresolved callee, if the short name is unique across all classes,
         resolve it confidently.  If ambiguous, try matching the caller's own class
         first (covers $this-> calls).
      3. For parent.X calls, look up the caller class in the `class_info` hierarchy
         and substitute the actual parent class name.

    `class_info` is an internal dataset emitted by all_queries.sc but not stored in
    the project DB — it is consumed and removed here.
    """
    UNRESOLVED = "<unresolvedNamespace>."

    # ── Build class hierarchy from class_info dataset ─────────────────────────
    hierarchy: Dict[str, str] = {}   # child_class → parent_class
    for row in results.pop("class_info", []):
        cls = row.get("class_name", "")
        parent = row.get("parent_name", "")
        if cls and parent:
            hierarchy[cls] = parent

    # ── Build method index from functional dataset ────────────────────────────
    method_index: Dict[str, List[str]] = {}   # short_name → [qualified_name, ...]
    all_qnames: set = {row.get("qualified_name", "") for row in results.get("functional", [])}
    for row in results.get("functional", []):
        qn   = row.get("qualified_name", "")
        name = row.get("name", "")
        if name and qn:
            method_index.setdefault(name, []).append(qn)

    # ── Resolution logic ──────────────────────────────────────────────────────
    def _resolve(caller_name: str, callee_name: str) -> str:
        # parent.X  →  ParentClass.X  (using class hierarchy)
        if callee_name.startswith("parent."):
            short = callee_name[len("parent."):]
            caller_class = caller_name.split(".")[0] if "." in caller_name else ""
            parent_class = hierarchy.get(caller_class, "")
            if parent_class:
                candidate = f"{parent_class}.{short}"
                if candidate in all_qnames:
                    return candidate
            return callee_name

        # <unresolvedNamespace>.X  →  ClassName.X
        if not callee_name.startswith(UNRESOLVED):
            return callee_name
        short = callee_name[len(UNRESOLVED):]
        candidates = method_index.get(short, [])
        if not candidates:
            return callee_name                          # stdlib/external — keep
        if len(candidates) == 1:
            return candidates[0]                        # unique name — confident
        # Ambiguous: try matching caller's own class ($this-> calls)
        if "." in caller_name:
            caller_class = caller_name.split(".")[0]
            for c in candidates:
                if c.startswith(caller_class + "."):
                    return c
        return callee_name                              # truly ambiguous

    # ── Apply resolution to control and arg_flow ──────────────────────────────
    for row in results.get("control", []):
        row["callee_name"] = _resolve(row.get("caller_name", ""), row.get("callee_name", ""))

    for row in results.get("arg_flow", []):
        row["callee_name"] = _resolve(row.get("caller_name", ""), row.get("callee_name", ""))

    return results


def _find_joern(joern_path: str) -> str:
    """Locate Joern: given path, PATH lookup, or local project install."""
    if os.path.exists(joern_path):
        return str(Path(joern_path).resolve())
    if os.path.isabs(joern_path):
        return joern_path
    find_cmd = "where" if os.name == "nt" else "which"
    try:
        result = subprocess.run([find_cmd, joern_path], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except FileNotFoundError:
        pass
    candidates = [
        third_party("joern-cli", "joern.bat"),
        third_party("joern-cli", "joern"),
        third_party("joern-cli", "bin", "joern.bat"),
        third_party("joern-cli", "bin", "joern"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return joern_path  # fallback: assume on PATH


class JoernAnalyzer:
    """Runs Joern on a PHP source directory and returns analysis datasets.

    The public interface is identical to CodeQLAnalyzer so project_runner.py
    can use it without language-specific branching beyond analyzer construction.
    """

    SCRIPT = PROJECT_ROOT / "queries" / "php" / "all_queries.sc"

    def __init__(
        self,
        source_path: str,
        joern_path: str = "joern",
        path_pattern: str = "",
        work_dir: Optional[str] = None,
        ram_mb: int = 4096,
    ):
        self.source_path = str(Path(source_path).resolve())
        self.joern = _find_joern(joern_path)
        # CodeQL uses SQL-LIKE % wildcards; strip them for substring matching.
        self.path_pattern = path_pattern.strip().replace("%", "")
        self.ram_mb = ram_mb

        if work_dir:
            self.work_dir = Path(work_dir).resolve()
        else:
            import tempfile
            self.work_dir = Path(tempfile.gettempdir()) / "joern_analyzer"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        if not self.SCRIPT.exists():
            raise FileNotFoundError(
                f"Joern PHP analysis script not found: {self.SCRIPT}\n"
                "Expected at queries/php/all_queries.sc"
            )

    # ──────────────────────────────────────────────────────────────────────────
    def run_batch_queries(
        self,
        query_names: Optional[List[str]] = None,
        log: Optional[Callable] = None,
    ) -> Dict[str, List[Dict[str, str]]]:
        """Run PHP analysis and return results in the same format as CodeQL.

        query_names: if given, only these dataset keys are returned.
        log(name, count): called after each dataset is parsed (same as CodeQL).
        """
        output_file = self.work_dir / f"joern_out_{os.getpid()}.jsonl"

        # --workspace is intentionally omitted: Joern 4.x injects importCpg(path) for
        # the workspace argument without quoting, which breaks Windows drive-letter paths.
        # Our script creates a fresh CPG via importCode.php(), so no pre-load is needed.
        # Windows bat scripts split arguments on '=', breaking --param key=value.
        # Solution: inject values directly into a temp copy of the script.
        wsl = _wsl_mode(self.joern)
        if wsl:
            inp_b64 = _b64enc(_to_wsl_path(self.source_path))
            out_b64 = _b64enc(_to_wsl_path(str(output_file)))
        else:
            inp_b64 = _b64enc(self.source_path)
            out_b64 = _b64enc(str(output_file))
        pat_b64 = _b64enc(self.path_pattern)

        injected = (f'val _inp = "{inp_b64}"\n'
                    f'val _out = "{out_b64}"\n'
                    f'val _pat = "{pat_b64}"')
        script_src = self.SCRIPT.read_text(encoding="utf-8")
        script_src = script_src.replace("// __PARAMS__", injected, 1)
        temp_script = self.work_dir / f"joern_script_{os.getpid()}.sc"
        temp_script.write_text(script_src, encoding="utf-8")

        if wsl:
            cmd = [
                _find_wsl(),
                _to_wsl_path(self.joern),
                "--script", _to_wsl_path(str(temp_script)),
            ]
        else:
            cmd = [self.joern, "--script", str(temp_script)]
            if os.name == "nt" and str(self.joern).lower().endswith(".bat"):
                cmd = ["cmd", "/c"] + cmd

        env = {
            **os.environ,
            "JAVA_OPTS": f"-Xmx{self.ram_mb}m",
            "_JAVA_OPTIONS": f"-Xmx{self.ram_mb}m",
        }
        if not wsl:
            java_home = _find_java_home(self.joern)
            if java_home:
                env["JAVA_HOME"] = java_home
            # php2cpg requires `php` on PATH; add bundled php-8.3 if present
            php_dir = third_party("php-8.3")
            php_exe = php_dir / "php.exe"
            if php_exe.exists() and str(php_dir) not in env.get("PATH", ""):
                env["PATH"] = str(php_dir) + os.pathsep + env.get("PATH", "")

        # Run Joern from a temp dir so it doesn't pick up our project workspace
        import tempfile as _tmpfile
        joern_cwd = _tmpfile.mkdtemp(prefix="joern_wd_")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=joern_cwd,
        )

        if proc.returncode != 0:
            stderr_tail = proc.stderr[-2000:] if proc.stderr else ""
            stdout_tail = proc.stdout[-2000:] if proc.stdout else ""
            raise RuntimeError(
                f"Joern analysis failed (exit code {proc.returncode}):\n"
                f"--- stderr ---\n{stderr_tail}\n"
                f"--- stdout ---\n{stdout_tail}"
            )

        if not output_file.exists():
            stdout_tail = proc.stdout[-500:] if proc.stdout else ""
            raise RuntimeError(
                f"Joern output file not created: {output_file}\n"
                f"Joern stdout: {stdout_tail}"
            )

        # Parse JSONL output: one JSON object per line, each with "_ds" field
        results: Dict[str, List[Dict[str, str]]] = {k: [] for k in DATASETS}
        try:
            for raw_line in output_file.read_text("utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line[0] != "{":
                    continue
                try:
                    obj = json.loads(line)
                    ds = obj.pop("_ds", None)
                    # Always collect class_info (used for call resolution, removed later)
                    if ds and (ds == "class_info" or query_names is None or ds in query_names):
                        results.setdefault(ds, []).append(obj)
                except json.JSONDecodeError:
                    continue
        finally:
            output_file.unlink(missing_ok=True)
            temp_script.unlink(missing_ok=True)

        # Resolve <unresolvedNamespace>.X and parent.X call names (PHP post-processing).
        # Also removes the internal class_info dataset from results.
        results = _resolve_php_calls(results)

        # Fire per-dataset log callback (mirrors CodeQL batch behaviour)
        for name, rows in results.items():
            if query_names is None or name in query_names:
                if log:
                    log(name, len(rows))

        if query_names is not None:
            return {k: v for k, v in results.items() if k in query_names}
        return results
