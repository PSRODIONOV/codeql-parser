"""
Standalone flowchart regeneration script.
Reads cached CSVs from a workspace work/ directory and regenerates DRAKON SVGs
without re-running CodeQL queries.

Usage:
  python3 regen_drakon.py --work <workspace/project/work> --out <output_dir>
                          [--db <codeql-db-path>]
"""
import argparse
import csv
from pathlib import Path


def read_csv(path: str):
    data = []
    p = Path(path)
    if not p.exists():
        return data
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        for row in reader:
            data.append(dict(zip(headers, row)))
    return data


def main():
    ap = argparse.ArgumentParser(description="Regenerate DRAKON SVGs from cached CSVs")
    ap.add_argument("--work", required=True,
                    help="Каталог work/ с CSV-кешем (напр. workspace/myproject/work)")
    ap.add_argument("--out", required=True,
                    help="Каталог вывода SVG-схем")
    ap.add_argument("--db", default=None,
                    help="Путь к CodeQL БД (нужен src.zip для подписей; необязательно)")
    args = ap.parse_args()

    work = Path(args.work)
    db_path = Path(args.db) if args.db else None
    output_dir = args.out

    print(f"Output: {output_dir}")
    print("Reading CSVs...", flush=True)

    func_data  = read_csv(work / "functional" / "functional.csv")
    flow_data  = read_csv(work / "flow"        / "flow.csv")
    info_data  = read_csv(work / "info"        / "info.csv")
    ctrl_data  = read_csv(work / "control"     / "control.csv")

    print(f"  func={len(func_data)} flow={len(flow_data)} info={len(info_data)} ctrl={len(ctrl_data)}", flush=True)

    # db_path: DrakonGenerator uses it to read src.zip for source labels
    # If not provided or has no src.zip, labels fall back to stmt_label
    effective_db = None
    if db_path is not None:
        src_zip = db_path / "src.zip"
        effective_db = str(db_path) if src_zip.exists() else None
        if effective_db:
            print(f"src.zip found at {src_zip}", flush=True)
        else:
            print("No src.zip — using stmt_label fallback", flush=True)
    else:
        print("No --db specified — using stmt_label fallback", flush=True)

    from viz.drakon_generator import DrakonGenerator

    gen = DrakonGenerator(output_dir, db_path=effective_db, clear_output=True)

    print("Generating flowcharts...", flush=True)
    generated, *_ = gen.generate_all(
        func_data, flow_data, info_data, ctrl_data,
        data_data=None, file_flow_data=None,
        build_flowcharts=True,
        need_routes_in_memory=False,
    )
    print(f"Done: {len(generated)} SVGs in {output_dir}", flush=True)


if __name__ == "__main__":
    main()
