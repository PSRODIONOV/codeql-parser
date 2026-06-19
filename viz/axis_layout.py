"""axis_layout.py — детерминированный укладчик блок-схем «ось + дорожки».

Не использует ELK/OGDF. Размещает узлы по правилам:
  • Y растёт сверху вниз в порядке строк исходника; start — вверху, end — внизу.
  • Основной поток — на центральной оси (x=0); ветви-экскурсии уходят в боковые
    дорожки по глубине вложенности (±k·LANE), поэтому не накладываются.
  • Порты фиксированы по типу узла (см. спецификацию).
  • Ортогональная маршрутизация рёбер; стрелки на всех рёбрах, кроме входящих
    в merge-поинт. Возвраты цикла и continue сливаются в общий поинт перед W.
  • return/throw/exit — терминатор + отдельный узел «Конец» рядом.

Результат — самостоятельный SVG (те же ГОСТ-фигуры, что и в elk_generator).
"""
import bisect
import collections
import heapq
import math
import re
from typing import Dict, List, Optional, Tuple
from viz.elk_generator import _node_size, _svg_color, _svg_escape

GAP = 38          # вертикальный зазор между узлами
LANE = 280        # горизонтальный шаг дорожки (экскурсии)
TERM = ("return", "throw", "exit")
JUMP = ("break", "continue", "goto")


class AxisLayout:
    def __init__(self, gen, func_name, func_num, func_index, var_index, spread=False):
        self.gen = gen
        self.fn = func_name
        self.fnum = func_num
        self.fi = func_index
        self.vi = var_index
        self.spread = spread          # разведение ветвей в непересекающиеся полосы
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []
        self._uid = 0

    # ── вспомогательное ────────────────────────────────────────────────────
    def _u(self, p):
        self._uid += 1
        return f"_{p}{self._uid}"

    @staticmethod
    def _wrap(text, width=46):
        """Переносит длинные строки метки по пробелам/операторам, не разрывая
        слова — чтобы условие целиком помещалось в один узел несколькими строками."""
        out = []
        for line in text.split("\n"):
            if len(line) <= width:
                out.append(line); continue
            cur = ""
            for tok in re.split(r"(\s+|(?<=[,&|])|(?=&&)|(?=\|\|))", line):
                if cur and len(cur) + len(tok) > width:
                    out.append(cur.rstrip()); cur = tok.lstrip()
                else:
                    cur += tok
            if cur.strip():
                out.append(cur.rstrip())
        return "\n".join(out)

    def _label(self, node):
        st = node["stmt_type"]; raw = node.get("stmt_label", st)
        # управляющие конструкции: полное условие (extract) + перенос, БЕЗ клипа
        # _format_label (он обрезал длинные условия в «...»).
        if st in ("if", "while", "for", "do", "return", "try", "switch"):
            raw = self.gen._extract_condition_text(node["stmt_id"], st, raw)
            b = node.get("branch_num")
            if b and st != "return":
                return f"#{b}\n{self._wrap(raw)}"
            return self._wrap(raw)
        if st in ("call", "io", "process", "throw", "exit", "break",
                  "continue", "goto", "label"):
            return raw
        return self.gen._format_label(raw, self.fi, self.vi)

    def _shape(self, st):
        if st in ("while", "for", "do"):
            return "hexagon", "", "#ffffff"
        if st in ("if", "try", "switch"):
            return "diamond", "", "#ffffff"
        if st == "break":
            return "diamond", "filled", "#cfe6ff"          # голубой
        if st == "call":
            return "box2", "", "#ffffff"
        if st in ("throw", "exit"):
            return "rounded", "rounded,filled", "#e6d0ff"  # фиолетовый (исключения/сист.выход)
        if st == "return":
            return "rounded", "rounded,filled", "#e8e8e8"  # нейтральный
        if st in ("goto", "label"):
            return "circle", "filled", "#fff2b3"           # жёлтый
        return "box", "", "#ffffff"

    def _node(self, nid, cx, cy, w, h, shape, style, fill, label):
        self.nodes[nid] = {"cx": cx, "cy": cy, "w": w, "h": h, "shape": shape,
                           "style": style, "fill": fill, "label": label}

    def _edge(self, pts, label=None, arrow=True, color="black", dashed=False):
        self.edges.append({"pts": pts, "label": label, "arrow": arrow,
                           "color": color, "dashed": dashed})

    # порты узла
    @staticmethod
    def N(n): return (n["cx"], n["cy"] - n["h"] / 2)
    @staticmethod
    def S(n): return (n["cx"], n["cy"] + n["h"] / 2)
    @staticmethod
    def W(n): return (n["cx"] - n["w"] / 2, n["cy"])
    @staticmethod
    def E(n): return (n["cx"] + n["w"] / 2, n["cy"])

    def _size(self, node):
        st = node["stmt_type"]
        sh, style, _ = self._shape(st)
        gshape = {"box2": "box", "rounded": "box"}.get(sh, sh)
        return _node_size(self._label(node), gshape, style)

    # ── основная рекурсия ──────────────────────────────────────────────────
    def _seq(self, stmts, ax, y0, depth, loop):
        """Раскладывает последовательность операторов на оси ax с y0.
        Возвращает (top|None, exit|None, y_end, first_id|None, last_id|None)."""
        stmts = sorted(stmts, key=lambda s: int(s.get("line_start", 0) or 0))
        prev_exit = None; first_top = None; first_id = None; last_id = None; y = y0
        for s in stmts:
            top, exitp, y, nid = self._stmt(s, ax, y, depth, loop)
            if first_top is None:
                first_top, first_id = top, nid
            if prev_exit is not None and top is not None and prev_exit != top:
                self._edge([prev_exit, top])
            prev_exit = exitp; last_id = nid
            y += GAP
        return first_top, prev_exit, y, first_id, last_id

    def _stmt(self, s, ax, y, depth, loop):
        """Возвращает (top_point, exit_point|None, y_end, node_id)."""
        st = s["stmt_type"]
        sh, style, fill = self._shape(st)
        w, h = self._size(s)
        nid = self.gen._dot_id(self.fn, s["stmt_id"])
        if nid in self.nodes:
            nid = self._u("n")
        cx, cy = ax, y + h / 2
        self._node(nid, cx, cy, w, h, sh, style, fill, self._label(s))
        n = self.nodes[nid]
        top = (cx, y); bot = (cx, y + h)

        # ── простые операторы ──
        if st in ("call", "process", "io", "expr", "code", "label", "goto") \
                or st not in ("if", "try", "switch", "while", "for", "do",
                              "return", "throw", "exit", "break", "continue"):
            if st == "goto":
                # соединитель: безусловный переход, конец пути
                return top, None, y + h, nid
            return top, bot, y + h, nid

        # ── терминаторы: + отдельный узел «Конец» справа ──
        if st in TERM:
            ew, eh = _node_size("Конец", "box", "rounded")
            eid = self._u("end")
            self._node(eid, cx + w / 2 + LANE * 0.35 + ew / 2, cy, ew, eh,
                       "rounded", "rounded,filled", "#ffd0d0", "Конец")   # end — красный
            self._edge([self.E(n), self.W(self.nodes[eid])])
            return top, None, y + h, nid

        # continue/break в конце многооператорной ветви (inline): узел уносим
        # в колонку цикла (continue — слева, break — справа) на одну ось с
        # одиночными `if(cond) continue/break;`. Перенос делает _loop.
        if st == "continue":
            if loop is not None:
                loop["cont_inline"].append((nid, top))
            return top, None, y + h, nid
        if st == "break":
            if loop is not None:
                loop["brk_inline"].append((nid, top))
            return top, None, y + h, nid

        # ── цикл ──
        if st in ("while", "for", "do"):
            return self._loop(s, n, ax, y, depth, loop)

        # ── ветвления ──
        return self._branch(s, n, ax, y, depth, loop)

    def _count(self, children):
        """Число операторов в поддереве (мера «размера» ветви)."""
        return sum(1 + self._count(c.get("children", [])) for c in children)

    def _contains_jump(self, children):
        """'break'/'continue', который ведёт к ТЕКУЩЕМУ циклу (без спуска во
        вложенные циклы — у них своя область), иначе None. break приоритетнее."""
        found = None
        for c in children:
            st = c["stmt_type"]
            if st == "break":
                return "break"
            if st == "continue":
                found = found or "continue"
            elif st in ("while", "for", "do"):
                continue  # вложенный цикл — его break/continue не наши
            else:
                r = self._contains_jump(c.get("children", []))
                if r == "break":
                    return "break"
                found = found or r
        return found

    def _children_split(self, s):
        ch = s.get("children", [])
        st = s["stmt_type"]
        if st == "try":
            el = [c for c in ch if int(c.get("in_catch", 0) or 0)]   # catch = else
            th = [c for c in ch if not int(c.get("in_catch", 0) or 0)]
            return th, el
        el_line = int(s.get("else_line", 0) or 0)
        if el_line:
            th = [c for c in ch if int(c.get("line_start", 0) or 0) < el_line]
            el = [c for c in ch if int(c.get("line_start", 0) or 0) >= el_line]
            return th, el
        return list(ch), []

    def _branch(self, s, n, ax, y, depth, loop):
        cx, cy = n["cx"], n["cy"]; h = n["h"]
        top = (cx, y); bot = self.S(n)
        then_ch, else_ch = self._children_split(s)
        ybr = y + h + GAP

        # Спец-случай `if (cond) continue;` / `if (cond) break;`:
        # узел-джамп уносим на ПОЛЕ цикла (continue — слева, break — справа),
        # ребро и возврат строит _loop. «нет» идёт вниз по оси.
        if (loop is not None and not else_ch and len(then_ch) == 1
                and then_ch[0]["stmt_type"] in ("continue", "break")):
            jmp = then_ch[0]; jst = jmp["stmt_type"]
            sh, style, fill = self._shape(jst); w2, h2 = self._size(jmp)
            jid = self.gen._dot_id(self.fn, jmp["stmt_id"])
            if jid in self.nodes:
                jid = self._u("n")
            self._node(jid, cx, cy, w2, h2, sh, style, fill, self._label(jmp))
            loop["brk" if jst == "break" else "cont"].append((jid, self._idof(n)))
            return top, bot, max(y + h, ybr), self._idof(n)

        SEP = 200
        xL, xR = ax - n["w"] / 2 - SEP, ax + n["w"] / 2 + SEP
        if else_ch:
            # двухветвевой. Зеркалирование: ветвь к continue → ВЛЕВО, к break → ВПРАВО.
            tj, ej = self._contains_jump(then_ch), self._contains_jump(else_ch)
            then_left = (tj == "continue") or (ej == "break")
            # Нет jump-предпочтения → БОЛЬШУЮ ветвь кладём ВЛЕВО (её левые каналы
            # циклов тянутся дальше; малую — вправо, чтобы они её не пересекали).
            size_based = (tj not in ("continue", "break")
                          and ej not in ("continue", "break"))
            if size_based:
                then_left = self._count(then_ch) >= self._count(else_ch)
            # Большой ветви (выбранной по размеру) даём доп. сдвиг наружу, чтобы
            # её return-bus вложенных циклов не пересекали соседние буферы.
            EX = 180 if size_based else 0
            if then_left:
                tx, ex, tp, ep = xL - EX, xR, self.W(n), self.E(n)
            else:
                tx, ex, tp, ep = xR + EX, xL, self.E(n), self.W(n)
            lim_left = ax - n["w"] / 2 - 30
            lim_right = ax + n["w"] / 2 + 30

            def _shift(keys, e_lo, e_hi, res, side):
                if not self.spread or not keys:
                    return res
                xmin, xmax = self._extent(keys)
                dx = 0
                if side == "L" and xmax > lim_left:
                    dx = lim_left - xmax
                elif side == "R" and xmin < lim_right:
                    dx = lim_right - xmin
                if dx:
                    self._translate(keys, e_lo, e_hi, dx)
                    res = list(res)
                    if res[0]: res[0] = (res[0][0] + dx, res[0][1])
                    if res[1]: res[1] = (res[1][0] + dx, res[1][1])
                return res

            et0 = len(self.edges)
            te0 = len(self.edges); bt = set(self.nodes)
            t = self._seq(then_ch, tx, ybr, depth + 1, loop); te1 = len(self.edges)
            tkeys = set(self.nodes) - bt
            t = _shift(tkeys, te0, te1, t, "L" if then_left else "R")
            ee0 = len(self.edges); be = set(self.nodes)
            e = self._seq(else_ch, ex, ybr, depth + 1, loop); ee1 = len(self.edges)
            ekeys = set(self.nodes) - be
            e = _shift(ekeys, ee0, ee1, e, "R" if then_left else "L")
            if t[0]: self._edge([tp, (t[0][0], cy), t[0]], "да")
            if e[0]: self._edge([ep, (e[0][0], cy), e[0]], "нет")
            ymax = max(t[2], e[2])
            mp = self._merge(cx, ymax); mpp = self.nodes[mp]["cx_pt"]
            # ОБЩИЙ extent ОБЕИХ ветвей (узлы + рёбра): канал merge ветви учитывает
            # крайние рёбра СОСЕДНЕЙ ветви, иначе их конечные рёбра пересекаются.
            cxs = []
            for k in tkeys | ekeys:
                nd = self.nodes[k]; cxs += [nd["cx"] - nd["w"] / 2, nd["cx"] + nd["w"] / 2]
            for ed in self.edges[et0:]:
                for (px, _py) in ed["pts"]:
                    cxs.append(px)
            cmin = min(cxs) if cxs else cx
            cmax = max(cxs) if cxs else cx
            # Собираем merge-выходы обеих ветвей и назначаем каналы СОВМЕСТНО:
            # ветвь, кончающаяся циклом, выходит ВПРАВО (порт E); обычная — по своей
            # стороне. Несколько выходов в одну сторону — в РАЗНЫЕ каналы за общим
            # extent, по убыванию y (нижний → внутренний канал), чтобы конечные
            # рёбра ветвей не пересекались.
            items = []
            for seqres, ex_pt, br_left in ((t, t[1], then_left), (e, e[1], not then_left)):
                if ex_pt is None:
                    continue
                lp = self.nodes.get(seqres[4]) if seqres[4] else None
                if lp is not None and "_exit_bus" in lp:
                    items.append(["R", lp["cy"], "loop", lp])
                else:
                    items.append(["L" if br_left else "R", ex_pt[1], "edge", ex_pt])

            def _draw_merge(it, ch):
                if it[2] == "loop":
                    lp = it[3]; ee = self.edges[lp["_exit_edge"]]; eb = lp["_exit_bus"]
                    ee["pts"] = ee["pts"][:2] + [(ch, lp["cy"]), (ch, ymax), mpp]
                    ee["arrow"] = False
                else:
                    ex_pt = it[3]
                    # ПРЯМО (вниз в своей колонке → по низу к merge), если чисто —
                    # без перелёта к внешнему каналу; иначе в обход через ch.
                    if self._clear_vert(ex_pt[0], ex_pt[1], ymax) \
                            and self._clear_horiz(ymax, ex_pt[0], mpp[0]):
                        self._edge([ex_pt, (ex_pt[0], ymax), mpp], arrow=False)
                    else:
                        self._edge([ex_pt, (ch, ex_pt[1]), (ch, ymax), mpp], arrow=False)

            rights = sorted([it for it in items if it[0] == "R"], key=lambda it: -it[1])
            lefts = sorted([it for it in items if it[0] == "L"], key=lambda it: -it[1])
            for idx, it in enumerate(rights):
                _draw_merge(it, cmax + 25 + idx * 30)
            for idx, it in enumerate(lefts):
                _draw_merge(it, cmin - 25 - idx * 30)
            return top, mpp, ymax, self._idof(n)
        else:
            # одноветвевой. Зеркалирование: ветвь к break — ВПРАВО (к выходу),
            # иначе ВЛЕВО. «нет» обычно идёт вниз по оси (S), НО если ветвь «да»
            # ушла вправо и её поддерево тянет рёбра влево (вложенные двухветвевые
            # if), прямой «нет» по оси их пересекает — тогда выводим «нет» через
            # СВОБОДНЫЙ порт W и ведём левее всей правой экскурсии (канал).
            to_right = (self._contains_jump(then_ch) == "break")
            tx, tp = (xR, self.E(n)) if to_right else (xL, self.W(n))
            before = set(self.nodes)
            t = self._seq(then_ch, tx, ybr, depth + 1, loop)
            if t[0]: self._edge([tp, (t[0][0], cy), t[0]], "да")
            # «нет» обычно идёт прямо вниз из СВОБОДНОЙ нижней вершины (S).
            # W-детур (огибание слева) включаем ТОЛЬКО если да-поддерево реально
            # уходит левее оси (вложенные двухветвевые if тянут рёбра влево) —
            # иначе прямой «нет» по оси чист.
            nx = None
            if to_right:
                dxmin, _ = self._extent(set(self.nodes) - before)
                if dxmin < cx - n["w"] / 2 - 10:
                    nx = dxmin - 30
            if t[1] is not None:
                ymax = max(t[2], y + h + GAP)
                mp = self._merge(cx, ymax); mpp = self.nodes[mp]["cx_pt"]
                if nx is not None:   # «нет» из W → левый канал → вниз → на ось
                    self._edge([self.W(n), (nx, cy), (nx, ymax), mpp], "нет", arrow=False)
                else:
                    self._edge([bot, mpp], "нет", arrow=False)
                self._edge([t[1], (t[1][0], ymax), mpp], arrow=False)
                return top, mpp, ymax, self._idof(n)
            else:
                # да-ветвь терминируется (break/return) → «нет» = продолжение:
                # выход = нижняя вершина на оси, дальше тело-возврат сам ведёт его
                # к шине (прямо на своём уровне, если чисто). Детур nx тут не нужен —
                # «нет» вниз не идёт, пересекать да-поддерево нечем.
                yend = max(t[2], y + h)
                return top, bot, yend, self._idof(n)

    def _extent(self, keys):
        """x-границы [xmin, xmax] множества узлов по их id."""
        xs0 = [self.nodes[k]["cx"] - self.nodes[k]["w"] / 2 for k in keys if k in self.nodes]
        xs1 = [self.nodes[k]["cx"] + self.nodes[k]["w"] / 2 for k in keys if k in self.nodes]
        return (min(xs0) if xs0 else 0, max(xs1) if xs1 else 0)

    def _translate(self, node_ids, e_lo, e_hi, dx):
        """Сдвигает поддерево ветви по X: узлы (и их merge-точки/каналы) + рёбра,
        созданные в диапазоне [e_lo, e_hi)."""
        if not dx:
            return
        for nid in node_ids:
            nd = self.nodes[nid]
            nd["cx"] += dx
            if "cx_pt" in nd:
                nd["cx_pt"] = (nd["cx_pt"][0] + dx, nd["cx_pt"][1])
            if "_exit_bus" in nd:
                nd["_exit_bus"] += dx
        for ei in range(e_lo, e_hi):
            self.edges[ei]["pts"] = [(x + dx, yv) for (x, yv) in self.edges[ei]["pts"]]

    def _clear_horiz(self, y, xa, xb):
        """Свободна ли горизонталь y в [xa,xb] от узлов и вертикальных рёбер."""
        xlo, xhi = min(xa, xb), max(xa, xb)
        for nd in self.nodes.values():
            if nd["shape"] == "point":
                continue
            if nd["cy"] - nd["h"] / 2 < y < nd["cy"] + nd["h"] / 2 \
                    and nd["cx"] - nd["w"] / 2 < xhi - 1 and nd["cx"] + nd["w"] / 2 > xlo + 1:
                return False
        for e in self.edges:
            for (px, py), (qx, qy) in zip(e["pts"], e["pts"][1:]):
                if abs(px - qx) < 1e-6 and xlo + 1 < px < xhi - 1 \
                        and min(py, qy) < y < max(py, qy):
                    return False
        return True

    def _clear_vert(self, x, ya, yb):
        """Свободна ли вертикаль x в [ya,yb] от узлов и горизонтальных рёбер."""
        ylo, yhi = min(ya, yb), max(ya, yb)
        for nd in self.nodes.values():
            if nd["shape"] == "point":
                continue
            if nd["cx"] - nd["w"] / 2 < x < nd["cx"] + nd["w"] / 2 \
                    and nd["cy"] - nd["h"] / 2 < yhi - 1 and nd["cy"] + nd["h"] / 2 > ylo + 1:
                return False
        for e in self.edges:
            for (px, py), (qx, qy) in zip(e["pts"], e["pts"][1:]):
                # горизонтальное ребро, пересекающее вертикаль x
                if abs(py - qy) < 1e-6 and ylo + 1 < py < yhi - 1 \
                        and min(px, qx) < x < max(px, qx):
                    return False
                # вертикальное ребро на ТОМ ЖЕ x (напр. шина вложенного цикла)
                if abs(px - qx) < 1e-6 and abs(px - x) < 2 \
                        and not (max(py, qy) <= ylo + 1 or min(py, qy) >= yhi - 1):
                    return False
        return True

    def _loop(self, s, n, ax, y, depth, loop):
        cx, cy, w, h = n["cx"], n["cy"], n["w"], n["h"]
        top = (cx, y)
        body_ch = list(s.get("children", []))
        myloop = {"returns": [], "breaks": [], "cont": [], "brk": [],
                  "cont_inline": [], "brk_inline": [], "W": self.W(n)}
        before = set(self.nodes); eidx0 = len(self.edges)
        if body_ch:
            b = self._seq(body_ch, ax, y + h + GAP, depth + 1, myloop)
            if b[0]:
                self._edge([self.S(n), b[0]], "да")
            if b[1] is not None:
                # тело-возврат выводим из БОКОВОГО порта (W) последнего узла тела
                # по его ЦЕНТРУ — тогда вход в шину на уровне центра, низ шины
                # совпадает (без свисания), и _sideport его уже не двигает.
                lastn = self.nodes.get(b[4]) if b[4] else None
                if (lastn and lastn["shape"] != "point"
                        and abs(b[1][0] - lastn["cx"]) < 2
                        and abs(b[1][1] - (lastn["cy"] + lastn["h"] / 2)) < 2):
                    myloop["returns"].append(self.W(lastn))
                else:
                    myloop["returns"].append(b[1])
            ybody_end = b[2]
        else:
            ybody_end = y + h + GAP
        CH = 40
        # extent тела БЕЗ узлов-джампов (их разместим на полях цикла)
        jump_ids = ({jid for jid, _ in myloop["cont"]} | {jid for jid, _ in myloop["brk"]}
                    | {jid for jid, _ in myloop["cont_inline"]}
                    | {jid for jid, _ in myloop["brk_inline"]})
        bxmin, bxmax = self._extent((set(self.nodes) - before) - jump_ids)
        bxmin = min(bxmin, cx - w / 2); bxmax = max(bxmax, cx + w / 2)
        # Разнесённые колонки и каналы с учётом ПОЛУШИРИНЫ узлов джампов, чтобы
        # ни тело, ни каналы не накладывались на сами ромбы break/continue.
        bn = [self.nodes[j] for j, _ in myloop["brk"]] + [self.nodes[j] for j, _ in myloop["brk_inline"]]
        cn = [self.nodes[j] for j, _ in myloop["cont"]] + [self.nodes[j] for j, _ in myloop["cont_inline"]]
        wb = max([n["w"] for n in bn], default=0) / 2
        wc = max([n["w"] for n in cn], default=0) / 2
        brk_x = bxmax + CH + wb        # центр колонки break (лев. край = bxmax+CH)
        exit_bus = brk_x + wb + CH     # канал выхода — правее колонки break
        ry = ybody_end

        # Колонка continue и шина возврата — левее контента в y-диапазоне присоединений.
        jy = []
        for jid, ifid in myloop["cont"]:
            ifn = self.nodes[ifid]; jy.append(ifn["cy"] + ifn["h"] / 2 + GAP + 30)
        for jid, _ in myloop["cont_inline"]:
            jy.append(self.nodes[jid]["cy"])
        if body_ch and b[1] is not None:
            jy.append(b[1][1])
        bbot = max(jy) if jy else cy
        lm = cx - w / 2
        for k in (set(self.nodes) - before) - jump_ids:
            nd = self.nodes[k]
            if nd["cy"] + nd["h"] / 2 > cy + 1 and nd["cy"] - nd["h"] / 2 < bbot - 1:
                lm = min(lm, nd["cx"] - nd["w"] / 2)
        cont_x = lm - CH - wc          # центр колонки continue (правый край = lm-CH)
        ret_bus = cont_x - wc - CH     # шина возвратов — левее колонки continue
        # Сдвигаем шину влево, пока её вертикаль не освободится от уже стоящих
        # шин ВЛОЖЕННЫХ циклов (иначе шины вложенного и внешнего цикла совпадут).
        guard = 0
        while not self._clear_vert(ret_bus, cy, bbot) and guard < 60:
            ret_bus -= CH; guard += 1

        # Без continue: back-edge ведём по БЛИЖАЙШЕМУ к W свободному вертикальному
        # каналу (а не у левого края), чтобы горизонталь шина→W была короткой.
        if not (myloop["cont"] or myloop["cont_inline"]) and body_ch and b[1] is not None:
            r0 = b[1]; wx = self.W(n)[0]
            xe = set()
            for k in (set(self.nodes) - before) - jump_ids:
                nd = self.nodes[k]
                if nd["cy"] + nd["h"] / 2 > cy + 1 and nd["cy"] - nd["h"] / 2 < bbot - 1:
                    xe.add(nd["cx"] - nd["w"] / 2); xe.add(nd["cx"] + nd["w"] / 2)
            sxe = sorted(xe)
            cands = [(a + b2) / 2 for a, b2 in zip(sxe, sxe[1:])] + [(min(sxe) - CH) if sxe else ret_bus]
            for x in sorted([c for c in cands if c < wx - 1], reverse=True):
                if self._clear_vert(x, cy, r0[1]) and self._clear_horiz(r0[1], x, r0[0]) and self._clear_horiz(cy, x, wx):
                    ret_bus = x; break

        # continue: узел → cont_x, НИЖЕ своего if; вход if.W → горизонт на уровне
        # if (над узлом) → вниз в N (вход сверху, не через тело).
        for jid, ifid in myloop["cont"]:
            jn = self.nodes[jid]; ifn = self.nodes[ifid]
            jn["cx"] = cont_x
            jn["cy"] = ifn["cy"] + ifn["h"] / 2 + GAP + jn["h"] / 2
            self._edge([self.W(ifn), (cont_x, ifn["cy"]), self.N(jn)], "да")
            self._edge([self.W(jn), (ret_bus, jn["cy"])], arrow=False)   # → шина
        # break: узел → brk_x, НИЖЕ своего if; вход if.E → горизонт → вниз в N
        for jid, ifid in myloop["brk"]:
            jn = self.nodes[jid]; ifn = self.nodes[ifid]
            jn["cx"] = brk_x
            jn["cy"] = ifn["cy"] + ifn["h"] / 2 + GAP + jn["h"] / 2
            self._edge([self.E(ifn), (brk_x, ifn["cy"]), self.N(jn)], "да")
            myloop["breaks"].append(self.E(jn))   # выход break — порт E (вправо к каналу)

        # переадресация входящего ребра при переносе inline-джампа.
        # vertical_in=True → вход СВЕРХУ (N): горизонталь к колонке, затем вниз;
        # иначе вход сбоку: вниз в своей колонке, затем горизонталь в порт.
        def _redirect(old_top, new_port, vertical_in=False):
            for e in self.edges:
                p = e["pts"][-1]
                if abs(p[0] - old_top[0]) < 2 and abs(p[1] - old_top[1]) < 2:
                    ps = e["pts"][0]
                    if vertical_in:
                        e["pts"] = [ps, (new_port[0], ps[1]), new_port]
                    else:
                        e["pts"] = [ps, (ps[0], new_port[1]), new_port]
                    return
        # inline continue (конец многооператорной ветви): узел → cont_x, на одну
        # ось с одиночными; вход от предыдущего узла справа (E), выход → шина.
        for jid, old_top in myloop["cont_inline"]:
            jn = self.nodes[jid]; jn["cx"] = cont_x
            _redirect(old_top, self.E(jn))
            self._edge([self.W(jn), (ret_bus, jn["cy"])], arrow=False)
        # inline break: узел → brk_x; вход СВЕРХУ (N); выход → после цикла.
        for jid, old_top in myloop["brk_inline"]:
            jn = self.nodes[jid]; jn["cx"] = brk_x
            _redirect(old_top, self.N(jn), vertical_in=True)
            myloop["breaks"].append(self.E(jn))   # выход break — порт E (вправо к каналу)

        # тело-возврат: к шине НА СВОЁМ уровне (как continue), если путь свободен;
        # иначе — вниз до конца тела и влево (без пересечений).
        ret_join_ys = []
        for r in myloop["returns"]:
            if self._clear_horiz(r[1], ret_bus, r[0]):
                self._edge([r, (ret_bus, r[1])], arrow=False); ret_join_ys.append(r[1])
            else:
                self._edge([r, (r[0], ry), (ret_bus, ry)], arrow=False); ret_join_ys.append(ry)
        # шина возвратов: вертикаль ret_bus от самого нижнего присоединения → W.
        join_ys = ([self.nodes[j]["cy"] for j, _ in myloop["cont"]]
                   + [self.nodes[j]["cy"] for j, _ in myloop["cont_inline"]]
                   + ret_join_ys)
        bus_bottom = max(join_ys) if join_ys else None
        if bus_bottom is not None:
            self._edge([(ret_bus, bus_bottom), (ret_bus, cy), self.W(n)], "N")
            ybody_end = ry + GAP
        y_post = ybody_end + GAP
        # выход цикла: правая вершина E → канал выхода → вниз → на ось.
        # Метим узел: если цикл окажется последним в ветви, _branch перенаправит
        # это ребро прямо в merge по каналу выхода (без возврата на ось).
        n["_exit_bus"] = exit_bus
        # break-узлы ВЛИВАЮТСЯ в канал выхода (как continue в шину возврата):
        # каждый break.S → горизонталь в exit_bus на своём уровне (без стрелки) —
        # тогда их рёбра не накладываются друг на друга.
        for bp in myloop["breaks"]:
            self._edge([bp, (exit_bus, bp[1])], arrow=False)
        # канал выхода: правая вершина E + все break → вниз по exit_bus → после цикла.
        n["_exit_edge"] = len(self.edges)
        self._edge([self.E(n), (exit_bus, cy), (exit_bus, y_post), (ax, y_post)], "нет")
        return top, (ax, y_post), y_post, self._idof(n)

    # ── обходной ортогональный роутер (grid A*) ─────────────────────────────
    def _route_all(self):
        """Перемаршрутизирует рёбра по сетке каналов между узлами, обходя их
        bbox. Узлы — препятствия; рёбра идут по свободным горизонталям/вертикалям.
        Концы (порты) лежат внутри inflated-bbox своего узла — он для этого ребра
        не считается препятствием."""
        M = 10
        rects = []
        for n in self.nodes.values():
            if n["shape"] == "point":
                continue
            rects.append((n["cx"] - n["w"] / 2 - M, n["cy"] - n["h"] / 2 - M,
                          n["cx"] + n["w"] / 2 + M, n["cy"] + n["h"] / 2 + M))
        if not rects:
            return
        xs, ys = set(), set()
        for x0, y0, x1, y1 in rects:
            xs |= {round(x0, 1), round(x1, 1)}; ys |= {round(y0, 1), round(y1, 1)}
        for e in self.edges:
            for (x, y) in (e["pts"][0], e["pts"][-1]):
                xs.add(round(x, 1)); ys.add(round(y, 1))
        sx, sy = sorted(xs), sorted(ys)
        xs |= {round((a + b) / 2, 1) for a, b in zip(sx, sx[1:])}
        ys |= {round((a + b) / 2, 1) for a, b in zip(sy, sy[1:])}
        Xs, Ys = sorted(xs), sorted(ys)
        XI = {x: i for i, x in enumerate(Xs)}; YI = {y: i for i, y in enumerate(Ys)}
        nx, ny = len(Xs), len(Ys)

        # блокирующие множества для рёбер сетки (только непустые)
        vblock: Dict[tuple, set] = {}   # вертикальное ребро (i,j)->(i,j+1)
        hblock: Dict[tuple, set] = {}   # горизонтальное ребро (i,j)->(i+1,j)
        for ri, (x0, y0, x1, y1) in enumerate(rects):
            ci0 = bisect.bisect_right(Xs, x0); ci1 = bisect.bisect_left(Xs, x1)
            rj0 = bisect.bisect_right(Ys, y0); rj1 = bisect.bisect_left(Ys, y1)
            # вертикальные рёбра в колонках строго внутри (x0,x1)
            for i in range(ci0, ci1):
                for j in range(max(0, rj0 - 1), min(ny - 1, rj1)):
                    ya, yb = Ys[j], Ys[j + 1]
                    if y0 < yb and y1 > ya:
                        vblock.setdefault((i, j), set()).add(ri)
            # горизонтальные рёбра в строках строго внутри (y0,y1)
            for j in range(rj0, rj1):
                for i in range(max(0, ci0 - 1), min(nx - 1, ci1)):
                    xa, xb = Xs[i], Xs[i + 1]
                    if x0 < xb and x1 > xa:
                        hblock.setdefault((i, j), set()).add(ri)

        def containing(p):
            return {ri for ri, (x0, y0, x1, y1) in enumerate(rects)
                    if x0 < p[0] < x1 and y0 < p[1] < y1}

        TURN = 14.0
        USE = 60.0   # штраф за канал, уже занятый другим ребром (развязка)
        used: Dict[tuple, int] = {}

        def seg_key(i, j, di, dj):
            if di == 1:  return ("h", i, j)
            if di == -1: return ("h", i - 1, j)
            if dj == 1:  return ("v", i, j)
            return ("v", i, j - 1)

        def astar(si, sj, ti, tj, allowed):
            start = (si, sj, 0)
            h0 = abs(Xs[si] - Xs[ti]) + abs(Ys[sj] - Ys[tj])
            pq = [(h0, 0.0, start, None)]
            best = {}; parent = {}
            while pq:
                f, g, st, par = heapq.heappop(pq)
                i, j, d = st
                if st in best and best[st] <= g:
                    continue
                best[st] = g; parent[st] = par
                if i == ti and j == tj:
                    pts = []; cur = st
                    while cur is not None:
                        pts.append((Xs[cur[0]], Ys[cur[1]])); cur = parent[cur]
                    return pts[::-1]
                for di, dj, nd, blk in ((1, 0, 1, hblock.get((i, j))),
                                        (-1, 0, 1, hblock.get((i - 1, j))),
                                        (0, 1, 2, vblock.get((i, j))),
                                        (0, -1, 2, vblock.get((i, j - 1)))):
                    ni, nj = i + di, j + dj
                    if not (0 <= ni < nx and 0 <= nj < ny):
                        continue
                    if blk and not blk <= allowed:
                        continue
                    seg = abs(Xs[ni] - Xs[i]) + abs(Ys[nj] - Ys[j])
                    pen = USE * used.get(seg_key(i, j, di, dj), 0)
                    cost = g + seg + pen + (TURN if (d and d != nd) else 0.0)
                    ns = (ni, nj, nd)
                    if ns not in best or best[ns] > cost:
                        hh = abs(Xs[ni] - Xs[ti]) + abs(Ys[nj] - Ys[tj])
                        heapq.heappush(pq, (cost + hh, cost, ns, st))
            return None

        def mark_used(path):
            for (ax_, ay_), (bx_, by_) in zip(path, path[1:]):
                i0, j0 = XI[round(ax_, 1)], YI[round(ay_, 1)]
                i1, j1 = XI[round(bx_, 1)], YI[round(by_, 1)]
                if i0 == i1:
                    for jj in range(min(j0, j1), max(j0, j1)):
                        used[("v", i0, jj)] = used.get(("v", i0, jj), 0) + 1
                else:
                    for ii in range(min(i0, i1), max(i0, i1)):
                        used[("h", ii, j0)] = used.get(("h", ii, j0), 0) + 1

        def simplify(pts):
            if len(pts) < 3:
                return pts
            out = [pts[0]]
            for k in range(1, len(pts) - 1):
                ax, ay = out[-1]; bx, by = pts[k]; cx2, cy2 = pts[k + 1]
                # пропускаем коллинеарные
                if (ax == bx == cx2) or (ay == by == cy2):
                    continue
                out.append(pts[k])
            out.append(pts[-1])
            return out

        order = sorted(range(len(self.edges)),
                       key=lambda k: abs(self.edges[k]["pts"][0][0] - self.edges[k]["pts"][-1][0])
                       + abs(self.edges[k]["pts"][0][1] - self.edges[k]["pts"][-1][1]))
        for k in order:
            e = self.edges[k]
            sP, tP = e["pts"][0], e["pts"][-1]
            si = XI.get(round(sP[0], 1)); sj = YI.get(round(sP[1], 1))
            ti = XI.get(round(tP[0], 1)); tj = YI.get(round(tP[1], 1))
            if None in (si, sj, ti, tj):
                continue
            allowed = containing(sP) | containing(tP)
            path = astar(si, sj, ti, tj, allowed)
            if path and len(path) >= 2:
                mark_used(path)
                e["pts"] = simplify([sP] + path[1:-1] + [tP])

    def _merge(self, cx, cy):
        mid = self._u("mrg")
        self._node(mid, cx, cy, 6, 6, "point", "", "black", "")
        self.nodes[mid]["cx_pt"] = (cx, cy)
        return mid

    def _idof(self, n):
        for k, v in self.nodes.items():
            if v is n:
                return k
        return None

    # ── сборка + SVG ───────────────────────────────────────────────────────
    def build(self, roots, route=False, connectors=True):
        sw, shh = _node_size(f"Начало\n({self.fnum}){self.fn}", "box", "rounded")
        self._node("start", 0, shh / 2, sw, shh, "rounded", "rounded,filled",
                   "#ccffcc", f"Начало\n({self.fnum}){self.fn}")   # start — зелёный
        top, exitp, yend, _, _ = self._seq(roots, 0, shh + GAP, 0, None)
        if top:
            self._edge([self.S(self.nodes["start"]), top])
        if exitp is not None:
            ew, eh = _node_size("Конец", "box", "rounded")
            self._node("end", 0, yend + eh / 2, ew, eh, "rounded",
                       "rounded,filled", "#ffd0d0", "Конец")   # end — красный
            self._edge([exitp, self.N(self.nodes["end"])])
        self._sideport_exits()
        if route:
            self._route_all()
        if connectors:
            self._resolve_with_connectors()
        return self._svg()

    def _resolve_with_connectors(self):
        """ГОСТ-соединители вместо пересекающихся рёбер: жадно заменяем ребро,
        участвующее в наибольшем числе пересечений (при равенстве — самое длинное,
        т.е. обратное/возвратное), на пару кружков-соединителей (линии нет →
        пересекаться нечему). Повторяем, пока пересечения не исчезнут."""
        def _elen(e):
            return sum(abs(a[0] - b[0]) + abs(a[1] - b[1])
                       for a, b in zip(e["pts"], e["pts"][1:]))

        def _crossing_counts():
            S = []
            for ei, e in enumerate(self.edges):
                if e.get("connector"):
                    continue
                for a, b in zip(e["pts"], e["pts"][1:]):
                    S.append((a[0], a[1], b[0], b[1], ei))
            cnt = collections.Counter()
            n = len(S)
            for i in range(n):
                x1, y1, x2, y2, ei = S[i]
                for j in range(i + 1, n):
                    x3, y3, x4, y4, ej = S[j]
                    if ei == ej:
                        continue
                    dn = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
                    if abs(dn) < 1e-9:
                        continue
                    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / dn
                    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / dn
                    if 0.05 < t < 0.95 and 0.05 < u < 0.95:
                        cnt[ei] += 1; cnt[ej] += 1
            return cnt

        lbl = 0
        for _ in range(400):
            cnt = _crossing_counts()
            if not cnt:
                break
            worst = max(cnt, key=lambda ei: (cnt[ei], _elen(self.edges[ei])))
            lbl += 1
            self.edges[worst]["connector"] = lbl
        return lbl

    def _sideport_exits(self):
        """Правило: если ребро выходит из узла (порт S или N) и сразу идёт ВБОК
        (первый сегмент горизонтальный), переносим выход на свободный БОКОВОЙ порт
        (E/W) в сторону ребра — чтобы ребро не выходило из-под низа/верха узла.
        Применяется ко ВСЕМ узлам (кроме точек-merge)."""
        # индекс: центр-низ и центр-верх → узел
        bynode = []
        for nd in self.nodes.values():
            if nd["shape"] == "point":
                continue
            bynode.append(nd)
        for e in self.edges:
            if len(e["pts"]) < 2:
                continue
            (x0, y0), (x1, y1) = e["pts"][0], e["pts"][1]
            if abs(y1 - y0) > 1 or abs(x1 - x0) < 1:
                continue  # первый сегмент не горизонтальный
            for nd in bynode:
                cx, cy, hw, hh = nd["cx"], nd["cy"], nd["w"] / 2, nd["h"] / 2
                onS = abs(x0 - cx) < 2 and abs(y0 - (cy + hh)) < 2
                onN = abs(x0 - cx) < 2 and abs(y0 - (cy - hh)) < 2
                if onS or onN:
                    side = cx + hw if x1 > x0 else cx - hw   # E или W в сторону ребра
                    e["pts"][0] = (side, cy)
                    e["pts"][1] = (x1, cy)
                    break

    def _svg(self):
        pad = 30
        xs = []; ys = []
        for n in self.nodes.values():
            xs += [n["cx"] - n["w"] / 2, n["cx"] + n["w"] / 2]
            ys += [n["cy"] - n["h"] / 2, n["cy"] + n["h"] / 2]
        for e in self.edges:
            for (x, y) in e["pts"]:
                xs.append(x); ys.append(y)
        minx, miny = min(xs), min(ys)
        W = int(max(xs) - minx + 2 * pad); H = int(max(ys) - miny + 2 * pad)
        def X(v): return v - minx + pad
        def Y(v): return v - miny + pad
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="Courier New, monospace" font-size="12">',
            '<defs><marker id="ar" markerWidth="10" markerHeight="10" refX="8" refY="3" '
            'orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="black"/></marker></defs>',
            f'<rect width="{W}" height="{H}" fill="white"/>',
        ]
        # рёбра
        conn_marks = []
        for e in self.edges:
            pts = e["pts"]
            if e.get("connector"):
                # ГОСТ-соединитель: линии нет, у обоих концов кружок с номером
                num = e["connector"]
                def _circ(p, q):   # кружок у конца p, слегка смещён к q
                    dx, dy = q[0] - p[0], q[1] - p[1]
                    L = (dx * dx + dy * dy) ** 0.5 or 1
                    cxc, cyc = p[0] + dx / L * 16, p[1] + dy / L * 16
                    conn_marks.append(
                        f'<circle cx="{X(cxc):.1f}" cy="{Y(cyc):.1f}" r="11" '
                        f'fill="#fff3c4" stroke="black" stroke-width="1.5"/>'
                        f'<text x="{X(cxc):.1f}" y="{Y(cyc)+4:.1f}" text-anchor="middle" '
                        f'font-size="11">{num}</text>')
                _circ(pts[0], pts[1])
                _circ(pts[-1], pts[-2])
                continue
            d = "M " + " L ".join(f"{X(x):.1f},{Y(y):.1f}" for (x, y) in pts)
            mk = ' marker-end="url(#ar)"' if e["arrow"] else ""
            dash = ' stroke-dasharray="5,4"' if e["dashed"] else ""
            out.append(f'<path d="{d}" fill="none" stroke="{e["color"]}" '
                       f'stroke-width="1.5"{dash}{mk}/>')
            if e["label"]:
                lx, ly = X(pts[0][0]) + 5, Y(pts[0][1]) + 14
                out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#a00">'
                           f'{_svg_escape(e["label"])}</text>')
        out.extend(conn_marks)   # соединители — поверх
        # узлы
        for n in self.nodes.values():
            cx, cy, w, h = X(n["cx"]), Y(n["cy"]), n["w"], n["h"]
            x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            sh = n["shape"]; fc = n["fill"] or "white"
            if sh == "diamond":
                out.append(f'<polygon points="{cx},{y0} {x1},{cy} {cx},{y1} {x0},{cy}" '
                           f'fill="{fc}" stroke="black" stroke-width="1.5"/>')
            elif sh == "hexagon":
                hw = w / 5
                out.append(f'<polygon points="{x0+hw},{y0} {x1-hw},{y0} {x1},{cy} '
                           f'{x1-hw},{y1} {x0+hw},{y1} {x0},{cy}" fill="{fc}" '
                           f'stroke="black" stroke-width="1.5"/>')
            elif sh == "point":
                out.append(f'<circle cx="{cx}" cy="{cy}" r="3" fill="black"/>')
                continue
            elif sh == "circle":
                out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{w/2:.1f}" ry="{h/2:.1f}" '
                           f'fill="{fc}" stroke="black" stroke-width="1.5"/>')
            elif "rounded" in n["style"]:
                out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w}" height="{h}" '
                           f'rx="8" fill="{fc}" stroke="black" stroke-width="1.5"/>')
            else:
                out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w}" height="{h}" '
                           f'fill="{fc}" stroke="black" stroke-width="1.5"/>')
                if sh == "box2":
                    out.append(f'<line x1="{x0+10}" y1="{y0}" x2="{x0+10}" y2="{y1}" stroke="black"/>')
                    out.append(f'<line x1="{x1-10}" y1="{y0}" x2="{x1-10}" y2="{y1}" stroke="black"/>')
            lab = (n["label"] or "").replace("\\n", "\n")
            lines = lab.split("\n")
            sy = cy - (len(lines) - 1) * 7 + 4
            for i, ln in enumerate(lines):
                out.append(f'<text x="{cx:.1f}" y="{sy+i*14:.1f}" '
                           f'text-anchor="middle">{_svg_escape(ln)}</text>')
        out.append("</svg>")
        return "\n".join(out)
