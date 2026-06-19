"""One-shot PHP analysis runner — guards against multiprocessing fork."""
import sys
sys.path.insert(0, ".")

if __name__ == "__main__":
    from core.project_db import ProjectDB
    from core.project_runner import run_static_analysis

    db = ProjectDB.open("workspace/test-php")
    meta = db.get_project()

    joern_path = "third-party/joern-cli/joern.bat"

    def log(msg):
        print(msg, flush=True)

    stats = run_static_analysis(
        project=db,
        joern_path=joern_path,
        ram_mb=4096,
        log=log,
    )
    print("Stats:", stats)
