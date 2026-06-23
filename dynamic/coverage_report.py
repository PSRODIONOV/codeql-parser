#!/usr/bin/env python3
"""
Отчёт о динамическом покрытии по трассам.

Строит три отчёта из трасс + статических Перечень_ФО / Перечень_ветвей:
  1. Покрытие_ФО.csv       — перечень ФО: покрыт / нет.
  2. Покрытие_ветвей.csv   — перечень ветвей (как в статике) + колонка «Покрыта».
  3. Сводка_покрытия.csv   — № ФО; ФО; Веток всего; Веток покрыто; % ветвей.

«Покрыт» — датчик сработал в трассе. «не инстр.» — датчик не ставился
(системный заголовок и т.п.; определяется по Карта_датчиков.csv).

Использование:
  python3 coverage_report.py --traces <dir|files> --reports <static-dir>
      --sensor-map <Карта_датчиков.csv> --out <dir>
"""
import argparse, csv, glob, os
from pathlib import Path


def read_traces(paths):
    """Множество (fo, br), встреченных в трассах."""
    seen = set()
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += glob.glob(os.path.join(p, "*.log"))
        else:
            files += glob.glob(p)
    for f in files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if ":" not in line:
                    continue
                a, _, b = line.partition(":")
                try:
                    seen.add((int(a), int(b)))
                except ValueError:
                    continue
    return seen, files


def read_csv(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.reader(fh, delimiter=";"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--sensor-map", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    reports = Path(args.reports)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    seen, tfiles = read_traces(args.traces)
    print(f"Трасс прочитано: {len(tfiles)}, уникальных срабатываний: {len(seen)}")

    # Что было инструментировано (по карте датчиков). Читаем по ЗАГОЛОВКУ —
    # карты C++ (с колонкой sid) и Python (без неё) имеют разный порядок столбцов.
    instr_fo = set()       # ФО с датчиком входа
    instr_br = set()       # (fo, #N) с датчиком ветви
    smap = read_csv(Path(args.sensor_map))
    hdr = smap[0]
    ci_fo = hdr.index("№ ФО")
    ci_br = next(i for i, h in enumerate(hdr) if h.startswith("Запись"))
    for row in smap[1:]:
        if len(row) <= max(ci_fo, ci_br):
            continue
        try:
            fo, br = int(row[ci_fo]), int(row[ci_br])
        except ValueError:
            continue
        if br == 0:
            instr_fo.add(fo)
        elif br >= 1:
            instr_br.add((fo, br))

    def fo_status(fo):
        if (fo, 0) in seen: return "да"
        return "нет" if fo in instr_fo else "не инстр."

    def br_status(fo, n):
        if (fo, n) not in instr_br: return "не инстр."
        return "да" if (fo, n) in seen else "нет"

    # --- 1. Покрытие_ФО ---
    fo_rows = read_csv(reports / "Перечень_ФО(процедур_функций).csv")
    out_fo = []
    # static_fo — ВСЕ ФО из статики (знаменатель "по всем объектам");
    # tot_fo — подмножество с реально поставленным датчиком (знаменатель
    # "по инструментированным", без "не инстр." — см. fo_status). Лог
    # печатает оба, чтобы видно было, какая доля ФО вообще инструментирована,
    # а не только итоговый % среди уже инструментированных.
    static_fo = cov_fo = tot_fo = 0
    for row in fo_rows[1:]:
        if not (row and row[0].strip() and len(row) > 1 and row[1].strip()):
            continue
        num = int(row[0]); name = row[1]
        st = fo_status(num)
        out_fo.append([num, name, st])
        static_fo += 1
        if st != "не инстр.":
            tot_fo += 1
            if st == "да": cov_fo += 1
    with open(out / "Покрытие_ФО.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";"); w.writerow(["№ ФО", "ФО", "Покрыт"]); w.writerows(out_fo)

    # --- 2. Покрытие_ветвей (= Перечень_ветвей + Покрыта) ---
    bl = read_csv(reports / "Перечень_ветвей.csv")
    hdr = bl[0] + ["Покрыта"]
    out_br = []
    per_fo = {}            # fo -> [total, covered] среди инструментированных
    # static_br — ВСЕ ветви из статики; tot_br — подмножество с датчиком
    # (см. static_fo выше — та же логика, для ветвей).
    static_br = cov_br = tot_br = 0
    for row in bl[1:]:
        if len(row) < 7: continue
        fo = int(row[1]); n = int(row[3])
        st = br_status(fo, n)
        out_br.append(row + [st])
        static_br += 1
        if st != "не инстр.":
            tot_br += 1
            per_fo.setdefault(fo, [0, 0, row[2]])
            per_fo[fo][0] += 1
            if st == "да":
                cov_br += 1
                per_fo[fo][1] += 1
    with open(out / "Покрытие_ветвей.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";"); w.writerow(hdr); w.writerows(out_br)

    # --- 3. Сводка_покрытия ---
    out_sum = []
    for fo in sorted(per_fo):
        total, covered, name = per_fo[fo]
        pct = f"{100*covered/total:.1f}%" if total else "—"
        out_sum.append([fo, name, total, covered, pct])
    with open(out / "Сводка_покрытия.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["№ ФО", "ФО", "Веток всего", "Веток покрыто", "% ветвей"])
        w.writerows(out_sum)

    print("=" * 56)
    # Два знаменателя рядом: "по статике" (всё, что есть в Перечень_ФО/
    # Перечень_ветвей.csv) и "по инструментированным" (за вычетом "не
    # инстр." — самодостаточные макросы, идиома CHECK и т.п., см.
    # fo_status/br_status выше) — иначе разница между этапами статики,
    # инструментации и покрытия выглядит как необъяснимый разброс чисел.
    print(f"ФО:    по статике {static_fo}, инструментировано {tot_fo} "
          f"({100*tot_fo/max(static_fo,1):.1f}%), покрыто {cov_fo}/{tot_fo} "
          f"({100*cov_fo/max(tot_fo,1):.1f}%)")
    print(f"Ветви: по статике {static_br}, инструментировано {tot_br} "
          f"({100*tot_br/max(static_br,1):.1f}%), покрыто {cov_br}/{tot_br} "
          f"({100*cov_br/max(tot_br,1):.1f}%)")
    print(f"Отчёты: {out}/Покрытие_ФО.csv, Покрытие_ветвей.csv, Сводка_покрытия.csv")


if __name__ == "__main__":
    main()
