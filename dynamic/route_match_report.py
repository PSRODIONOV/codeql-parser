#!/usr/bin/env python3
"""
Сопоставление ФАКТИЧЕСКИХ маршрутов выполнения (из трасс) со СТАТИЧЕСКИМИ.

Строит два отчёта, зеркально статическим отчётам о маршрутах:
  - Сопоставление_маршрутов(функций_процедур).csv — по цепочкам ВЫЗОВОВ
    (vs Маршруты_выполнения_ФО(процедур_функций).csv); строится всегда, когда
    есть статический отчёт по вызовам.
  - Сопоставление_маршрутов(ветвей).csv — по последовательностям ВЕТВЕЙ внутри ФО
    (vs Маршруты_выполнения_ФО(ветвей).csv); строится ТОЛЬКО если в статике есть
    отчёт по ветвям (Перечень_ветвей.csv) И в трассах есть информация о ветвях.

Рантайм датчиков пишет на выходе из каждого вызова ФО две строки:
  R fo:b1>b2>...      — фактический маршрут по «да»-ветвям;
  C fo:fo>c1>c2>...   — фактическая цепочка вызовов (self, затем вызванные ФО).
Уникальные пути пишутся 1,2,4,8… раз (анти-спам на уровне маршрута).

Использование:
  python3 route_match_report.py --traces <dir|files> --reports <static-dir> --out <dir>
"""
import argparse, csv, glob, os, re
from pathlib import Path
from collections import defaultdict, Counter

_TOKEN = re.compile(r"^(\w+)\s+#(\d+)\s+-(.+)$")
_CALLNUM = re.compile(r"\((\d+)\)")
BRANCH_CSV = "Маршруты_выполнения_ФО(ветвей).csv"
CALL_CSV = "Маршруты_выполнения_ФО(процедур_функций).csv"
INVENTORY_CSV = "Перечень_ветвей.csv"


def read_csv(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.reader(fh, delimiter=";"))


def is_instrumented(btype: str, outcome: str) -> bool:
    """Сработает ли датчик ветви: датчик стоит на «да»-стороне (then/тело цикла/
    try-блок). Для try вход в блок происходит при любом исходе. Метки switch
    (case/default) инструментируются и срабатывают при достижении (в т.ч. через
    fallthrough), поэтому считаются сработавшими."""
    if btype in ("if", "for", "while", "do"):
        return outcome.strip() == "да"
    if btype in ("try", "case", "default"):
        return True
    return False


def _collapse_cycles(seq):
    """Схлопывает подряд идущие повторы блоков в последовательности ветвей —
    приводит ФАКТИЧЕСКИЙ маршрут (рантайм пишет каждую итерацию цикла) к ОДНОМУ
    проходу, как в статическом перечислителе маршрутов. Примеры:
        (1,2,1,2,1,2) -> (1,2)     # цикл из двух ветвей, 3 итерации
        (1,1,1)       -> (1)       # одна ветвь, 3 итерации
        (1,2,3,2,3)   -> (1,2,3)   # вложенный повтор
    Итеративно до стабилизации; всегда оставляем ОДИН экземпляр блока, начиная
    с самого раннего и короткого (детерминированно). Маршруты короткие
    (≤ сотен элементов), поэтому O(n²) приемлемо.

    ПРИМ.: если итерации цикла проходят РАЗНЫЕ ветви (напр. (1,3,1,2) —
    continue на первой, выход на второй), это не повтор блока и НЕ схлопывается —
    такой маршрут останется «непредусмотренным» (одного статического прохода для
    него действительно нет)."""
    s = list(seq)
    changed = True
    while changed:
        changed = False
        n = len(s)
        for i in range(n):
            for L in range(1, (n - i) // 2 + 1):
                block = s[i:i + L]
                j = i + L
                while j + L <= n and s[j:j + L] == block:
                    j += L
                if j > i + L:                      # блок повторился ≥1 раза подряд
                    s = s[:i + L] + s[j:]          # оставить один экземпляр
                    changed = True
                    break
            if changed:
                break
    return tuple(s)


def _branch_sig(route_str: str):
    """route_str → кортеж номеров инструментированных ветвей по порядку
    (с нормализацией циклов — см. _collapse_cycles)."""
    seq = []
    for tok in route_str.split("->"):
        m = _TOKEN.match(tok.strip())
        if m and is_instrumented(m.group(1), m.group(3)):
            seq.append(int(m.group(2)))
    return _collapse_cycles(seq)


def _call_sig(route_str: str):
    """call_str «(6)->(14)->(20)» → кортеж номеров ФО (self, callee…)."""
    return tuple(int(x) for x in _CALLNUM.findall(route_str))


def parse_static(reports: Path, fname: str, sig_fn):
    """Возвращает (order[(fo_num,fo_name)], routes[fo_num]=[(rnum, route_str, sig)])."""
    rows = read_csv(reports / fname)
    routes = defaultdict(list)
    order = []
    cur_num = cur_name = None
    for row in rows[1:]:
        if len(row) < 5:
            continue
        if row[1].strip():
            cur_num = int(row[1]); cur_name = row[2]
            order.append((cur_num, cur_name))
        if cur_num is None:
            continue
        routes[cur_num].append((row[3], row[4], sig_fn(row[4])))
    return order, routes


def read_actual(paths):
    """Читает строки R (ветви) и C (вызовы) из трасс.
    Возвращает (br[fo]={seq:n}, cl[fo]={seq:n}, any_branch_info, files)."""
    files = []
    for p in paths:
        files += glob.glob(os.path.join(p, "*.log")) if os.path.isdir(p) else glob.glob(p)
    br = defaultdict(lambda: defaultdict(int))
    cl = defaultdict(lambda: defaultdict(int))
    any_branch = False
    for f in files:
        with open(f, encoding="utf-8-sig", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                tag = line[:2]
                if tag not in ("R ", "C "):
                    continue
                fo_s, _, seq_s = line[2:].partition(":")
                try:
                    fo = int(fo_s)
                except ValueError:
                    continue
                seq = tuple(int(x) for x in seq_s.split(">") if x.strip().lstrip("-").isdigit())
                if tag == "R ":
                    # Нормализация циклов: каждую итерацию цикла рантайм пишет
                    # отдельно (1>2>1>2>…) — схлопываем до одного прохода (1>2),
                    # как в статическом маршруте. Разные счётчики итераций
                    # суммируются в один структурный маршрут.
                    seq = _collapse_cycles(seq)
                    br[fo][seq] += 1
                    if seq:
                        any_branch = True
                else:
                    cl[fo][seq] += 1
    return br, cl, any_branch, files


def build_rows(order, routes, actual, render_fn, mark_try_ambig):
    rows = []
    n_static = n_exec = n_unexp = 0
    for fo_num, fo_name in order:
        acts = dict(actual.get(fo_num, {}))
        sig_count = Counter(sig for _, _, sig in routes.get(fo_num, []))
        static_sigs = set()
        for rnum, rstr, sig in routes.get(fo_num, []):
            static_sigs.add(sig)
            cnt = acts.get(sig, 0)
            executed = cnt > 0
            n_static += 1
            n_exec += 1 if executed else 0
            typ = "неоднозначно (try)" if (mark_try_ambig and sig_count[sig] > 1) else "статический"
            rows.append([fo_num, fo_name, rnum, rstr,
                         "да" if executed else "нет", cnt if executed else "", typ])
        for sig, cnt in sorted(acts.items()):
            if sig in static_sigs:
                continue
            n_unexp += 1
            rows.append([fo_num, fo_name, "", render_fn(sig), "да", cnt, "непредусмотренный"])
    return rows, (n_static, n_exec, n_unexp)


def _write(out: Path, fname: str, rows):
    with open(out / fname, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["№ ФО", "Функциональный объект", "№ маршрута", "Маршрут",
                    "Исполнялся", "Кол-во", "Тип записи"])
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", required=True)
    ap.add_argument("--reports", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    reports = Path(args.reports)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    br, cl, any_branch, tfiles = read_actual(args.traces)
    print(f"Трасс прочитано: {len(tfiles)}")

    # 1. Маршруты по вызовам (функции/процедуры) — если есть статический отчёт.
    if (reports / CALL_CSV).exists():
        order, routes = parse_static(reports, CALL_CSV, _call_sig)
        rows, (ns, ne, nu) = build_rows(
            order, routes, cl,
            lambda s: "->".join(f"({n})" for n in s), mark_try_ambig=False)
        _write(out, "Сопоставление_маршрутов(функций_процедур).csv", rows)
        print(f"[функции/процедуры] статических: {ns}, исполнено: {ne}, "
              f"непредусмотренных: {nu}")
    else:
        print(f"[функции/процедуры] пропущено: нет {CALL_CSV}")

    # 2. Маршруты по ветвям — только если есть статика по ветвям И динамика по ветвям.
    has_static_branches = (reports / BRANCH_CSV).exists() and (reports / INVENTORY_CSV).exists()
    if has_static_branches and any_branch:
        order, routes = parse_static(reports, BRANCH_CSV, _branch_sig)
        rows, (ns, ne, nu) = build_rows(
            order, routes, br,
            lambda s: "Начало->" + "".join(f"#{b}->" for b in s) + "Конец",
            mark_try_ambig=True)
        _write(out, "Сопоставление_маршрутов(ветвей).csv", rows)
        print(f"[ветви] статических: {ns}, исполнено: {ne}, непредусмотренных: {nu}")
    elif not has_static_branches:
        print("[ветви] пропущено: нет статического отчёта по ветвям "
              "(Перечень_ветвей.csv / Маршруты_выполнения_ФО(ветвей).csv)")
    else:
        print("[ветви] пропущено: в трассах нет информации об отработке ветвей")

    print(f"Отчёты: {out}")


if __name__ == "__main__":
    main()
