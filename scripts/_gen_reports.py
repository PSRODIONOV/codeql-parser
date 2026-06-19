"""Regenerate static reports from the current DB state."""
import sys
sys.path.insert(0, ".")

if __name__ == "__main__":
    from core.project_db import ProjectDB
    from core.project_runner import generate_static_reports

    db = ProjectDB.open("workspace/test-php")
    import time
    t = time.perf_counter()
    generate_static_reports(db)
    print(f"[OK] Reports done in {time.perf_counter()-t:.1f}s")
