"""
drakon_generator.py — DRAKON-style SVG flowchart generator.

Layout rules (DRAKON Primitive form):
  YES / да  branch always goes DOWN  (main spine)
  NO  / нет branch always goes RIGHT (parallel column, merges back)
  Loop back-edges run on the LEFT side
  All connectors are orthogonal (no diagonal lines)

No external dependencies — pure Python SVG output.
"""

from __future__ import annotations
import re
import math
import zipfile
import html as _html
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ── Layout constants ───────────────────────────────────────────────────────────
_V_GAP    = 38      # vertical gap between nodes
_H_GAP    = 70      # horizontal gap between main and alt column
_BACK_W   = 56      # left margin for loop-back connector
_MARGIN   = 44      # outer margin
_MAX_CH   = 52      # max chars before label truncation
_WRAP_W   = 26      # wrap at this many chars per line

_ACT_MIN_W = 160;  _ACT_MAX_W = 280;  _ACT_MIN_H = 40;  _ACT_MAX_H = 100
_COND_MIN_W = 160; _COND_MAX_W = 300; _COND_H_BASE = 64
_LOOP_MIN_W = 160; _LOOP_MAX_W = 280; _LOOP_H_BASE = 48
_CAP_H  = 42   # start/end capsule height
_CAP_W  = 180  # start/end capsule width

_PAD_X   = 18
_PAD_Y   = 10
_CHAR_W  = 7.2
_LINE_H  = 16

# ── Colour palette ─────────────────────────────────────────────────────────────
_BG      = "#f0f4f8"
_C_ACT   = "#ffffff"
_C_COND  = "#fef3c7"
_C_LOOP  = "#bfdbfe"
_C_CALL  = "#a5f3fc"
_C_IO    = "#e9d5ff"
_C_RET   = "#fecaca"
_C_CAP   = "#bbf7d0"
_C_STUB  = "#e2e8f0"
_C_CATCH = "#fde68a"
_BORDER  = "#1e3a5f"
_CLABEL  = "#1e3a5f"
_YES_C   = "#166534"
_NO_C    = "#991b1b"
_CONN    = "#6b7280"   # loop-back / merge connector colour


# ── Helpers ────────────────────────────────────────────────────────────────────

def _wrap(text: str, width: int = _WRAP_W) -> List[str]:
    """Word-wrap text to at most `width` chars per line."""
    lines: List[str] = []
    for para in text.split("\n"):
        words = para.split()
        cur = ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > width:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip() if cur else w
        if cur:
            lines.append(cur)
        if not words:
            lines.append("")
    return lines or [""]


def _dims(ntype: str, label: str) -> Tuple[float, float]:
    """Compute (width, height) for a node given its visual type and label."""
    lines = _wrap(label)
    cw = max((len(l) for l in lines), default=4) * _CHAR_W
    ch = len(lines) * _LINE_H
    if ntype == "condition":
        # Diamond: the inscribed rectangle must fit the text → scale up
        w = max(_COND_MIN_W, min(_COND_MAX_W, cw * 1.45 + 2 * _PAD_X))
        h = max(_COND_H_BASE, ch + 2 * _PAD_Y + 16)
    elif ntype == "loop":
        # Hexagon (pointed sides): extra padding for pointy left/right
        w = max(_LOOP_MIN_W, min(_LOOP_MAX_W, cw + 2 * _PAD_X + 24))
        h = max(_LOOP_H_BASE, ch + 2 * _PAD_Y)
    elif ntype in ("start", "end"):
        w = _CAP_W
        h = _CAP_H
    else:
        w = max(_ACT_MIN_W, min(_ACT_MAX_W, cw + 2 * _PAD_X))
        h = max(_ACT_MIN_H, min(_ACT_MAX_H, ch + 2 * _PAD_Y))
    return w, h


def _ntype(st: str) -> str:
    if st in ("if", "try"):           return "condition"
    if st in ("while", "for", "do"):  return "loop"
    if st in ("return", "throw"):     return "return"
    if st == "call":                  return "call"
    if st == "io":                    return "io"
    if st in ("exit", "goto"):        return "return"
    if st == "code":                  return "stub"
    if st in ("break", "continue"):   return "return"
    return "action"


def _fill(nt: str) -> str:
    return {
        "condition": _C_COND,
        "loop":      _C_LOOP,
        "call":      _C_CALL,
        "io":        _C_IO,
        "return":    _C_RET,
        "start":     _C_CAP,
        "end":       _C_CAP,
        "stub":      _C_STUB,
        "catch":     _C_CATCH,
    }.get(nt, _C_ACT)


def _escape(s: str) -> str:
    return _html.escape(str(s), quote=True)


# ── Placed-node / placed-edge records ─────────────────────────────────────────

@dataclass
class _PN:
    nid:   str
    x:     float
    y:     float
    w:     float
    h:     float
    ntype: str
    label: str


@dataclass
class _PE:
    src:    str
    dst:    str
    label:  str  = ""
    lcolor: str  = _CLABEL
    # route variants:
    #   "V"  : straight vertical  src-bottom → dst-top
    #   "RD" : src-east → go right to col_x → down → dst-top   (NO branch enters alt col)
    #   "LU" : dst-top  → go left → up → src-east              (merge from alt col → main)
    #   "LB" : loop-back: src-bottom → down-ext → left-rail → up → loop-west
    route:  str  = "V"
    # extra routing params (set where needed)
    col_x:    float = 0.0   # RD / LU: x of the right column
    rail_x:   float = 0.0   # LB: x of the left rail
    src_y:    float = 0.0   # override departure y (for merge routing)
    no_marker: bool = False  # LB from continue: share rail visually but no arrowhead


# ── Layout engine ──────────────────────────────────────────────────────────────

class _Layouter:
    def __init__(self, gen: "DrakonGenerator", fi: dict, vi: dict):
        self.gen = gen
        self.fi  = fi
        self.vi  = vi
        self.simplified = gen.simplified
        self.placed:       Dict[str, _PN]    = {}
        self.edges:        List[_PE]         = []
        self._uid_n:       List[int]         = [0]
        self._break_rails: Dict[str, float]  = {}  # loop_exit_id → no_skip_x
        self._back_rails:  Dict[str, float]  = {}  # loop_nid → rail_x

    # ── uid generator ──────────────────────────────────────────────────────────
    def _uid(self, prefix: str = "__") -> str:
        self._uid_n[0] += 1
        return f"{prefix}{self._uid_n[0]}"

    # ── label helpers ──────────────────────────────────────────────────────────
    def _label(self, node: dict) -> str:
        st  = node["stmt_type"]
        raw = node["stmt_label"]
        if not node.get("_simplified") and st in ("if", "while", "for", "do", "return", "try"):
            raw = self.gen._extract_condition_text(node["stmt_id"], st, raw)
        bnum = node.get("branch_num")
        if bnum and st in ("if", "while", "for", "do", "try"):
            raw = f"#{bnum}\n{raw}"
        if node.get("_simplified") or st in ("call", "io", "process", "throw", "exit", "return"):
            label = raw
        else:
            label = self.gen._format_label(raw, self.fi, self.vi)
        if len(label) > _MAX_CH:
            label = label[:_MAX_CH - 3] + "..."
        return label

    # ── measure helpers ────────────────────────────────────────────────────────
    def _mw_col(self, nodes: list) -> float:
        """Max width of main-column nodes (no bypass / alt-column space)."""
        if not nodes:
            return _ACT_MIN_W
        maxw = 0.0
        for n in nodes:
            st  = n["stmt_type"]
            lab = self._label(n)
            nw, _ = _dims(_ntype(st), lab)
            ch = n["children"]
            if st == "if":
                el      = n.get("else_line", 0)
                then_ch = [c for c in ch if not el or c["line_start"] < el]
                nw = max(nw, self._mw_col(then_ch))
            elif st in ("while", "for", "do"):
                nw = max(nw, self._mw_col(ch))
            elif st == "try":
                try_ch = [c for c in ch if not int(c.get("in_catch", "0") or 0)]
                nw = max(nw, self._mw_col(try_ch))
            maxw = max(maxw, nw)
        return maxw

    def _mw_right(self, nodes: list) -> float:
        """Max right extension from cx including all nested NO-bypass rails."""
        if not nodes:
            return _ACT_MIN_W / 2
        maxr = _ACT_MIN_W / 2
        for n in nodes:
            maxr = max(maxr, self._mw_node_right(n))
        return maxr

    def _mw_node_right(self, node: dict) -> float:
        """Right extension of one node from its column cx, recursing into children.

        Ensures each level's bypass rail is placed outside all inner bypass rails,
        so no nested NO-edge can cross an outer NO-edge.
        """
        st   = node["stmt_type"]
        lab  = self._label(node)
        nw, _ = _dims(_ntype(st), lab)
        half = nw / 2
        ch   = node["children"]

        if st == "if":
            el      = node.get("else_line", 0)
            then_ch = [c for c in ch if not el or c["line_start"] < el]
            else_ch = [c for c in ch if el and c["line_start"] >= el]
            then_r  = self._mw_right(then_ch) if then_ch else half
            if else_ch:
                else_col     = self._mw_col(else_ch)
                else_cx_off  = max(half, then_r) + _H_GAP + else_col / 2
                else_inner_r = self._mw_right(else_ch)
                return max(then_r, else_cx_off + else_inner_r)
            return max(half, then_r) + _H_GAP  # guard: bypass rail outside then-branch

        elif st in ("while", "for", "do"):
            body_r = self._mw_right(ch) if ch else half
            return max(half, body_r) + _H_GAP + 10  # loop NO-bypass outside body

        elif st == "try":
            try_ch   = [c for c in ch if not int(c.get("in_catch", "0") or 0)]
            catch_ch = [c for c in ch if int(c.get("in_catch", "0") or 0)]
            try_r    = self._mw_right(try_ch) if try_ch else half
            if catch_ch:
                catch_col    = self._mw_col(catch_ch)
                catch_cx_off = max(half, try_r) + _H_GAP + catch_col / 2
                return max(try_r, catch_cx_off + self._mw_right(catch_ch))
            return half

        return half  # leaf nodes

    def _mw_back_ext(self, nodes: list) -> float:
        """Leftward extent from cx needed for loop back-rails in subtree.

        For each loop in the subtree the back-rail sits at
        cx - (max(lw/2, inner_back_ext) + _BACK_W).
        Recursing ensures outer rails are placed further left than inner ones.
        """
        if not nodes:
            return 0.0
        ext = 0.0
        for n in nodes:
            st  = n["stmt_type"]
            lab = self._label(n)
            nw, _ = _dims(_ntype(st), lab)
            ch  = n["children"]
            if st in ("while", "for", "do"):
                body_ext = self._mw_back_ext(sorted(ch, key=lambda c: c["line_start"]))
                ext = max(ext, max(nw / 2, body_ext) + _BACK_W)
            elif st == "if":
                el      = n.get("else_line", 0)
                then_ch = [c for c in ch if not el or c["line_start"] < el]
                else_ch = [c for c in ch if el and c["line_start"] >= el]
                ext = max(ext, self._mw_back_ext(then_ch), self._mw_back_ext(else_ch))
            elif st == "try":
                try_ch   = [c for c in ch if not int(c.get("in_catch", "0") or 0)]
                catch_ch = [c for c in ch if int(c.get("in_catch", "0") or 0)]
                ext = max(ext, self._mw_back_ext(try_ch), self._mw_back_ext(catch_ch))
        return ext

    # ── edge helpers ───────────────────────────────────────────────────────────
    def _cv(self, src: str, dst: str, label: str = "", lcolor: str = _CLABEL):
        self.edges.append(_PE(src=src, dst=dst, label=label, lcolor=lcolor, route="V"))

    def _crd(self, src: str, dst: str, col_x: float, label: str, lcolor: str):
        """NO edge: src-east → col_x (right column) → dst-top."""
        self.edges.append(_PE(src=src, dst=dst, label=label, lcolor=lcolor,
                              route="RD", col_x=col_x))

    def _clu(self, src: str, dst: str, col_x: float, main_cx: float):
        """Merge edge: src-bottom → down → left back to main col → dst-top."""
        self.edges.append(_PE(src=src, dst=dst, label="", lcolor=_CONN,
                              route="LU", col_x=col_x))

    def _clb(self, src: str, dst: str, rail_x: float):
        """Loop-back edge: src-bottom → down → rail_x (left) → up → dst-west."""
        self.edges.append(_PE(src=src, dst=dst, label="", lcolor=_CONN,
                              route="LB", rail_x=rail_x))

    # ── terminal checks ────────────────────────────────────────────────────────
    def _is_terminal(self, nid: str) -> bool:
        """True if nid is any control-flow terminal (return/break/continue/…).
        Used to suppress merge edges in _layout_if branches."""
        pn = self.placed.get(nid)
        return pn is not None and pn.ntype == "return"

    def _is_loop_ctrl(self, nid: str) -> bool:
        """True if nid is a loop-scope terminator (break or continue).
        These jump to loop exit/back — subsequent nodes in the same block
        are unreachable and must NOT be connected to this node."""
        pn = self.placed.get(nid)
        return pn is not None and pn.ntype == "return" and pn.label in ("break", "continue")

    # ── port helpers ───────────────────────────────────────────────────────────
    def _south(self, nid: str) -> Tuple[float, float]:
        p = self.placed[nid]
        if p.ntype == "condition":
            return (p.x + p.w / 2, p.y + p.h)
        if p.ntype == "loop":
            return (p.x + p.w / 2, p.y + p.h)
        return (p.x + p.w / 2, p.y + p.h)

    def _north(self, nid: str) -> Tuple[float, float]:
        p = self.placed[nid]
        return (p.x + p.w / 2, p.y)

    def _east(self, nid: str) -> Tuple[float, float]:
        p = self.placed[nid]
        if p.ntype == "condition":
            return (p.x + p.w, p.y + p.h / 2)   # right diamond vertex
        if p.ntype == "loop":
            return (p.x + p.w, p.y + p.h / 2)   # right hexagon point
        return (p.x + p.w, p.y + p.h / 2)

    def _west(self, nid: str) -> Tuple[float, float]:
        p = self.placed[nid]
        if p.ntype == "loop":
            return (p.x, p.y + p.h / 2)          # left hexagon point
        return (p.x, p.y + p.h / 2)

    # ── place a merge point (invisible dot) ───────────────────────────────────
    def _merge(self, cx: float, y: float) -> str:
        mid = self._uid("mrg")
        self.placed[mid] = _PN(nid=mid, x=cx - 3, y=y, w=6, h=6,
                               ntype="merge", label="")
        return mid

    # ── layout sequence of nodes ───────────────────────────────────────────────
    def layout_seq(self, nodes: list, cx: float, y: float,
                   exit_id: Optional[str],
                   loop_back_id: Optional[str] = None,
                   loop_exit_id: Optional[str] = None,
                   prev_id: Optional[str] = None) -> Tuple[Optional[str], float]:
        """
        Layout a list of nodes vertically centred at cx starting at y.
        Returns (last_placed_id, next_y_after_last_node).
        """
        for node in sorted(nodes, key=lambda n: n["line_start"]):
            st = node["stmt_type"]
            if st in ("case", "default"):
                # Метки границ ветвей switch, не собственные блоки — см.
                # комментарий в _layout_leaf.
                continue
            if st == "if":
                prev_id, y = self._layout_if(node, cx, y, exit_id, loop_back_id,
                                             loop_exit_id, prev_id)
            elif st in ("while", "for", "do"):
                prev_id, y = self._layout_loop(node, cx, y, exit_id, loop_back_id,
                                               loop_exit_id, prev_id)
            elif st == "try":
                prev_id, y = self._layout_try(node, cx, y, exit_id, loop_back_id,
                                              loop_exit_id, prev_id)
            else:
                prev_id, y = self._layout_leaf(node, cx, y, prev_id,
                                               loop_back_id, loop_exit_id, exit_id)
                # Any terminator (break/continue/return/throw/exit/goto) jumps
                # elsewhere — subsequent nodes are unreachable, don't connect.
                if prev_id and self._is_terminal(prev_id):
                    prev_id = None
        return prev_id, y

    # ── leaf node ──────────────────────────────────────────────────────────────
    def _layout_leaf(self, node: dict, cx: float, y: float,
                     prev_id: Optional[str],
                     loop_back_id: Optional[str],
                     loop_exit_id: Optional[str],
                     exit_id: Optional[str]) -> Tuple[str, float]:
        st  = node["stmt_type"]
        nt  = _ntype(st)
        lab = self._label(node)
        w, h = _dims(nt, lab)
        x = cx - w / 2
        pn = _PN(nid=node["stmt_id"], x=x, y=y, w=w, h=h, ntype=nt, label=lab)
        self.placed[node["stmt_id"]] = pn
        if prev_id and prev_id in self.placed:
            self._cv(prev_id, node["stmt_id"])

        nid = node["stmt_id"]
        end_y = y + h + _V_GAP

        # Handle control-flow terminators
        if st in ("return", "throw", "exit"):
            if exit_id and exit_id in self.placed:
                self._cv(nid, exit_id)
        elif st == "break":
            target = loop_exit_id  # break exits innermost loop, not the function
            if target and target in self.placed:
                skip_x = self._break_rails.get(target)
                if skip_x is not None:
                    self.edges.append(_PE(src=nid, dst=target, label="",
                                          lcolor=_CONN, route="RD", col_x=skip_x))
                else:
                    self._cv(nid, target)
        elif st == "continue":
            target = loop_back_id
            if target and target in self.placed:
                r = self._back_rails.get(target, self.placed[target].x - _BACK_W)
                self.edges.append(_PE(src=nid, dst=target, label="", lcolor=_CONN,
                                      route="LB", rail_x=r, no_marker=True))

        # Recurse into children (rare for leaf types, but possible).
        # case/default — НЕ собственные блоки (метки границ ветвей switch,
        # см. probe_points.ql/function_flow.ql), пропускаем их: иначе на
        # схеме появлялись бы пустые блоки с текстом "case ..."/"default"
        # посреди обычной последовательности (минимальный безопасный фикс
        # для switch — без построения настоящего N-арного ветвления в
        # каноническом DRAKON-layout, см. обсуждение).
        if node["children"]:
            ch_sorted = sorted(node["children"], key=lambda c: c["line_start"])
            prev_id = nid
            for c in ch_sorted:
                if c["stmt_type"] in ("case", "default"):
                    continue
                prev_id, end_y = self._layout_leaf(c, cx, end_y, prev_id,
                                                   loop_back_id, loop_exit_id, exit_id)

        return nid, end_y

    # ── if node ────────────────────────────────────────────────────────────────
    def _layout_if(self, node: dict, cx: float, y: float,
                   exit_id: Optional[str],
                   loop_back_id: Optional[str],
                   loop_exit_id: Optional[str],
                   prev_id: Optional[str]) -> Tuple[str, float]:
        lab = self._label(node)
        cw, ch = _dims("condition", lab)
        cx_node = cx   # condition centred at cx

        cond_pn = _PN(nid=node["stmt_id"],
                      x=cx_node - cw / 2, y=y, w=cw, h=ch,
                      ntype="condition", label=lab)
        self.placed[node["stmt_id"]] = cond_pn
        if prev_id and prev_id in self.placed:
            self._cv(prev_id, node["stmt_id"])

        el = node.get("else_line", 0)
        then_ch = sorted([c for c in node["children"]
                          if not el or c["line_start"] < el],
                         key=lambda c: c["line_start"])
        else_ch = sorted([c for c in node["children"]
                          if el and c["line_start"] >= el],
                         key=lambda c: c["line_start"])

        body_y   = y + ch + _V_GAP
        nid      = node["stmt_id"]

        if else_ch:
            # ── if-else: YES continues down (same cx), NO goes right ──────────
            then_r   = self._mw_right(then_ch) if then_ch else cw / 2
            else_col = self._mw_col(else_ch)
            # else column cx placed outside all inner then-branch bypasses
            else_cx  = cx + max(cw / 2, then_r) + _H_GAP + else_col / 2
            col_x    = else_cx - else_col / 2   # left edge of else column

            # YES path
            then_last, then_ey = self.layout_seq(then_ch, cx, body_y, exit_id,
                                                 loop_back_id, loop_exit_id, None)
            if then_ch:
                self.edges.append(_PE(src=nid, dst=then_ch[0]["stmt_id"],
                                      label="да", lcolor=_YES_C, route="V"))

            # NO path
            else_last, else_ey = self.layout_seq(else_ch, else_cx, body_y, exit_id,
                                                 loop_back_id, loop_exit_id, None)
            self._crd(nid, else_ch[0]["stmt_id"], col_x, "нет", _NO_C)

            # Merge point
            merge_y = max(then_ey, else_ey)
            mid     = self._merge(cx, merge_y)

            if then_last and then_last in self.placed:
                if not self._is_terminal(then_last):
                    self._cv(then_last, mid)
            else:
                # then branch empty – direct from condition
                self.edges.append(_PE(src=nid, dst=mid, label="да",
                                      lcolor=_YES_C, route="V"))

            if else_last and else_last in self.placed:
                if not self._is_terminal(else_last):
                    self._clu(else_last, mid, else_cx, cx)

            return mid, merge_y + 6 + _V_GAP

        else:
            # ── if without else (guard) ────────────────────────────────────────
            then_r   = self._mw_right(then_ch) if then_ch else cw / 2
            skip_cx  = cx + max(cw / 2, then_r) + _H_GAP  # NO bypass x, outside inner bypasses

            # YES path
            then_last, then_ey = self.layout_seq(then_ch, cx, body_y, exit_id,
                                                 loop_back_id, loop_exit_id, None)
            if then_ch:
                self.edges.append(_PE(src=nid, dst=then_ch[0]["stmt_id"],
                                      label="да", lcolor=_YES_C, route="V"))

            # Is the YES branch terminal (return/throw/exit)?
            merge_y = then_ey  # NO path arrives here
            mid     = self._merge(cx, merge_y)

            if then_last and then_last in self.placed and not self._is_terminal(then_last):
                self._cv(then_last, mid)

            # NO edge: goes right to bypass x, then down to merge, then left back to cx
            self.edges.append(_PE(src=nid, dst=mid, label="нет", lcolor=_NO_C,
                                  route="RD", col_x=skip_cx))

            return mid, merge_y + 6 + _V_GAP

    # ── while / for / do node ─────────────────────────────────────────────────
    def _layout_loop(self, node: dict, cx: float, y: float,
                     exit_id: Optional[str],
                     outer_loop_back: Optional[str],
                     outer_loop_exit: Optional[str],
                     prev_id: Optional[str]) -> Tuple[str, float]:
        lab  = self._label(node)
        lw, lh = _dims("loop", lab)

        loop_cx = cx
        lx      = loop_cx - lw / 2

        # Back rail must be outside all inner loops' back rails
        body_back_ext = self._mw_back_ext(
            sorted(node["children"], key=lambda c: c["line_start"])
        ) if node["children"] else 0.0
        rail_x = loop_cx - max(lw / 2, body_back_ext) - _BACK_W
        self._back_rails[node["stmt_id"]] = rail_x

        loop_pn = _PN(nid=node["stmt_id"],
                      x=lx, y=y, w=lw, h=lh,
                      ntype="loop", label=lab)
        self.placed[node["stmt_id"]] = loop_pn
        if prev_id and prev_id in self.placed:
            self._cv(prev_id, node["stmt_id"])

        nid      = node["stmt_id"]
        body_y   = y + lh + _V_GAP
        body_cx  = loop_cx  # body centred under header

        # Compute bypass rail x before body layout (depends only on tree structure)
        body_r    = self._mw_right(sorted(node["children"], key=lambda c: c["line_start"])) \
                    if node["children"] else lw / 2
        no_skip_x = loop_cx + max(lw / 2, body_r) + _H_GAP + 10

        # Pre-allocate exit merge so break nodes inside body can reference it
        loop_exit_cx = cx
        loop_exit_id = self._merge(loop_exit_cx, body_y)  # y repositioned after body
        self._break_rails[loop_exit_id] = no_skip_x

        # Layout body with loop_exit_id known so break can connect
        body_last, body_ey = self.layout_seq(
            sorted(node["children"], key=lambda c: c["line_start"]),
            body_cx, body_y, exit_id=None,
            loop_back_id=nid, loop_exit_id=loop_exit_id,
            prev_id=None
        )
        if node["children"]:
            first_body = sorted(node["children"], key=lambda c: c["line_start"])[0]
            self.edges.append(_PE(src=nid, dst=first_body["stmt_id"],
                                  label="да", lcolor=_YES_C, route="V"))

        # Add code stub if body is empty.
        # В упрощённом режиме метка — «Базовый блок» (как прочие неветвящиеся
        # узлы), в полном — «(КОД)».
        if not node["children"]:
            stub_label = "Базовый блок" if self.simplified else "(КОД)"
            stub_id = self._uid("stub")
            sw, sh  = _dims("stub", stub_label)
            sx      = body_cx - sw / 2
            self.placed[stub_id] = _PN(nid=stub_id, x=sx, y=body_y,
                                       w=sw, h=sh, ntype="stub", label=stub_label)
            self.edges.append(_PE(src=nid, dst=stub_id,
                                  label="да", lcolor=_YES_C, route="V"))
            body_last = stub_id
            body_ey   = body_y + sh + _V_GAP

        # Loop-back connector (from body bottom → rail_x → loop header left)
        if body_last and body_last in self.placed:
            self._clb(body_last, nid, rail_x)

        # Reposition exit merge to its final y (after body is fully laid out)
        self.placed[loop_exit_id].y = body_ey

        # NO edge from loop header: goes right and down to loop exit
        self.edges.append(_PE(src=nid, dst=loop_exit_id, label="нет", lcolor=_NO_C,
                              route="RD", col_x=no_skip_x))

        return loop_exit_id, body_ey + 6 + _V_GAP

    # ── try / except node ─────────────────────────────────────────────────────
    def _layout_try(self, node: dict, cx: float, y: float,
                    exit_id: Optional[str],
                    loop_back_id: Optional[str],
                    loop_exit_id: Optional[str],
                    prev_id: Optional[str]) -> Tuple[str, float]:
        lab  = self._label(node)
        cw, ch = _dims("condition", lab)
        cond_pn = _PN(nid=node["stmt_id"],
                      x=cx - cw / 2, y=y, w=cw, h=ch,
                      ntype="condition", label=lab)
        self.placed[node["stmt_id"]] = cond_pn
        if prev_id and prev_id in self.placed:
            self._cv(prev_id, node["stmt_id"])

        nid    = node["stmt_id"]
        body_y = y + ch + _V_GAP

        try_ch   = sorted([c for c in node["children"] if not int(c.get("in_catch", "0") or 0)],
                          key=lambda c: c["line_start"])
        catch_ch = sorted([c for c in node["children"] if int(c.get("in_catch", "0") or 0)],
                          key=lambda c: c["line_start"])

        try_r    = self._mw_right(try_ch) if try_ch else cw / 2
        catch_col = self._mw_col(catch_ch) if catch_ch else 0

        catch_cx = cx + max(cw / 2, try_r) + _H_GAP + catch_col / 2

        # try body (YES / нет исключения path)
        try_last, try_ey = self.layout_seq(try_ch, cx, body_y, exit_id,
                                           loop_back_id, loop_exit_id, None)
        if try_ch:
            self.edges.append(_PE(src=nid, dst=try_ch[0]["stmt_id"],
                                  label="нет исключения", lcolor=_YES_C, route="V"))

        # catch branch (NO path)
        catch_last = None; catch_ey = body_y
        if catch_ch:
            catch_last, catch_ey = self.layout_seq(catch_ch, catch_cx, body_y, exit_id,
                                                   loop_back_id, loop_exit_id, None)
            self._crd(nid, catch_ch[0]["stmt_id"],
                      catch_cx - catch_col / 2, "catch", _NO_C)

        # Merge
        merge_y = max(try_ey, catch_ey)
        mid     = self._merge(cx, merge_y)
        if try_last and try_last in self.placed:
            self._cv(try_last, mid)
        if catch_last and catch_last in self.placed:
            self._clu(catch_last, mid, catch_cx, cx)
        elif catch_ch and not catch_last:
            self.edges.append(_PE(src=nid, dst=mid, label="catch",
                                  lcolor=_NO_C, route="V"))

        return mid, merge_y + 6 + _V_GAP

    # ── full diagram layout ────────────────────────────────────────────────────
    def layout(self, roots: list, func_name: str, func_num: int) -> Tuple[float, float]:
        """
        Layout the full diagram. Returns (svg_width, svg_height).
        Diagram is drawn starting at (_MARGIN, _MARGIN).
        """
        col_w    = self._mw_col(roots)
        max_r    = self._mw_right(roots)
        back_ext = max(_BACK_W, self._mw_back_ext(roots))  # space for all back-rails
        cx       = _MARGIN + back_ext + col_w / 2
        total_w  = cx + max_r + _MARGIN

        # Start capsule
        sw, sh = _dims("start", f"Начало\n({func_num}){func_name[:30]}")
        sx = cx - sw / 2
        start_pn = _PN(nid="__start", x=sx, y=_MARGIN, w=sw, h=sh,
                       ntype="start", label=f"Начало\n({func_num}){func_name[:30]}")
        self.placed["__start"] = start_pn

        y = _MARGIN + sh + _V_GAP

        # Pre-allocate __end so return/throw/exit can connect to it during layout
        ew, eh = _dims("end", "Конец")
        ex = cx - ew / 2
        self.placed["__end"] = _PN(nid="__end", x=ex, y=0, w=ew, h=eh,
                                   ntype="end", label="Конец")

        last_id, y = self.layout_seq(roots, cx, y, exit_id="__end",
                                     prev_id="__start")

        # Move __end to its final position
        self.placed["__end"].y = y
        if last_id and last_id in self.placed:
            self._cv(last_id, "__end")

        svg_h  = y + eh + _MARGIN
        svg_w  = total_w
        return svg_w, svg_h


# ── SVG rendering ─────────────────────────────────────────────────────────────

def _svg_text_lines(lines: List[str], cx: float, cy_mid: float,
                    font_size: int = 12) -> str:
    """Multi-line SVG text centred at (cx, cy_mid)."""
    lh  = font_size * 1.35
    total_h = len(lines) * lh
    y0  = cy_mid - total_h / 2 + lh * 0.8
    parts = []
    for i, line in enumerate(lines):
        parts.append(
            f'<text x="{cx:.1f}" y="{y0 + i*lh:.1f}" '
            f'text-anchor="middle" font-size="{font_size}" fill="{_BORDER}">'
            f'{_escape(line)}</text>'
        )
    return "\n".join(parts)


def _svg_rect(pn: _PN, rx: float = 4) -> str:
    fill = _fill(pn.ntype)
    sw   = 2.0 if pn.ntype == "call" else 1.5
    parts = [
        f'<rect x="{pn.x:.1f}" y="{pn.y:.1f}" width="{pn.w:.1f}" height="{pn.h:.1f}" '
        f'rx="{rx}" ry="{rx}" fill="{fill}" stroke="{_BORDER}" stroke-width="{sw}"/>'
    ]
    if pn.ntype == "call":   # double border
        m = 4
        parts.append(
            f'<rect x="{pn.x+m:.1f}" y="{pn.y+m:.1f}" '
            f'width="{pn.w-2*m:.1f}" height="{pn.h-2*m:.1f}" '
            f'rx="{max(0,rx-2)}" ry="{max(0,rx-2)}" '
            f'fill="none" stroke="{_BORDER}" stroke-width="1"/>'
        )
    cx = pn.x + pn.w / 2
    cy = pn.y + pn.h / 2
    parts.append(_svg_text_lines(_wrap(pn.label), cx, cy))
    return "\n".join(parts)


def _svg_question(pn: _PN) -> str:
    """DRAKON Question icon: horizontal hexagon with pointed left/right vertices.
    Matches buildQuestionCoords from drakon_canvas.js."""
    pad = min(20.0, pn.h * 0.38)
    x0, x1 = pn.x, pn.x + pad
    x3, x2 = pn.x + pn.w, pn.x + pn.w - pad
    cy = pn.y + pn.h / 2
    bot = pn.y + pn.h
    pts = (f"{x0:.1f},{cy:.1f} "
           f"{x1:.1f},{pn.y:.1f} "
           f"{x2:.1f},{pn.y:.1f} "
           f"{x3:.1f},{cy:.1f} "
           f"{x2:.1f},{bot:.1f} "
           f"{x1:.1f},{bot:.1f}")
    fill = _fill(pn.ntype)
    cx = pn.x + pn.w / 2
    out = [f'<polygon points="{pts}" fill="{fill}" stroke="{_BORDER}" stroke-width="1.5"/>']
    out.append(_svg_text_lines(_wrap(pn.label, 20), cx, cy, font_size=11))
    return "\n".join(out)


def _svg_loop_begin(pn: _PN) -> str:
    """DRAKON Loop Begin icon: shield shape — pointed left/right at mid-height,
    chamfered top corners, flat bottom.
    Matches buildLoopBeginCoords from drakon_canvas.js."""
    ADD = 5.0
    pad = min(20.0, pn.h * 0.40)
    x0, x1 = pn.x - ADD, pn.x - ADD + pad
    x3, x2 = pn.x + pn.w + ADD, pn.x + pn.w + ADD - pad
    cy = pn.y + pn.h / 2
    bot = pn.y + pn.h
    pts = (f"{x0:.1f},{cy:.1f} "
           f"{x1:.1f},{pn.y:.1f} "
           f"{x2:.1f},{pn.y:.1f} "
           f"{x3:.1f},{cy:.1f} "
           f"{x3:.1f},{bot:.1f} "
           f"{x0:.1f},{bot:.1f}")
    fill = _fill(pn.ntype)
    cx = pn.x + pn.w / 2
    out = [f'<polygon points="{pts}" fill="{fill}" stroke="{_BORDER}" stroke-width="1.5"/>']
    out.append(_svg_text_lines(_wrap(pn.label, 22), cx, cy, font_size=11))
    return "\n".join(out)


def _svg_output(pn: _PN) -> str:
    """DRAKON Output icon: pentagon with right-pointing flag.
    Matches buildSimpleOutputCoords from drakon_canvas.js."""
    pad = min(18.0, pn.h * 0.40)
    x1 = pn.x + pn.w - pad
    cy = pn.y + pn.h / 2
    bot = pn.y + pn.h
    pts = (f"{pn.x:.1f},{pn.y:.1f} "
           f"{x1:.1f},{pn.y:.1f} "
           f"{pn.x+pn.w:.1f},{cy:.1f} "
           f"{x1:.1f},{bot:.1f} "
           f"{pn.x:.1f},{bot:.1f}")
    fill = _fill(pn.ntype)
    cx = (pn.x + x1) / 2   # centre text left of the arrow tip
    out = [f'<polygon points="{pts}" fill="{fill}" stroke="{_BORDER}" stroke-width="1.5"/>']
    out.append(_svg_text_lines(_wrap(pn.label), cx, cy))
    return "\n".join(out)


def _svg_capsule(pn: _PN) -> str:
    """Rounded capsule for start/end."""
    r  = pn.h / 2
    fill = _fill(pn.ntype)
    out = [
        f'<rect x="{pn.x:.1f}" y="{pn.y:.1f}" width="{pn.w:.1f}" height="{pn.h:.1f}" '
        f'rx="{r:.1f}" ry="{r:.1f}" fill="{fill}" stroke="{_BORDER}" stroke-width="1.5"/>'
    ]
    cx = pn.x + pn.w / 2
    cy = pn.y + pn.h / 2
    out.append(_svg_text_lines(_wrap(pn.label, 30), cx, cy, font_size=11))
    return "\n".join(out)


def _svg_node(pn: _PN) -> str:
    if pn.ntype == "merge":
        # Invisible merge point — rendered as tiny dot
        cx = pn.x + 3
        cy = pn.y + 3
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2" fill="{_CONN}"/>'
    if pn.ntype == "condition":
        return _svg_question(pn)
    if pn.ntype == "loop":
        return _svg_loop_begin(pn)
    if pn.ntype == "io":
        return _svg_output(pn)
    if pn.ntype in ("start", "end"):
        return _svg_capsule(pn)
    if pn.ntype == "stub":
        return _svg_rect(pn, rx=2)
    if pn.ntype == "return":
        return _svg_rect(pn, rx=16)
    return _svg_rect(pn, rx=4)


def _svg_edge(edge: _PE, placed: Dict[str, _PN]) -> str:
    """Render one edge as an SVG path with optional label."""
    if edge.src not in placed or edge.dst not in placed:
        return ""
    src_pn = placed[edge.src]
    dst_pn = placed[edge.dst]

    def south(p: _PN) -> Tuple[float, float]:
        return (p.x + p.w / 2, p.y + p.h)

    def north(p: _PN) -> Tuple[float, float]:
        return (p.x + p.w / 2, p.y)

    def east(p: _PN) -> Tuple[float, float]:
        if p.ntype == "condition":
            return (p.x + p.w, p.y + p.h / 2)
        if p.ntype == "loop":
            return (p.x + p.w, p.y + p.h / 2)
        return (p.x + p.w, p.y + p.h / 2)

    def west(p: _PN) -> Tuple[float, float]:
        if p.ntype == "loop":
            return (p.x, p.y + p.h / 2)
        return (p.x, p.y + p.h / 2)

    color = _BORDER
    lw    = "1.5"
    dash  = ""
    marker = "" if edge.no_marker else ' marker-end="url(#arr)"'

    route = edge.route

    if route == "V":
        sx, sy = south(src_pn)
        dx, dy = north(dst_pn)
        # straight or with mid-column alignment
        if abs(sx - dx) < 2:
            d = f"M {sx:.1f} {sy:.1f} L {dx:.1f} {dy:.1f}"
        else:
            midy = (sy + dy) / 2
            d = (f"M {sx:.1f} {sy:.1f} "
                 f"L {sx:.1f} {midy:.1f} "
                 f"L {dx:.1f} {midy:.1f} "
                 f"L {dx:.1f} {dy:.1f}")
        color = edge.lcolor if edge.lcolor != _CLABEL else _BORDER

    elif route == "RD":
        # Depart from east of source, go right to col_x, down, arrive at north of dst
        # Final segment is vertical (↓) so the arrowhead points down into the node top
        ex, ey = east(src_pn)
        col_x  = edge.col_x
        dx, dy = north(dst_pn)
        gap    = _V_GAP / 2
        d = (f"M {ex:.1f} {ey:.1f} "
             f"L {col_x:.1f} {ey:.1f} "
             f"L {col_x:.1f} {dy - gap:.1f} "
             f"L {dx:.1f} {dy - gap:.1f} "
             f"L {dx:.1f} {dy:.1f}")
        color = edge.lcolor

    elif route == "LU":
        # Merge from right alt-col back to main merge point
        # src-bottom → down a bit → left to dst-center → down into dst top
        # All segments go downward or leftward — no upward arrows
        sx, sy = south(src_pn)
        dx, dy = north(dst_pn)
        dcx    = dst_pn.x + dst_pn.w / 2
        turn_y = sy + _V_GAP / 3   # guaranteed < dy since dy ≈ sy + V_GAP
        d = (f"M {sx:.1f} {sy:.1f} "
             f"L {sx:.1f} {turn_y:.1f} "
             f"L {dcx:.1f} {turn_y:.1f} "
             f"L {dcx:.1f} {dy:.1f}")
        color  = _CONN
        lw     = "1.2"
        dash   = 'stroke-dasharray="6,3"'

    elif route == "LB":
        # Loop-back: src-bottom → down-ext → rail_x (left) → up rail → turn right
        # above loop header → down into loop header top (arrowhead points ↓)
        sx, sy = south(src_pn)
        nx, ny = north(dst_pn)
        rail_x = edge.rail_x
        ext_y  = sy + 18   # a little below the body
        gap    = _V_GAP / 2
        d = (f"M {sx:.1f} {sy:.1f} "
             f"L {sx:.1f} {ext_y:.1f} "
             f"L {rail_x:.1f} {ext_y:.1f} "
             f"L {rail_x:.1f} {ny - gap:.1f} "
             f"L {nx:.1f} {ny - gap:.1f} "
             f"L {nx:.1f} {ny:.1f}")
        color  = _CONN
        lw     = "1.2"
        dash   = 'stroke-dasharray="6,3"'

    else:
        return ""

    style = f'stroke="{color}" stroke-width="{lw}" fill="none"'
    if dash:
        style += f' {dash}'
    path_svg = f'<path d="{d}" {style}{marker}/>'

    # Edge label
    label_svg = ""
    if edge.label:
        # Place label near the start of the path
        m = re.match(r"M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+)", d)
        if m:
            lx = (float(m.group(1)) + float(m.group(3))) / 2 + 4
            ly = (float(m.group(2)) + float(m.group(4))) / 2 - 4
        else:
            # fallback: near source
            lx = src_pn.x + src_pn.w / 2 + 8
            ly = src_pn.y + src_pn.h + 14
        label_svg = (f'<text x="{lx:.1f}" y="{ly:.1f}" '
                     f'font-size="10" fill="{edge.lcolor}">'
                     f'{_escape(edge.label)}</text>')

    return path_svg + ("\n" + label_svg if label_svg else "")


# ── Process-pool worker state (module-level, lives in each worker process) ────

_DK_PP_STATE: Dict[str, Any] = {}


def _dk_pp_init(spec: dict, func_index: dict, var_index: dict) -> None:
    """Worker-process initializer: reconstruct DrakonGenerator from spec."""
    import importlib
    mod = importlib.import_module(spec["module"])
    cls = getattr(mod, spec["qualname"])
    _DK_PP_STATE["gen"]        = cls(**spec["kwargs"])
    _DK_PP_STATE["func_index"] = func_index
    _DK_PP_STATE["var_index"]  = var_index


def _dk_pp_task(args: tuple):
    """Worker task: build one flowchart, return (filename, cache_key)."""
    func_name, func_num, stmts, cache_key = args
    gen = _DK_PP_STATE["gen"]
    try:
        result = gen.generate(func_name, func_num, stmts,
                              _DK_PP_STATE["func_index"], _DK_PP_STATE["var_index"])
        return (result, cache_key)
    except Exception as _e:
        import traceback as _tb
        print(f"[DRAKON] ERROR {func_name}: {_e}\n{_tb.format_exc()}", flush=True)
        return ("", cache_key)


# ── Generator class ────────────────────────────────────────────────────────────

class DrakonGenerator:
    """
    DRAKON-style SVG flowchart generator — standalone, no external dependencies.
    Layout: YES/да goes down (main spine), NO/нет goes right (bypass column),
    loop back-edges on the left rail. All connectors are orthogonal.
    """

    def __init__(self, output_dir: str, db_path: str = None,
                 clear_output: bool = True, simplified: bool = False):
        self.output_dir  = Path(output_dir)
        self.db_path     = Path(db_path) if db_path else None
        self.simplified  = simplified
        if clear_output and self.output_dir.exists():
            for old in self.output_dir.iterdir():
                if old.is_file():
                    try:
                        old.unlink()
                    except OSError:
                        pass
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._source_by_base: Dict[str, List[str]] = {}
        self._build_source_index()

    # ── Source reading from CodeQL db src.zip ─────────────────────────────────

    def _build_source_index(self) -> None:
        if not self.db_path:
            return
        src_zip = self.db_path / "src.zip"
        if not src_zip.exists():
            return
        try:
            with zipfile.ZipFile(src_zip) as z:
                for name in z.namelist():
                    if name.endswith("/"):
                        continue
                    base = name.replace("\\", "/").rsplit("/", 1)[-1]
                    if base in self._source_by_base:
                        continue
                    try:
                        text = z.read(name).decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                    self._source_by_base[base] = text.splitlines()
        except (zipfile.BadZipFile, OSError):
            pass

    def _get_source_line(self, stmt_id: str) -> Optional[str]:
        if ":" not in stmt_id:
            return None
        parts = stmt_id.rsplit(":", 1)
        if len(parts) != 2:
            return None
        filename, line_str = parts
        try:
            line_num = int(line_str) - 1
        except ValueError:
            return None
        base  = filename.replace("\\", "/").rsplit("/", 1)[-1]
        lines = self._source_by_base.get(base)
        if not lines or not (0 <= line_num < len(lines)):
            return None
        return lines[line_num].strip()

    def _get_source_statement(self, stmt_id: str, max_lines: int = 6) -> Optional[str]:
        first = self._get_source_line(stmt_id)
        if first is None:
            return None
        if ":" not in stmt_id:
            return first
        filename, line_str = stmt_id.rsplit(":", 1)
        try:
            line_num = int(line_str) - 1
        except ValueError:
            return first
        base  = filename.replace("\\", "/").rsplit("/", 1)[-1]
        lines = self._source_by_base.get(base)
        if not lines:
            return first
        result  = first
        balance = first.count("(") - first.count(")")
        i = line_num + 1
        guard = 0
        while balance > 0 and ";" not in result and i < len(lines) and guard < max_lines:
            nxt = lines[i].strip()
            result  = (result + " " + nxt).strip()
            balance += nxt.count("(") - nxt.count(")")
            i += 1; guard += 1
        return result

    # ── Label helpers ──────────────────────────────────────────────────────────

    def _extract_condition_text(self, stmt_id: str, stmt_type: str, default_label: str) -> str:
        source = self._get_source_statement(stmt_id) or self._get_source_line(stmt_id)
        if not source:
            return default_label
        src = source.strip()

        def paren(kw):
            m = re.search(rf'\b{kw}\s*\(', src)
            if not m:
                return None
            i = m.end() - 1
            depth = 0
            for j in range(i, len(src)):
                if src[j] == '(':   depth += 1
                elif src[j] == ')':
                    depth -= 1
                    if depth == 0:
                        return src[i + 1:j].strip()
            return src[i + 1:].strip()

        def colon(kw):
            m = re.search(rf'\b{kw}\b\s*(.+?)\s*:\s*(#.*)?$', src)
            return m.group(1).strip() if m else None

        if stmt_type == "if":
            c = paren("if") or colon("if") or colon("elif")
            return f"if ({c})" if c else default_label
        if stmt_type == "while":
            c = paren("while") or colon("while")
            return f"while ({c})" if c else default_label
        if stmt_type == "for":
            if paren("for") is not None:
                return f"for ({paren('for')})"
            c = colon("for")
            return f"for ({c})" if c else default_label
        if stmt_type == "do":
            c = paren("while")
            return f"do ... while ({c})" if c else default_label
        if stmt_type == "return":
            m = re.search(r'\breturn\b\s*(.*?)\s*;', src) or re.search(r'\breturn\b\s*(.*)$', src)
            if m and m.group(1).strip():
                return f"return {m.group(1).strip()}"
            return "return"
        if stmt_type == "try":
            return "try"
        return default_label

    @staticmethod
    def _remove_comments(label: str) -> str:
        label = re.sub(r'//.*$',    '', label, flags=re.MULTILINE)
        label = re.sub(r'/\*.*?\*/', '', label, flags=re.DOTALL)
        return label.strip()

    def _format_label(self, label: str,
                      func_index: Dict[str, int],
                      var_index: Dict[str, int]) -> str:
        label = self._remove_comments(label)

        def _annotate(text, name, num):
            if name not in text:
                return text
            return re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)',
                          lambda _m, n=num, nm=name: f"({n}){nm}", text)

        for fname, fnum in sorted(func_index.items(), key=lambda x: -len(x[0])):
            label = _annotate(label, fname, fnum)
        for vname, vnum in sorted(var_index.items(), key=lambda x: -len(x[0])):
            label = _annotate(label, vname, vnum)
        if len(label) > 60:
            label = label[:57] + "..."
        return label

    # ── Hierarchy builder ──────────────────────────────────────────────────────

    def _build_hierarchy(self, stmts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sorted_stmts = sorted(
            stmts,
            key=lambda x: (int(x.get("line", x.get("line_start", "1"))),
                           int(x.get("line_end", "9999")))
        )
        nodes = []
        for s in sorted_stmts:
            nodes.append({
                "stmt_id":    s["stmt_id"],
                "line_start": int(s.get("line", s.get("line_start", "1"))),
                "line_end":   int(s.get("line_end", s.get("line", "1"))),
                "stmt_type":  s.get("stmt_type", "other"),
                "stmt_label": s.get("stmt_label", "..."),
                "branch_type": s.get("branch_type", ""),
                "else_line":  int(s.get("else_line", "0") or 0),
                "branch_num": s.get("branch_num"),
                "callee_num": s.get("callee_num"),
                "in_catch":   int(s.get("in_catch", "0") or 0),
                "children":   [],
                "parent":     None,
            })
        # Catch-узел относим к ближайшему предшествующему try (см. комментарий
        # в flowchart_generator._build_hierarchy): иначе при нескольких try
        # каждый растягивался до самого дальнего catch чужого блока.
        try_nodes = sorted((n for n in nodes if n["stmt_type"] == "try"),
                           key=lambda n: n["line_start"])
        if try_nodes:
            for c in nodes:
                if c.get("in_catch") != 1:
                    continue
                owner = None
                for t in try_nodes:
                    if t["line_start"] <= c["line_start"]:
                        owner = t
                    else:
                        break
                if owner is not None:
                    owner["line_end"] = max(owner["line_end"], c["line_end"])
        for i, child in enumerate(nodes):
            best_parent = None
            for j in range(i - 1, -1, -1):
                cand = nodes[j]
                if (cand["line_start"] <= child["line_start"]
                        and cand["line_end"] >= child["line_end"]
                        and cand["stmt_type"] in ("if", "while", "for", "do", "code", "try", "switch")):
                    if best_parent is None or cand["line_start"] > best_parent["line_start"]:
                        best_parent = cand
            if best_parent:
                child["parent"] = best_parent
                best_parent["children"].append(child)
        return [n for n in nodes if n["parent"] is None]

    # ── Process-pool reconstruction ────────────────────────────────────────────

    def _worker_kwargs(self) -> dict:
        return {
            "output_dir":   str(self.output_dir),
            "db_path":      str(self.db_path) if self.db_path else None,
            "clear_output": False,
            "simplified":   self.simplified,
        }

    def _worker_spec(self) -> dict:
        return {
            "module":   type(self).__module__,
            "qualname": type(self).__qualname__,
            "kwargs":   self._worker_kwargs(),
        }

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(self, func_name: str, func_num: int,
                 stmts: List[Dict[str, Any]],
                 func_index: Dict[str, int],
                 var_index: Dict[str, int]) -> str:
        safe = re.sub(r'[^\w]', '_', func_name)
        base = f"{func_num}_{safe}"

        roots = self._build_hierarchy(stmts)
        if self.simplified:
            from viz.flowchart_generator import _simplify_seq
            roots = _simplify_seq(roots)
        if not roots and stmts:
            # stmts есть, но иерархия не построилась — нештатная ситуация
            print(f"[DRAKON] SKIP {func_name}: _build_hierarchy вернул пустой список "
                  f"({len(stmts)} stmts)", flush=True)
            return ""
        # roots=[] + stmts=[] → пустая ФО → строим минимальную схему START→END

        # Build layout
        layouter = _Layouter(self, func_index, var_index)
        svg_w, svg_h = layouter.layout(roots, func_name, func_num)

        # Render SVG
        svg = self._render_svg(layouter.placed, layouter.edges, svg_w, svg_h)

        filepath = self.output_dir / f"{base}.svg"
        try:
            filepath.write_text(svg, encoding="utf-8")
        except OSError:
            return ""
        return f"{base}.svg"

    def generate_all(
        self,
        func_data:       List[Dict[str, str]],
        flow_data:       List[Dict[str, str]],
        info_data:       List[Dict[str, str]],
        control_data:    List[Dict[str, str]]  = None,
        data_data:       List[Dict[str, str]]  = None,
        file_flow_data:  List[Dict[str, str]]  = None,
        route_writer                           = None,
        load_by_demand:  bool                  = False,
        build_flowcharts: bool                 = True,
        need_routes_in_memory: bool            = False,
        max_routes:      int                   = 1000,
        progress                               = None,
        workers:         int                   = 0,
        log                                    = None,
    ):
        """Generate DRAKON SVGs for all functions.

        Returns (generated_files, {}, {}, {}) — routes/branches not computed
        by the DRAKON renderer (handled by FlowchartGenerator when needed).
        """
        import os, time
        from collections import defaultdict
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

        # Build indices
        func_index: Dict[str, int] = {
            item["qualified_name"]: i + 1 for i, item in enumerate(func_data)
        }
        _info_no_params = [it for it in info_data if it.get("kind") != "parameter"]
        var_index: Dict[str, int] = {
            item["qualified_name"]: i + 1 for i, item in enumerate(_info_no_params)
        }

        # Group flow statements by (func_name, func_file) — файл обязателен,
        # иначе все одноимённые функции (например, main из разных модулей)
        # получат одинаковые stmts и одинаковые блок-схемы.
        # stmts_by_name — fallback для данных без func_file (старые project.db).
        stmts_by_func: Dict[tuple, list] = defaultdict(list)
        stmts_by_name: Dict[str, list] = defaultdict(list)
        for item in flow_data:
            key = (item["func_name"], item.get("func_file", ""))
            stmts_by_func[key].append(item)
            stmts_by_name[item["func_name"]].append(item)

        # Build task list: sort small→large for better parallel utilisation
        # fnum = row index (i+1) to match Перечень_ФО row numbers 1:1.
        tasks = []
        for i, item in enumerate(func_data):
            fname = item["qualified_name"]
            ffile = item.get("file", "")
            fnum  = i + 1
            stmts = stmts_by_func.get((fname, ffile))
            if stmts is None:
                stmts = stmts_by_name.get(fname, [])
            tasks.append((fname, fnum, stmts, fname))
        tasks.sort(key=lambda t: len(t[2]))

        generated: List[str] = []
        if not build_flowcharts:
            return generated, {}, {}, {}

        total   = len(tasks)
        done    = 0
        t_start = time.time()

        max_w = workers if workers > 0 else min(os.cpu_count() or 1, 8)
        use_procs = max_w > 1 and total > 4

        def _on(result):
            nonlocal done
            if result:
                generated.append(result)
            done += 1
            if progress and (done % 10 == 0 or done == total):
                progress("[БЛОК-СХЕМЫ] Генерация блок-схем (ФО)", done, total)
            if done % 100 == 0 or done == total:
                print(f"[DRAKON] {done}/{total} блок-схем готово", flush=True)

        if use_procs:
            spec = self._worker_spec()
            try:
                with ProcessPoolExecutor(
                    max_workers=max_w,
                    initializer=_dk_pp_init,
                    initargs=(spec, func_index, var_index),
                ) as pool:
                    futures = {pool.submit(_dk_pp_task, t): t[3] for t in tasks}
                    for fut in as_completed(futures):
                        try:
                            result, _ = fut.result()
                        except Exception as _e:
                            print(f"[DRAKON] ERROR future: {_e}", flush=True)
                            result = ""
                        _on(result)
            except Exception as exc:
                print(f"[DRAKON] ProcessPool failed ({exc}), falling back to threads",
                      flush=True)
                use_procs = False
                done = 0
                generated.clear()

        if not use_procs:
            with ThreadPoolExecutor(max_workers=max_w) as pool:
                futures = {
                    pool.submit(self.generate, fn, fnum, st, func_index, var_index): ck
                    for fn, fnum, st, ck in tasks
                }
                for fut in as_completed(futures):
                    try:
                        result = fut.result()
                    except Exception as _e:
                        print(f"[DRAKON] ERROR future: {_e}", flush=True)
                        result = ""
                    _on(result)

        elapsed = time.time() - t_start
        print(f"[DRAKON] Done: {len(generated)}/{total} SVGs in {elapsed:.1f}s", flush=True)
        if log:
            log(f"[БЛОК-СХЕМЫ] DRAKON: {len(generated)} SVG за {elapsed:.1f} с")

        return generated, {}, {}, {}

    def _render_svg(self, placed: Dict[str, _PN], edges: List[_PE],
                    svg_w: float, svg_h: float) -> str:
        W = math.ceil(svg_w)
        H = math.ceil(svg_h)

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="Courier New, monospace" font-size="12">',
            '<defs>',
            '  <marker id="arr" markerWidth="10" markerHeight="7" '
            '  refX="9" refY="3.5" orient="auto" markerUnits="strokeWidth">',
            f'    <polygon points="0,0 10,3.5 0,7" fill="{_BORDER}"/>',
            '  </marker>',
            '</defs>',
            f'<rect width="{W}" height="{H}" fill="{_BG}"/>',
        ]

        # Draw edges first (behind nodes)
        for edge in edges:
            s = _svg_edge(edge, placed)
            if s:
                parts.append(s)

        # Draw nodes on top
        for nid, pn in placed.items():
            parts.append(_svg_node(pn))

        parts.append('</svg>')
        return "\n".join(parts)
