"""grid_layout.py — клеточная раскладка, BOTTOM-UP (от самых вложенных).

Каждая конструкция строит БЛОК — самостоятельную матрицу ячеек с известным
размером (W×H в клетках), портами вход/выход и точками continue/break. Родитель
вставляет блоки детей как слоты ТОЧНОГО размера и ставит свои клетки вокруг —
поэтому полосы поддеревьев не пересекаются by construction. В конце логическая
сетка компактится в пиксели; рендер/метки/фигуры — из axis_layout. Есть экспорт
в HTML-таблицу (build_table): блоки цветом, пустые белые, пересечения красным.

Шаблоны (по согласованной концепции): if-1/if-2/guard; for/while — 2 шины
(возврат слева, выход справа); do-while — 1 шина (возврат); switch — 1 шина;
continue → шина возврата, break → шина выхода (ближайшего цикла).
"""
from viz.axis_layout import AxisLayout, GAP, _node_size

CHGAP = 46


class GridLayout(AxisLayout):
    _PALETTE = ["#cfe6ff", "#cdebc5", "#fff2b3", "#e6d0ff", "#ffd8a8", "#c5ecec",
                "#d9e8a0", "#d8c6f2", "#bfe3d4", "#f3d2e6", "#cfe0f7", "#e8e0b8"]

    def __init__(self, gen, func_name, func_num, func_index, var_index):
        super().__init__(gen, func_name, func_num, func_index, var_index)
        self.gnodes = {}   # id -> {w,h,shape,style,fill,label[,col,row]}
        self.gedges = []   # {pts:[ref...], label, arrow}; ref=('p',id,side)|('c',col,row)

    # ── узлы (атрибуты; позиция назначается при flatten) ─────────────────────
    def _attr(self, w, h, shape, style, fill, label, base=None):
        nid = base if (base and base not in self.gnodes) else self._u("n")
        self.gnodes[nid] = {"w": w, "h": h, "shape": shape, "style": style,
                            "fill": fill, "label": label}
        return nid

    def _node_of(self, stmt):
        st = stmt["stmt_type"]
        sh, style, fill = self._shape(st)
        gshape = {"box2": "box", "rounded": "box"}.get(sh, sh)
        lab = self._label(stmt)
        w, h = _node_size(lab, gshape, style)
        return self._attr(w, h, sh, style, fill, lab, base=self.gen._dot_id(self.fn, stmt["stmt_id"]))

    # ── БЛОК ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _blk():
        return {"N": {}, "E": [], "W": 1, "H": 1, "spine": 0,
                "entry": None, "exit": None, "cont": [], "brk": []}

    @staticmethod
    def _off(ref, dc, dr):
        return ("c", ref[1] + dc, ref[2] + dr) if ref and ref[0] == "c" else ref

    def _into(self, B, child, dc, dr):
        """Вставляет блок child в B со смещением (dc,dr)."""
        for nid, (c, r) in child["N"].items():
            B["N"][nid] = (c + dc, r + dr)
        for (pts, lab, ar) in child["E"]:
            B["E"].append(([self._off(p, dc, dr) for p in pts], lab, ar))
        B["cont"] += child["cont"]; B["brk"] += child["brk"]

    def _edge(self, B, pts, label=None, arrow=True):
        B["E"].append((pts, label, arrow))

    TERM = ("return", "throw", "exit")

    # ── ЛИСТЬЯ ───────────────────────────────────────────────────────────────
    def _b_leaf(self, nid):
        b = self._blk(); b["N"][nid] = (0, 0)
        b["entry"] = ("p", nid, "N"); b["exit"] = ("p", nid, "S")
        return b

    def _b_term(self, nid):
        b = self._blk()
        ew, eh = _node_size("Конец", "box", "rounded")
        eid = self._attr(ew, eh, "rounded", "rounded,filled", "#ffd0d0", "Конец")
        b["N"][nid] = (0, 0); b["N"][eid] = (1, 0)
        self._edge(b, [("p", nid, "E"), ("p", eid, "W")])
        b["W"] = 2; b["entry"] = ("p", nid, "N"); b["exit"] = None
        return b

    def _b_jump(self, nid, kind):
        b = self._blk(); b["N"][nid] = (0, 0)
        b["entry"] = ("p", nid, "N"); b["exit"] = None
        (b["cont"] if kind == "continue" else b["brk"]).append(nid)
        return b

    # ── ПОСЛЕДОВАТЕЛЬНОСТЬ (вертикальный стек, выровнено по спине) ────────────
    def _b_seq(self, stmts, loop):
        kids = [self._b_stmt(s, loop) for s in
                sorted(stmts, key=lambda s: int(s.get("line_start", 0) or 0))]
        if not kids:
            b = self._blk(); b["W"] = 0; b["H"] = 0; return b
        leftmax = max(k["spine"] for k in kids)
        rightmax = max(k["W"] - 1 - k["spine"] for k in kids)
        spine = leftmax; W = leftmax + 1 + rightmax
        B = self._blk(); B["W"] = W; B["spine"] = spine
        row = 0; prev = None
        for k in kids:
            dc = spine - k["spine"]
            self._into(B, k, dc, row)
            ent = self._off(k["entry"], dc, row); ex = self._off(k["exit"], dc, row)
            if B["entry"] is None:
                B["entry"] = ent
            if prev is not None and ent is not None:
                self._edge(B, [prev, ent])
            prev = ex if ex is not None else prev if False else ex
            row += k["H"]
        B["H"] = row; B["exit"] = prev
        return B

    def _b_stmt(self, s, loop):
        st = s["stmt_type"]
        nid = self._node_of(s)
        if st in self.TERM:
            return self._b_term(nid)
        if st in ("continue", "break"):
            return self._b_jump(nid, st)
        if st == "goto":
            b = self._b_leaf(nid); b["exit"] = None; return b
        if st in ("while", "for", "do"):
            return self._b_loop(s, nid)
        if st == "switch":
            return self._b_switch(s, nid, loop)
        if st in ("if", "try"):
            return self._b_branch(s, nid, loop)
        return self._b_leaf(nid)

    def _split(self, s):
        ch = s.get("children", [])
        if s["stmt_type"] == "try":
            el = [c for c in ch if int(c.get("in_catch", 0) or 0)]
            th = [c for c in ch if not int(c.get("in_catch", 0) or 0)]
            return th, el
        el_line = int(s.get("else_line", 0) or 0)
        if el_line:
            th = [c for c in ch if int(c.get("line_start", 0) or 0) < el_line]
            el = [c for c in ch if int(c.get("line_start", 0) or 0) >= el_line]
            return th, el
        return list(ch), []

    # ── ВЕТВЛЕНИЕ (с зеркалированием: continue→влево, break→вправо) ───────────
    def _jcount(self, children, in_switch=False):
        """(#continue, #break), относящиеся к ТЕКУЩЕМУ циклу. break внутри switch
        принадлежит switch (не цикл) → не считаем; вложенные циклы пропускаем;
        continue всегда относится к циклу (switch его не перехватывает)."""
        nc = nb = 0
        for c in children:
            st = c["stmt_type"]
            if st == "break":
                if not in_switch:
                    nb += 1
            elif st == "continue":
                nc += 1
            elif st in ("while", "for", "do"):
                continue
            elif st == "switch":
                a, _ = self._jcount(c.get("children", []), in_switch=True)
                nc += a
            else:
                a, b = self._jcount(c.get("children", []), in_switch)
                nc += a; nb += b
        return nc, nb

    def _b_branch(self, s, nid, loop):
        th, el = self._split(s)
        if el:
            T = self._b_seq(th, loop); E = self._b_seq(el, loop)
            # сторона по БАЛАНСУ прыжков цикла: continue тянет ВЛЕВО (к шине
            # возврата), break — ВПРАВО (к шине выхода); break внутри switch/
            # вложенного цикла не учитывается; при равенстве — бо́льшая ветвь влево.
            tc, tb = self._jcount(th); ec, eb = self._jcount(el)
            ts, es = tc - tb, ec - eb
            then_left = ts > es if ts != es else self._count(th) >= self._count(el)
            # leftblk/rightblk: какая ветвь слева/справа + порт/метка
            if then_left:
                Lb, Rb, Llab, Rlab, Lport, Rport = T, E, "да", "нет", "W", "E"
            else:
                Lb, Rb, Llab, Rlab, Lport, Rport = E, T, "нет", "да", "W", "E"
            spine = Lb["W"]; W = Lb["W"] + 1 + Rb["W"]
            B = self._blk(); B["W"] = W; B["spine"] = spine
            B["N"][nid] = (spine, 0)
            self._into(B, Lb, 0, 1); lent = self._off(Lb["entry"], 0, 1); lex = self._off(Lb["exit"], 0, 1)
            self._into(B, Rb, spine + 1, 1); rent = self._off(Rb["entry"], spine + 1, 1); rex = self._off(Rb["exit"], spine + 1, 1)
            if lent: self._edge(B, [("p", nid, Lport), lent], Llab)
            if rent: self._edge(B, [("p", nid, Rport), rent], Rlab)
            mrow = 1 + max(Lb["H"], Rb["H"])
            mid = self._attr(6, 6, "point", "", "black", "")
            B["N"][mid] = (spine, mrow)
            if lex: self._edge(B, [lex, ("p", mid, "N")], arrow=False)
            if rex: self._edge(B, [rex, ("p", mid, "N")], arrow=False)
            B["H"] = mrow + 1; B["entry"] = ("p", nid, "N"); B["exit"] = ("p", mid, "S")
            return B
        else:
            # одноветвевой: break-доминантная ветвь → ВПРАВО (к выходу), иначе ВЛЕВО
            # (continue-доминантная/нейтральная — влево); break в switch не считается.
            tc, tb = self._jcount(th)
            to_right = tb > tc
            T = self._b_seq(th, loop)
            if to_right:
                spine = 0; W = 1 + T["W"]; dc = 1; port = "E"
            else:
                spine = T["W"]; W = T["W"] + 1; dc = 0; port = "W"
            B = self._blk(); B["W"] = W; B["spine"] = spine
            B["N"][nid] = (spine, 0)
            self._into(B, T, dc, 1); tent = self._off(T["entry"], dc, 1); tex = self._off(T["exit"], dc, 1)
            if tent: self._edge(B, [("p", nid, port), tent], "да")
            B["entry"] = ("p", nid, "N")
            if tex is not None:
                mrow = 1 + max(T["H"], 1)
                mid = self._attr(6, 6, "point", "", "black", "")
                B["N"][mid] = (spine, mrow)
                self._edge(B, [("p", nid, "S"), ("p", mid, "N")], "нет", arrow=False)
                self._edge(B, [tex, ("p", mid, "N")], arrow=False)
                B["H"] = mrow + 1; B["exit"] = ("p", mid, "S")
            else:  # guard — без merge
                B["H"] = max(1 + T["H"], 1); B["exit"] = ("p", nid, "S")
            return B

    # ── ЦИКЛ ─────────────────────────────────────────────────────────────────
    def _b_loop(self, s, nid):
        myloop = {}
        Bd = self._b_seq(list(s.get("children", [])), myloop)
        W = 1 + Bd["W"] + 1
        spine = 1 + Bd["spine"]; retcol = 0; exitcol = W - 1
        B = self._blk(); B["W"] = W; B["spine"] = spine
        B["N"][nid] = (spine, 0)
        self._into(B, Bd, 1, 1)
        bent = self._off(Bd["entry"], 1, 1); bex = self._off(Bd["exit"], 1, 1)
        if bent: self._edge(B, [("p", nid, "S"), bent], "да")
        brow = 1 + Bd["H"]
        # возврат: тело-конец + continue → шина возврата (retcol) → W заголовка
        joins = []
        if bex is not None: joins.append(bex)
        for cid in Bd["cont"]:
            joins.append(("p", cid, "W"))
        if joins:
            for j in joins:
                jy = self._refrow(B, j)
                self._edge(B, [j, ("c", retcol, jy)], arrow=False)
            self._edge(B, [("c", retcol, brow), ("c", retcol, 0), ("p", nid, "W")], "N")
        # выход: нет + break → шина выхода (exitcol) → строка после цикла
        prow = brow + 1
        self._edge(B, [("p", nid, "E"), ("c", exitcol, 0), ("c", exitcol, prow),
                       ("c", spine, prow)], "нет")
        for bid in Bd["brk"]:
            by = self._refrow(B, ("p", bid, "E"))
            self._edge(B, [("p", bid, "E"), ("c", exitcol, by), ("c", exitcol, prow)], arrow=False)
        B["H"] = prow + 1; B["entry"] = ("p", nid, "N"); B["exit"] = ("c", spine, prow)
        # continue/break этого цикла ПОГЛОЩЕНЫ (не пробрасываем выше)
        B["cont"] = []; B["brk"] = []
        return B

    # ── SWITCH (тело вниз по спине; break → выход switch; continue → в цикл) ───
    def _b_switch(self, s, nid, loop):
        Bd = self._b_seq(list(s.get("children", [])), loop)
        spine = Bd["spine"]
        W = max(Bd["W"] + 1, spine + 2); exitcol = W - 1
        B = self._blk(); B["W"] = W; B["spine"] = spine
        B["N"][nid] = (spine, 0)
        self._into(B, Bd, 0, 1)
        bent = self._off(Bd["entry"], 0, 1); bex = self._off(Bd["exit"], 0, 1)
        if bent: self._edge(B, [("p", nid, "S"), bent])
        erow = 1 + Bd["H"]
        mid = self._attr(6, 6, "point", "", "black", "")
        B["N"][mid] = (spine, erow)
        if bex is not None:
            self._edge(B, [bex, ("p", mid, "N")], arrow=False)
        # break = выход ИЗ switch → шина выхода (справа) → merge снизу (поглощаем)
        for bid in Bd["brk"]:
            by = B["N"][bid][1]
            self._edge(B, [("p", bid, "E"), ("c", exitcol, by), ("c", exitcol, erow),
                           ("p", mid, "N")], arrow=False)
        B["H"] = erow + 1; B["entry"] = ("p", nid, "N"); B["exit"] = ("p", mid, "S")
        B["cont"] = Bd["cont"]; B["brk"] = []
        return B

    def _refrow(self, B, ref):
        if ref[0] == "c":
            return ref[2]
        return B["N"][ref[1]][1]

    # ── СБОРКА КОРНЯ ─────────────────────────────────────────────────────────
    def _build_root(self, roots):
        body = self._b_seq(roots, None)
        sw, shh = _node_size(f"Начало\n({self.fnum}){self.fn}", "box", "rounded")
        sid = self._attr(sw, shh, "rounded", "rounded,filled", "#ccffcc",
                         f"Начало\n({self.fnum}){self.fn}", base="start")
        spine = body["spine"]; W = max(body["W"], 1)
        B = self._blk(); B["W"] = W; B["spine"] = spine
        B["N"][sid] = (spine, 0)
        self._into(B, body, 0, 1)
        bent = self._off(body["entry"], 0, 1); bex = self._off(body["exit"], 0, 1)
        if bent: self._edge(B, [("p", sid, "S"), bent])
        H = 1 + body["H"]
        if bex is not None:
            ew, eh = _node_size("Конец", "box", "rounded")
            eid = self._attr(ew, eh, "rounded", "rounded,filled", "#ffd0d0", "Конец", base="end")
            B["N"][eid] = (spine, H)
            self._edge(B, [bex, ("p", eid, "N")]); H += 1
        B["H"] = H
        # flatten → позиции в gnodes, рёбра в gedges
        for nid, (c, r) in B["N"].items():
            self.gnodes[nid]["col"] = c; self.gnodes[nid]["row"] = r
        self.gedges = [{"pts": pts, "label": lab, "arrow": ar} for (pts, lab, ar) in B["E"]]

    # ── компакция логической сетки → пиксели ─────────────────────────────────
    def _compact(self):
        cols = set(); rows = set()
        for v in self.gnodes.values():
            if "col" in v:
                cols.add(v["col"]); rows.add(v["row"])
        for e in self.gedges:
            for ref in e["pts"]:
                if ref[0] == "c":
                    cols.add(ref[1]); rows.add(ref[2])
        scols = sorted(cols); srows = sorted(rows)
        wcol = {c: 0 for c in scols}; hrow = {r: 0 for r in srows}
        for v in self.gnodes.values():
            if "col" in v:
                wcol[v["col"]] = max(wcol[v["col"]], v["w"])
                hrow[v["row"]] = max(hrow[v["row"]], v["h"])
        for c in scols:
            if wcol[c] == 0: wcol[c] = CHGAP
        for r in srows:
            if hrow[r] == 0: hrow[r] = CHGAP
        X = {}; acc = 0
        for c in scols:
            X[c] = acc + wcol[c] / 2; acc += wcol[c] + 30
        Y = {}; acc = 0
        for r in srows:
            Y[r] = acc + hrow[r] / 2; acc += hrow[r] + 24
        self._X = X; self._Y = Y; self._scols = scols; self._srows = srows

        def xof(col):
            if col in X: return X[col]
            lo = max([c for c in scols if c < col], default=scols[0])
            hi = min([c for c in scols if c > col], default=scols[-1])
            return X[lo] if hi == lo else X[lo] + (X[hi] - X[lo]) * (col - lo) / (hi - lo)

        def yof(r):
            if r in Y: return Y[r]
            lo = max([x for x in srows if x < r], default=srows[0])
            hi = min([x for x in srows if x > r], default=srows[-1])
            return Y[lo] if hi == lo else Y[lo] + (Y[hi] - Y[lo]) * (r - lo) / (hi - lo)

        self.nodes = {}
        for nid, v in self.gnodes.items():
            if "col" not in v:
                continue
            self.nodes[nid] = {"cx": xof(v["col"]), "cy": yof(v["row"]), "w": v["w"],
                               "h": v["h"], "shape": v["shape"], "style": v["style"],
                               "fill": v["fill"], "label": v["label"]}
            if v["shape"] == "point":
                self.nodes[nid]["cx_pt"] = (xof(v["col"]), yof(v["row"]))

        def resolve(ref):
            if ref[0] == "p":
                n = self.nodes[ref[1]]
                return {"N": self.N, "S": self.S, "W": self.W, "E": self.E}[ref[2]](n)
            return (xof(ref[1]), yof(ref[2]))

        self.edges = []
        for e in self.gedges:
            pts = [resolve(r) for r in e["pts"]]
            opts = [pts[0]]
            for q in pts[1:]:
                p = opts[-1]
                if abs(p[0] - q[0]) > 1 and abs(p[1] - q[1]) > 1:
                    opts.append((q[0], p[1]))
                opts.append(q)
            self.edges.append({"pts": opts, "label": e["label"], "arrow": e["arrow"],
                               "color": "black", "dashed": False})

    def build(self, roots):
        self._build_root(roots)
        self._compact()
        return self._svg()

    # ── ЭКСПОРТ В ТАБЛИЦУ (HTML) ─────────────────────────────────────────────
    def build_table(self, roots, cellpx=18):
        self._build_root(roots); self._compact()
        order = [nid for nid in self.gnodes if "col" in self.gnodes[nid]]
        blockcol = {nid: self._PALETTE[i % len(self._PALETTE)] for i, nid in enumerate(order)}

        def rc(ref):
            if ref[0] == "p":
                v = self.gnodes[ref[1]]; return (v["col"], v["row"])
            return (ref[1], ref[2])

        def blk_of(e):
            for ref in e["pts"]:
                if ref[0] == "p":
                    return ref[1]
            return None

        ecells = {}
        for e in self.gedges:
            pts = [rc(r) for r in e["pts"]]
            opath = [pts[0]]
            for q in pts[1:]:
                p = opath[-1]
                if p[0] != q[0] and p[1] != q[1]:
                    opath.append((q[0], p[1]))
                opath.append(q)
            blk = blk_of(e)
            for (a, b) in zip(opath, opath[1:]):
                if a[1] == b[1]:
                    for c in range(int(min(a[0], b[0])), int(max(a[0], b[0])) + 1):
                        d = ecells.setdefault((c, a[1]), {"H": 0, "V": 0, "blk": blk}); d["H"] = 1
                elif a[0] == b[0]:
                    for r in range(int(min(a[1], b[1])), int(max(a[1], b[1])) + 1):
                        d = ecells.setdefault((a[0], r), {"H": 0, "V": 0, "blk": blk}); d["V"] = 1

        nodecell = {(self.gnodes[n]["col"], self.gnodes[n]["row"]): n for n in order}
        segs = []
        for e in self.edges:
            for a, b in zip(e["pts"], e["pts"][1:]):
                segs.append((a[0], a[1], b[0], b[1]))
        redcells = set(); ncross = 0
        for i in range(len(segs)):
            x1, y1, x2, y2 = segs[i]
            for j in range(i + 1, len(segs)):
                x3, y3, x4, y4 = segs[j]
                dn = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
                if abs(dn) < 1e-9: continue
                t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / dn
                u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / dn
                if 0.05 < t < 0.95 and 0.05 < u < 0.95:
                    ncross += 1
                    px, py = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
                    col = min(self._scols, key=lambda c: abs(self._X[c] - px))
                    row = min(self._srows, key=lambda r: abs(self._Y[r] - py))
                    redcells.add((col, row))

        cols = sorted({c for c, r in nodecell} | {c for c, r in ecells} | {c for c, r in redcells})
        rows = sorted({r for c, r in nodecell} | {r for c, r in ecells} | {r for c, r in redcells})

        def glyph(d):
            return "┼" if d["H"] and d["V"] else "─" if d["H"] else "│" if d["V"] else ""

        def short(nid):
            v = self.gnodes[nid]; lab = (v["label"] or "").replace("\n", " ")
            sym = {"diamond": "◇", "hexagon": "⬡", "point": "●", "circle": "◯",
                   "rounded": "▭", "box2": "▢"}.get(v["shape"], "▢")
            return (sym + " " + lab[:12]).replace("<", "&lt;").replace(">", "&gt;")

        out = ['<!doctype html><meta charset="utf-8"><style>',
               f'table{{border-collapse:collapse}}td{{width:{cellpx}px;height:{cellpx}px;'
               f'border:1px solid #eee;font:9px monospace;text-align:center;overflow:hidden;'
               f'white-space:nowrap;padding:0;max-width:{cellpx}px}}</style>',
               f'<h3>{self.fn} — bottom-up клетки ({len(rows)}×{len(cols)}), '
               f'пересечений: <b>{ncross}</b></h3><table>']
        for r in rows:
            out.append("<tr>")
            for c in cols:
                cell = (c, r)
                if cell in redcells:
                    g = short(nodecell[cell]) if cell in nodecell else (glyph(ecells[cell]) if cell in ecells else "✕")
                    out.append(f'<td style="background:#ff5555;color:#fff">{g or "✕"}</td>')
                elif cell in nodecell:
                    nid = nodecell[cell]; full = (self.gnodes[nid]["label"] or "").replace('"', "'")
                    out.append(f'<td style="background:{blockcol[nid]}" title="{full}">{short(nid)}</td>')
                elif cell in ecells:
                    d = ecells[cell]; bc = blockcol.get(d["blk"], "#cccccc")
                    out.append(f'<td style="background:{bc}55">{glyph(d)}</td>')
                else:
                    out.append("<td></td>")
            out.append("</tr>")
        out.append("</table>")
        return "\n".join(out)
