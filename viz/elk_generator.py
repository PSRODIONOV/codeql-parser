"""
elk_generator.py — ELK-based flowchart layout + Graphviz neato rendering.

Architecture:
  1. GraphBuilder  — mock graphviz.Digraph that accumulates nodes/edges
  2. _build_elk_json — convert graph to ELK JSON with proper node sizes
  3. _run_elkjs     — call elk_layout.js via Node.js, get positioned graph
  4. _elk_to_dot    — convert ELK positions back to Graphviz DOT (pos= attrs)
  5. _render_neato  — call neato -n (use fixed positions, route edges only)
  6. ELKFlowchartGenerator — subclass of FlowchartGenerator, overrides generate()
"""

import json
import os
import sys
import shutil
import gc
import subprocess
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from viz.flowchart_generator import FlowchartGenerator
from paths import third_party


# ─────────────────────────────────────────────────────────────────────────────
# GraphBuilder — API-compatible mock of graphviz.Digraph
# ─────────────────────────────────────────────────────────────────────────────

class GraphBuilder:
    """Captures nodes/edges using the same API as graphviz.Digraph."""

    def __init__(self, comment: str = ""):
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []
        self._group = None  # текущая группа (пунктирный бокс охранника)

    # Match graphviz.Digraph.attr() signature
    def attr(self, elem_type=None, **attrs):
        pass  # Graph/node/edge defaults not needed for ELK path

    def node(self, name: str, label: str = None, **attrs):
        nd = {"label": label if label is not None else name, **attrs}
        if self._group:
            nd["group"] = self._group
        self._nodes[name] = nd

    def edge(self, tail: str, head: str, **attrs):
        self._edges.append({"tail": tail, "head": head, **attrs})


# ─────────────────────────────────────────────────────────────────────────────
# Node size estimation for ELK
# ─────────────────────────────────────────────────────────────────────────────

_CW = 7.5   # Courier 12px — char width (px)
_LH = 17.0  # line height (px)
_PX = 16    # horizontal padding
_PY = 10    # vertical padding


def _text_bbox(label: str) -> Tuple[float, float]:
    lines = label.split("\n")
    w = max((len(l) for l in lines), default=4) * _CW + _PX
    h = len(lines) * _LH + _PY
    return w, h


def _node_size(label: str, shape: str, style: str = "") -> Tuple[int, int]:
    lw, lh = _text_bbox(label)
    if shape == "diamond":
        # Diamond bounding box must inscribe the label text
        w = max(lw * 2.4, 140)
        h = max(lh * 2.2,  65)
    elif shape == "hexagon":
        w = max(lw * 1.7, 150)
        h = max(lh * 1.6,  65)
    elif shape == "parallelogram":
        w = max(lw + 30, 100)
        h = max(lh,  38)
    elif shape == "point":
        return 2, 2
    elif shape == "circle":
        # Соединитель — компактный эллипс по тексту метки.
        return int(max(lw + 16, 46)), int(max(lh + 10, 40))
    elif shape == "pentagon":
        # Межстраничный соединитель ГОСТ — пятиугольник «домиком».
        return int(max(lw + 24, 80)), int(max(lh + 20, 48))
    elif "rounded" in style:
        w = max(lw, 130)
        h = max(lh + 6, 44)
    else:
        w = max(lw, 80)
        h = max(lh, 36)
    return int(w), int(h)


# ─────────────────────────────────────────────────────────────────────────────
# ELK JSON
# ─────────────────────────────────────────────────────────────────────────────

_ELK_OPTS = {
    "algorithm": "layered",
    "elk.direction": "DOWN",
    "elk.edgeRouting": "ORTHOGONAL",
    # Brandes–Köpf BALANCED — центрирует каждый узел между соседями
    "layered.nodePlacement.strategy": "BRANDES_KOEPF",
    "layered.nodePlacement.bk.fixedAlignment": "BALANCED",
    "layered.crossingMinimization.strategy": "LAYER_SWEEP",
    # Доп. жадная перестановка соседних узлов в обе стороны — убирает остаточные
    # пересечения после послойной развёртки.
    "elk.layered.crossingMinimization.greedySwitch.type": "TWO_SIDED",
    # Прямее рёбра (меньше изломов и визуальных пересечений).
    "elk.layered.nodePlacement.favorStraightEdges": "true",
    # Разрыв циклов по порядку объявления узлов: ELK развернёт именно
    # обратное ребро цикла (увеличивает порядковый номер), поэтому тело
    # цикла всегда оказывается НИЖЕ заголовка-шестиугольника.
    "layered.cycleBreaking.strategy": "MODEL_ORDER",
    "layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    "elk.layered.thoroughness": "15",
    "elk.padding": "[top=35, left=55, bottom=35, right=55]",
    "elk.spacing.nodeNode": "45",
    "elk.spacing.edgeNode": "25",
    "elk.spacing.edgeEdge": "15",
    "elk.layered.unnecessaryBendpoints": "true",
}


def _is_back_edge(ed: dict) -> bool:
    """Обратное ребро цикла — помечено генератором как tailport=w AND headport=w."""
    return ed.get("tailport") == "w" and ed.get("headport") == "w"


def _edge_label(ed: dict) -> str:
    return (ed.get("taillabel") or ed.get("label") or "").strip()


def _build_elk_json(builder: GraphBuilder) -> dict:
    """
    Строит ELK JSON с фиксированными портами для управления сторонами рёбер:
      • шестиугольник цикла: тело — SOUTH, выход — EAST, возврат — WEST;
      • последний узел тела: возврат выходит из его WEST;
      • ромб «нет»: ветка выходит из WEST.
    Это гарантирует требования 1 и 2 (стороны крепления рёбер).
    """
    nodes  = builder._nodes
    redges = builder._edges

    # порты по узлам и привязка концов рёбер к портам
    ports_by_node: Dict[str, List[dict]] = defaultdict(list)
    src_port: Dict[int, str] = {}
    tgt_port: Dict[int, str] = {}

    def ensure_port(nid: str, side: str) -> str:
        pid = f"{nid}__p_{side}"
        if not any(p["id"] == pid for p in ports_by_node[nid]):
            ports_by_node[nid].append({"id": pid, "side": side})
        return pid

    for i, ed in enumerate(redges):
        t, h = ed["tail"], ed["head"]
        ts = nodes.get(t, {}).get("shape", "box")
        hs = nodes.get(h, {}).get("shape", "box")
        lbl = _edge_label(ed)
        back = _is_back_edge(ed)

        if hs == "hexagon" and back:
            # возврат в цикл: из WEST тела в WEST шестиугольника
            tgt_port[i] = ensure_port(h, "WEST")
            src_port[i] = ensure_port(t, "WEST")
        elif ts == "hexagon" and lbl == "да":
            src_port[i] = ensure_port(t, "SOUTH")      # вход в тело
        elif ts == "hexagon" and not lbl:
            src_port[i] = ensure_port(t, "EAST")       # выход из цикла
        elif ts == "diamond" and lbl == "да":
            src_port[i] = ensure_port(t, "SOUTH")      # ветка «да» — из нижней вершины
        elif ts == "diamond" and lbl == "нет":
            src_port[i] = ensure_port(t, "WEST")       # ветка «нет» — из левой вершины
        elif h == "end":
            # требование 2: рёбра в «Конец» (от не-ромбов) выходят из нижней грани.
            src_port[i] = ensure_port(t, "SOUTH")

        # Вход в ромб — всегда в верхнюю вершину (NORTH), иначе ELK
        # смещает входящее ребро вдоль грани и оно «висит» не на вершине.
        if hs == "diamond":
            tgt_port[i] = ensure_port(h, "NORTH")
        # Жёсткая фиксация портов заголовка цикла (шестиугольник):
        #   • ВХОД (не возврат) — строго в ВЕРХНЮЮ вершину (NORTH);
        #   • ВОЗВРАТ (back-edge) — в ЛЕВУЮ (WEST, задаётся выше).
        # Разные грани → вход и обратное ребро не пересекаются.
        if hs == "hexagon" and not back:
            tgt_port[i] = ensure_port(h, "NORTH")
        # Все рёбра в «Конец» входят сверху — так они не пересекаются.
        if h == "end":
            tgt_port[i] = ensure_port("end", "NORTH")

    children = []
    for nid, nd in nodes.items():
        label = nd.get("label", nid)
        w, h  = _node_size(label, nd.get("shape", "box"), nd.get("style", ""))
        entry: Dict[str, Any] = {"id": nid, "width": w, "height": h}
        opts: Dict[str, str] = {}

        ps = ports_by_node.get(nid)
        if ps:
            opts["elk.portConstraints"] = "FIXED_SIDE"
            opts["portLabels.placement"] = "INSIDE"
            # Для ромба/шестиугольника вершина грани — это центр стороны
            # bounding box. Выравниваем порты по центру, чтобы ребро крепилось
            # именно к вершине фигуры, а не скользило вдоль грани.
            shape = nd.get("shape", "box")
            if shape in ("diamond", "hexagon"):
                opts["elk.portAlignment.default"] = "CENTER"
            entry["ports"] = [
                {"id": p["id"], "width": 1, "height": 1,
                 "layoutOptions": {"elk.port.side": p["side"]}}
                for p in ps
            ]

        # «Начало»/вход страницы — в первом слое (вверху); «Конец»/выход на
        # следующую страницу — в последнем слое (всегда в самом низу).
        if nid in ("start", "pgin"):
            opts["elk.layered.layering.layerConstraint"] = "FIRST"
        elif nid in ("end", "pgout"):
            opts["elk.layered.layering.layerConstraint"] = "LAST"

        if opts:
            entry["layoutOptions"] = opts
        children.append(entry)

    edges = []
    for i, ed in enumerate(redges):
        eid = f"e{i}"
        s = src_port.get(i, ed["tail"])
        d = tgt_port.get(i, ed["head"])
        entry = {"id": eid, "sources": [s], "targets": [d]}
        tl = ed.get("taillabel") or ed.get("label")
        if tl:
            entry["labels"] = [{"id": f"{eid}_l", "text": tl,
                                 "width": int(len(tl) * _CW + 8), "height": 16}]
        edges.append(entry)

    # ── Рамки охранников (пунктирный бокс) — БЕЗ контейнеров ──────────────────
    # Узлы помечены 'group'. Чтобы узел-преемник («нет») встал ПОД боксом, а не
    # сбоку (и не попал внутрь рамки), добавляем НЕВИДИМЫЕ рёбра «член группы →
    # преемник» — они задают порядок слоёв (преемник ниже всего бокса), но не
    # рисуются. Рамку рисует _render_svg по bbox узлов группы.
    grp_of = {nid: nd.get("group") for nid, nd in nodes.items() if nd.get("group")}
    has_groups = bool(grp_of)
    if has_groups:
        members_of = {}
        for nid, g in grp_of.items():
            members_of.setdefault(g, []).append(nid)
        inv_id = 0
        for ed in redges:
            gt, gh = grp_of.get(ed["tail"]), grp_of.get(ed["head"])
            if gt and gt != gh:  # выход охранника («нет») к преемнику вне бокса
                for m in members_of[gt]:
                    edges.append({"id": f"inv{inv_id}", "sources": [m],
                                  "targets": [ed["head"]]})
                    inv_id += 1

    opts_all = dict(_ELK_OPTS)
    n = len(nodes)
    # Адаптивная стратегия слоёв:
    #  • небольшие графы (≤70 узлов) — LONGEST_PATH: хвосты ветвей выравниваются
    #    по нижнему слою у точки слияния (читаемо, симметрично);
    #  • крупные — NETWORK_SIMPLEX + повышенная тщательность.
    if n <= 70 and not has_groups:
        opts_all["elk.layered.layering.strategy"] = "LONGEST_PATH"
    else:
        opts_all["elk.layered.layering.strategy"] = "NETWORK_SIMPLEX"
        opts_all["elk.layered.thoroughness"] = "50" if n > 200 else "30"

    return {"id": "root", "layoutOptions": opts_all,
            "children": children, "edges": edges}


# ─────────────────────────────────────────────────────────────────────────────
# Axis-connector mode: insert routing nodes on long bypass edges
# ─────────────────────────────────────────────────────────────────────────────

def _insert_axis_connectors(builder: "GraphBuilder") -> "GraphBuilder":
    """Return a modified GraphBuilder with axis connector routing nodes inserted.

    For each 'нет' bypass edge from a diamond that is NOT a guard-style west
    edge (tailport=w AND headport=w) and whose target is NOT already a close
    merge point (shape='point'), insert an invisible intermediate routing node.

    This splits every long bypass edge into two shorter segments.  ELK's
    LAYER_SWEEP crossing-minimisation works at the level of single layers —
    shorter edges participate in fewer layer-pair comparisons, which lets the
    algorithm find better orderings.  Multiple connector nodes that land in the
    same intermediate layer form an implicit routing 'axis' that bundles all
    bypass traffic into one column, reducing visual cross-threading.
    """
    new = GraphBuilder()
    for nid, nd in builder._nodes.items():
        new._nodes[nid] = dict(nd)

    conn_idx = 0
    for ed in builder._edges:
        src, dst = ed["tail"], ed["head"]
        src_shape = builder._nodes.get(src, {}).get("shape", "box")
        lbl       = (ed.get("taillabel") or ed.get("label") or "").strip()
        is_guard  = ed.get("tailport") == "w" and ed.get("headport") == "w"
        dst_shape = builder._nodes.get(dst, {}).get("shape", "")

        # Target: 'нет' bypass from diamond, not a guard back-edge, not to merge point
        if src_shape == "diamond" and lbl == "нет" and not is_guard and dst_shape != "point":
            cid = f"__axconn_{conn_idx}"
            conn_idx += 1
            # Invisible routing node (2×2 px point)
            new._nodes[cid] = {"label": "", "shape": "point"}
            # First segment keeps the original edge attributes (port, label)
            new._edges.append({**ed, "head": cid})
            # Second segment is a plain edge to the real destination
            new._edges.append({"tail": cid, "head": dst})
        else:
            new._edges.append(dict(ed))

    return new


def _build_elk_json_axis(builder: "GraphBuilder") -> dict:
    """Build ELK JSON with bottom-up (LEFTUP) placement and axis connectors.

    Differences from the standard _build_elk_json:
    • Axis connector routing nodes are inserted on all 'нет' bypass edges.
    • Node placement uses the LEFTUP (bottom-up) Brandes-Köpf variant so that
      node positions are anchored toward the bottom of their layer range —
      which gives the 'bottom-up' visual character.
    • LONGEST_PATH layering is always used (pushes each node as close to the
      sink as possible → nodes accumulate at the bottom → bottom-up feel).
    • Thoroughness is raised to 30 to compensate for the extra connector nodes.
    """
    modified = _insert_axis_connectors(builder)
    result   = _build_elk_json(modified)
    result["layoutOptions"].update({
        # Bottom-up Brandes-Köpf: prefer positions from the bottom of layer range
        "layered.nodePlacement.bk.fixedAlignment":  "LEFTUP",
        # LONGEST_PATH pushes every node as late (as close to sink) as possible
        "elk.layered.layering.strategy":             "LONGEST_PATH",
        # Higher thoroughness because connector nodes increase graph density
        "elk.layered.thoroughness":                  "30",
        "elk.layered.crossingMinimization.greedySwitch.type": "TWO_SIDED",
    })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Node.js discovery
# ─────────────────────────────────────────────────────────────────────────────

def _find_node() -> str:
    """Ищет интерпретатор node.

    На Windows предпочитаем bundled nodejs/node.exe (автономность).
    На Linux/WSL обязательно используем НАТИВНЫЙ node из PATH: запуск Windows
    node.exe под WSL идёт через interop и искажает unix-пути аргументов
    ('/mnt/f/...' → 'F:\\mnt\\f\\...'), из-за чего node не находит elk_layout.js.
    """
    local = third_party("nodejs", "node.exe")
    if sys.platform == "win32" and local.exists():
        return str(local)
    found = shutil.which("node") or shutil.which("node.exe")
    if found:
        return found
    # Последний шанс — bundled node.exe (например, Windows без node в PATH)
    if local.exists():
        return str(local)
    return "node"


# ─────────────────────────────────────────────────────────────────────────────
# Pillow renderer (replaces neato)
# ─────────────────────────────────────────────────────────────────────────────

def _windows_font_candidates() -> list:
    # Use WINDIR so the path is correct even if Windows is installed on D: or E:.
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts = str(Path(windir) / "Fonts")
    return [f"{fonts}/cour.ttf", f"{fonts}/lucon.ttf"]


_FONT_CANDIDATES = [
    *(_windows_font_candidates() if sys.platform == "win32" else []),
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
]

def _load_font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _parse_color(color: str):
    """Конвертирует '#rrggbb' или имя цвета в RGB-кортеж."""
    if color.startswith("#") and len(color) == 7:
        return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
    named = {"white": (255,255,255), "black": (0,0,0), "gray": (128,128,128),
             "lightgray": (211,211,211)}
    return named.get(color, (255, 255, 255))


def _draw_arrowhead(draw, tip: tuple, prev: tuple, size: int = 10):
    """Закрашенный треугольник-стрелка на конце ребра."""
    dx, dy = tip[0] - prev[0], tip[1] - prev[1]
    length = (dx*dx + dy*dy) ** 0.5
    if length < 1:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    half = size * 0.45
    p2 = (int(tip[0] - ux*size - px*half), int(tip[1] - uy*size - py*half))
    p3 = (int(tip[0] - ux*size + px*half), int(tip[1] - uy*size + py*half))
    draw.polygon([tip, p2, p3], fill="black")


def _render_pillow(elk_result: dict, orig_nodes: dict, orig_edges: list,
                   png_path: Path, scale: float = 2.0) -> bool:
    """Рендерит ELK-positioned граф в PNG через Pillow без Graphviz."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("       Pillow not installed")
        return False

    pad = 25  # отступ вокруг графа (в ELK-пикселях до масштабирования)
    total_w = int((elk_result.get("width",  800) + 2 * pad) * scale)
    total_h = int((elk_result.get("height", 600) + 2 * pad) * scale)

    img  = Image.new("RGB", (total_w, total_h), "white")
    draw = ImageDraw.Draw(img)

    font    = _load_font(int(12 * scale))
    font_sm = _load_font(int(11 * scale))
    lw      = max(1, int(1.5 * scale))   # толщина линий

    # Уплощаем иерархию (контейнеры охранников) с накоплением смещений.
    elk_nodes: Dict[str, dict] = {}
    elk_edges: Dict[str, tuple] = {e["id"]: (e, 0.0, 0.0)
                                   for e in elk_result.get("edges", [])}
    containers = []

    def _flatten(children, ox, oy):
        for nd in children:
            ax, ay = ox + nd.get("x", 0), oy + nd.get("y", 0)
            if str(nd.get("id", "")).startswith("cont_"):
                containers.append((ax, ay, ax + nd.get("width", 0), ay + nd.get("height", 0)))
                for e in nd.get("edges", []):
                    elk_edges[e["id"]] = (e, ax, ay)
                _flatten(nd.get("children", []), ax, ay)
            else:
                m = dict(nd); m["x"] = ax; m["y"] = ay
                elk_nodes[nd["id"]] = m
    _flatten(elk_result.get("children", []), 0.0, 0.0)

    def T(x, y):
        return (int((x + pad) * scale), int((y + pad) * scale))

    def Ts(v):
        return max(1, int(v * scale))

    def _node_anchor(nid):
        en = elk_nodes.get(nid)
        if not en:
            return None
        return (en.get("x", 0) + en.get("width", 80) / 2,
                en.get("y", 0) + en.get("height", 36) / 2)

    def _resolve(eid):
        if not eid:
            return None
        if eid in elk_nodes:
            return _node_anchor(eid)
        base = eid
        for suf in ("__p_", "__in", "__out"):
            if suf in base:
                base = base.split(suf)[0]; break
        base = base[len("cont_"):] if base.startswith("cont_") else base
        return _node_anchor(base)

    def _is_boundary(pid):
        return bool(pid) and pid.startswith("cont_") and (pid.endswith("__in") or pid.endswith("__out"))

    # Рамки охранников по bbox узлов группы (в PNG — сплошной серый контур).
    groups = defaultdict(list)
    for nid, nd in orig_nodes.items():
        if nd.get("group") and nid in elk_nodes:
            groups[nd["group"]].append(nid)
    gpad = 10
    for gid, ids in groups.items():
        x0 = min(elk_nodes[i]["x"] for i in ids) - gpad
        y0 = min(elk_nodes[i]["y"] for i in ids) - gpad
        x1 = max(elk_nodes[i]["x"] + elk_nodes[i]["width"] for i in ids) + gpad
        y1 = max(elk_nodes[i]["y"] + elk_nodes[i]["height"] for i in ids) + gpad
        draw.rectangle([T(x0, y0), T(x1, y1)],
                       outline=(136, 136, 136), width=max(1, int(scale)))

    # ── Рёбра — рисуем ДО узлов (невидимые «inv*» пропускаем) ──
    for eid, (elk_ed, eox, eoy) in elk_edges.items():
        if eid.startswith("inv"):
            continue
        secs = elk_ed.get("sections")
        if secs:
            s = secs[0]
            raw = [s["startPoint"]] + list(s.get("bendPoints", [])) + [s["endPoint"]]
            pts = [{"x": p["x"] + eox, "y": p["y"] + eoy} for p in raw]
        else:
            a = _resolve((elk_ed.get("sources") or [None])[0])
            b = _resolve((elk_ed.get("targets") or [None])[0])
            pts = [{"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}] if a and b else []
        if len(pts) < 2:
            continue
        img_pts = [T(p["x"], p["y"]) for p in pts]
        draw.line(img_pts, fill="black", width=lw)
        if not _is_boundary((elk_ed.get("targets") or [""])[0]):
            _draw_arrowhead(draw, img_pts[-1], img_pts[-2], size=Ts(9))
        lbl_list = elk_ed.get("labels", [])
        if lbl_list:
            txt = lbl_list[0].get("text", "")
            if "x" in lbl_list[0]:
                lx, ly = T(lbl_list[0]["x"] + eox, lbl_list[0]["y"] + eoy)
            else:
                lx, ly = img_pts[0][0] + Ts(4), img_pts[0][1] - Ts(14)
            if txt:
                draw.text((lx, ly), txt, fill="black", font=font_sm)

    # ── Узлы ──────────────────────────────────────────────────────────────────
    for nid, en in elk_nodes.items():
        nx, ny = en.get("x", 0), en.get("y", 0)
        nw, nh = en.get("width", 80), en.get("height", 36)

        x0, y0 = T(nx, ny)
        x1, y1 = T(nx + nw, ny + nh)
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2

        on    = orig_nodes.get(nid, {})
        shape = on.get("shape", "box")
        style = on.get("style", "")
        fc    = _parse_color(on.get("fillcolor", "")) if on.get("fillcolor") else (255, 255, 255)
        peri  = int(on.get("peripheries", 1))
        label = (on.get("label", nid) or "").replace("\\n", "\n")

        mid_x, mid_y = cx, cy

        if shape == "diamond":
            poly = [(mid_x, y0), (x1, mid_y), (mid_x, y1), (x0, mid_y)]
            draw.polygon(poly, fill=fc, outline="black")
            draw.polygon(poly, outline="black", width=lw)
        elif shape == "hexagon":
            hw = (x1 - x0) // 5
            poly = [(x0 + hw, y0), (x1 - hw, y0), (x1, mid_y),
                    (x1 - hw, y1), (x0 + hw, y1), (x0, mid_y)]
            draw.polygon(poly, fill=fc, outline="black")
            draw.polygon(poly, outline="black", width=lw)
        elif shape == "parallelogram":
            off = Ts(12)
            poly = [(x0 + off, y0), (x1, y0), (x1 - off, y1), (x0, y1)]
            draw.polygon(poly, fill=fc, outline="black")
            draw.polygon(poly, outline="black", width=lw)
        elif shape == "point":
            r = Ts(3)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="black")
            continue
        elif "rounded" in style:
            r = Ts(8)
            draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fc,
                                   outline="black", width=lw)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=fc, outline="black", width=lw)
            if peri >= 2:
                # ГОСТ 19.701-90 «предопределённый процесс» — вертикальные линии по бокам
                m = Ts(10)
                draw.line([(x0 + m, y0), (x0 + m, y1)], fill="black", width=lw)
                draw.line([(x1 - m, y0), (x1 - m, y1)], fill="black", width=lw)

        # Текст по центру (поддержка многострочных меток)
        if label and shape != "point":
            try:
                bbox = draw.multiline_textbbox((0, 0), label, font=font, align="center")
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.multiline_text((cx - tw // 2, cy - th // 2), label,
                                    fill="black", font=font, align="center")
            except Exception:
                draw.text((cx, cy), label, fill="black", font=font, anchor="mm")

    img.save(str(png_path))
    return True


def _svg_color(color: str) -> str:
    """Возвращает CSS-цвет для SVG (имя/hex как есть, иначе white)."""
    if not color:
        return "white"
    if color.startswith("#") or color.isalpha():
        return color
    return "white"


def _svg_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _render_svg(elk_result: dict, orig_nodes: dict, orig_edges: list,
                svg_path: Path) -> bool:
    """Рендерит ELK-positioned граф в SVG (вектор, текст, компактно).

    Те же фигуры ГОСТ, что и в PNG-рендере, но в разы меньше по размеру и без
    потери качества при масштабировании. Координаты ELK используются 1:1.
    """
    pad = 25
    W = int(elk_result.get("width", 800) + 2 * pad)
    H = int(elk_result.get("height", 600) + 2 * pad)
    def X(v): return v + pad
    def Y(v): return v + pad

    # Уплощаем иерархию: контейнеры (cont_*) дают абсолютную рамку, их дети —
    # абсолютные координаты (+смещение контейнера); внутренние рёбра контейнера
    # тоже со смещением. Корневые узлы/рёбра — как есть.
    elk_nodes: Dict[str, dict] = {}
    elk_edges: Dict[str, tuple] = {e["id"]: (e, 0.0, 0.0)
                                   for e in elk_result.get("edges", [])}
    containers = []  # (x0, y0, x1, y1) абсолютные

    def _flatten(children, ox, oy):
        for nd in children:
            ax, ay = ox + nd.get("x", 0), oy + nd.get("y", 0)
            if str(nd.get("id", "")).startswith("cont_"):
                containers.append((ax, ay, ax + nd.get("width", 0), ay + nd.get("height", 0)))
                for e in nd.get("edges", []):
                    elk_edges[e["id"]] = (e, ax, ay)
                _flatten(nd.get("children", []), ax, ay)
            else:
                m = dict(nd); m["x"] = ax; m["y"] = ay
                elk_nodes[nd["id"]] = m
    _flatten(elk_result.get("children", []), 0.0, 0.0)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="Courier New, monospace" font-size="12">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" '
        'orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L8,3 L0,6 Z" fill="black"/></marker></defs>',
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    # Пунктирные рамки охранников — по bbox узлов группы (преемник вытолкнут
    # вниз невидимыми рёбрами, поэтому в рамку не попадает).
    groups = defaultdict(list)
    for nid, nd in orig_nodes.items():
        if nd.get("group") and nid in elk_nodes:
            groups[nd["group"]].append(nid)
    gpad = 10
    for gid, ids in groups.items():
        x0 = min(elk_nodes[i]["x"] for i in ids) - gpad
        y0 = min(elk_nodes[i]["y"] for i in ids) - gpad
        x1 = max(elk_nodes[i]["x"] + elk_nodes[i]["width"] for i in ids) + gpad
        y1 = max(elk_nodes[i]["y"] + elk_nodes[i]["height"] for i in ids) + gpad
        out.append(f'<rect x="{X(x0):.1f}" y="{Y(y0):.1f}" width="{x1-x0:.1f}" '
                   f'height="{y1-y0:.1f}" rx="6" ry="6" fill="none" stroke="#888" '
                   f'stroke-width="1.2" stroke-dasharray="6,4"/>')

    def _node_anchor(nid):
        en = elk_nodes.get(nid)
        if not en:
            return None
        return (en.get("x", 0) + en.get("width", 80) / 2,
                en.get("y", 0) + en.get("height", 36) / 2)

    def _resolve(eid):
        """Координата конца ребра по id узла/порта (для запасной прямой)."""
        if not eid:
            return None
        if eid in elk_nodes:
            return _node_anchor(eid)
        base = eid
        for suf in ("__p_", "__in", "__out"):
            if suf in base:
                base = base.split(suf)[0]
                break
        base = base[len("cont_"):] if base.startswith("cont_") else base
        return _node_anchor(base)

    def _is_boundary(pid):
        return bool(pid) and pid.startswith("cont_") and (pid.endswith("__in") or pid.endswith("__out"))

    # ── Рёбра (невидимые служебные «inv*» — для раскладки, не рисуем) ──
    for eid, (elk_ed, eox, eoy) in elk_edges.items():
        if eid.startswith("inv"):
            continue
        secs = elk_ed.get("sections")
        if secs:
            s = secs[0]
            raw = [s["startPoint"]] + list(s.get("bendPoints", [])) + [s["endPoint"]]
            pts = [{"x": p["x"] + eox, "y": p["y"] + eoy} for p in raw]
        else:
            a = _resolve((elk_ed.get("sources") or [None])[0])
            b = _resolve((elk_ed.get("targets") or [None])[0])
            pts = [{"x": a[0], "y": a[1]}, {"x": b[0], "y": b[1]}] if a and b else []
        if len(pts) < 2:
            continue
        tgt = (elk_ed.get("targets") or [""])[0]
        marker = "" if _is_boundary(tgt) else ' marker-end="url(#arrow)"'
        d = "M " + " L ".join(f"{X(p['x']):.1f},{Y(p['y']):.1f}" for p in pts)
        out.append(f'<path d="{d}" fill="none" stroke="black" stroke-width="1.5"{marker}/>')
        lbl_list = elk_ed.get("labels", [])
        if lbl_list:
            txt = lbl_list[0].get("text", "")
            if "x" in lbl_list[0]:
                lx, ly = X(lbl_list[0]["x"] + eox), Y(lbl_list[0]["y"] + eoy) + 10
            else:
                lx, ly = X(pts[0]["x"]) + 4, Y(pts[0]["y"]) - 6
            if txt:
                out.append(f'<text x="{lx:.1f}" y="{ly:.1f}">{_svg_escape(txt)}</text>')

    # ── Узлы ──
    for nid, en in elk_nodes.items():
        nx, ny = en.get("x", 0), en.get("y", 0)
        nw, nh = en.get("width", 80), en.get("height", 36)
        x0, y0 = X(nx), Y(ny)
        x1, y1 = X(nx + nw), Y(ny + nh)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        on = orig_nodes.get(nid, {})
        shape = on.get("shape", "box")
        style = on.get("style", "")
        fc = _svg_color(on.get("fillcolor", ""))
        peri = int(on.get("peripheries", 1))
        label = (on.get("label", nid) or "").replace("\\n", "\n")

        if shape == "diamond":
            poly = f"{cx:.1f},{y0:.1f} {x1:.1f},{cy:.1f} {cx:.1f},{y1:.1f} {x0:.1f},{cy:.1f}"
            out.append(f'<polygon points="{poly}" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        elif shape == "hexagon":
            hw = (x1 - x0) / 5
            poly = (f"{x0+hw:.1f},{y0:.1f} {x1-hw:.1f},{y0:.1f} {x1:.1f},{cy:.1f} "
                    f"{x1-hw:.1f},{y1:.1f} {x0+hw:.1f},{y1:.1f} {x0:.1f},{cy:.1f}")
            out.append(f'<polygon points="{poly}" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        elif shape == "parallelogram":
            off = 12
            poly = f"{x0+off:.1f},{y0:.1f} {x1:.1f},{y0:.1f} {x1-off:.1f},{y1:.1f} {x0:.1f},{y1:.1f}"
            out.append(f'<polygon points="{poly}" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        elif shape == "point":
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="black"/>')
            continue
        elif shape == "circle":
            # Соединитель ГОСТ — эллипс по габаритам узла.
            out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{(x1-x0)/2:.1f}" '
                       f'ry="{(y1-y0)/2:.1f}" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        elif shape == "pentagon":
            # Межстраничный соединитель ГОСТ — пятиугольник «домиком» (остриё вниз).
            tip = y1; topb = y0 + (y1 - y0) * 0.45
            poly = (f"{x0:.1f},{y0:.1f} {x1:.1f},{y0:.1f} {x1:.1f},{topb:.1f} "
                    f"{cx:.1f},{tip:.1f} {x0:.1f},{topb:.1f}")
            out.append(f'<polygon points="{poly}" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        elif "rounded" in style:
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}" '
                       f'rx="8" ry="8" fill="{fc}" stroke="black" stroke-width="1.5"/>')
        else:
            out.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}" '
                       f'fill="{fc}" stroke="black" stroke-width="1.5"/>')
            if peri >= 2:  # предопределённый процесс — вертикальные линии по бокам
                m = 10
                out.append(f'<line x1="{x0+m:.1f}" y1="{y0:.1f}" x2="{x0+m:.1f}" y2="{y1:.1f}" stroke="black" stroke-width="1.5"/>')
                out.append(f'<line x1="{x1-m:.1f}" y1="{y0:.1f}" x2="{x1-m:.1f}" y2="{y1:.1f}" stroke="black" stroke-width="1.5"/>')

        if label and shape != "point":
            lines = label.split("\n")
            n_lines = len(lines)
            start_y = cy - (n_lines - 1) * 7 + 4
            for li, ln in enumerate(lines):
                out.append(f'<text x="{cx:.1f}" y="{start_y + li*14:.1f}" '
                           f'text-anchor="middle">{_svg_escape(ln)}</text>')

    out.append("</svg>")
    try:
        svg_path.write_text("\n".join(out), encoding="utf-8")
        return True
    except OSError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ELKFlowchartGenerator
# ─────────────────────────────────────────────────────────────────────────────

class _ElkServer:
    """Постоянный процесс node (`elk_layout.js --server`) для раскладки ELK.

    Убирает запуск node на КАЖДУЮ блок-схему (старт node + загрузка elkjs —
    доминирующая накладная при десятках тысяч схем). Один экземпляр обслуживает
    много графов по протоколу newline-delimited JSON. Не потокобезопасен —
    держим по одному на поток (threading.local). Таймаута нет специально:
    гиганты должны достроиться (их ставят в очередь последними).
    """

    def __init__(self, node_path: str, elk_js: str):
        self._node_path = node_path
        self._elk_js = elk_js
        self.proc = None
        self._start()

    def _start(self):
        # elk_layout.js делает require('elkjs'); node_modules лежит в third-party/,
        # поэтому путь к нему передаём через NODE_PATH (иначе require не найдёт модуль).
        env = {**os.environ, "NODE_PATH": str(third_party("node_modules"))}
        self.proc = subprocess.Popen(
            [self._node_path, self._elk_js, "--server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            env=env,
        )

    def layout(self, graph: dict) -> Optional[dict]:
        # Перезапуск, если процесс умер на предыдущем запросе.
        if self.proc is None or self.proc.poll() is not None:
            self._start()
        try:
            self.proc.stdin.write(json.dumps(graph) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()  # блокирует до ответа (без таймаута)
            if not line:                         # процесс закрыл stdout / упал
                self._start()
                return None
            res = json.loads(line)
            if isinstance(res, dict) and res.get("error"):
                print(f"       elkjs: {str(res['error'])[:200]}")
                return None
            return res
        except Exception as e:
            print(f"       elkjs server exception: {e}")
            try:
                self._start()  # пересоздаём на следующий запрос
            except Exception:
                pass
            return None

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None


class ELKFlowchartGenerator(FlowchartGenerator):
    """
    Replaces Graphviz dot layout with ELK (elkjs + Node.js).
    Rendering still uses Graphviz neato in -n mode (fixed positions).

    Layout algorithm: ELK LAYERED with BRANDES_KOEPF BALANCED node placement.
    This centres the main flow and minimises edge crossings.
    """

    def __init__(self, output_dir: str, db_path: str = None,
                 node_path: str = None, elk_js: str = None,
                 output_format: str = "svg", clear_output: bool = True,
                 fold_guards: bool = False, loop_back_connectors: bool = True,
                 page_size: int = 60, frame_guards: bool = True,
                 axis_mode: bool = False, simplified: bool = False):
        super().__init__(output_dir, db_path, clear_output=clear_output,
                         fold_guards=fold_guards, loop_back_connectors=loop_back_connectors,
                         page_size=page_size, frame_guards=frame_guards,
                         simplified=simplified)
        self._node_path  = node_path or _find_node()
        self._elk_js     = elk_js or str(Path(__file__).parent / "elk_layout.js")
        self.output_format = output_format  # "svg" (вектор) или "png" (растр)
        self._axis_mode  = axis_mode        # True → axis connector + bottom-up layout
        # Пул постоянных node-процессов: по одному на поток (для параллелизма).
        self._elk_tls = threading.local()
        self._elk_servers: List[_ElkServer] = []
        self._elk_lock = threading.Lock()

    def _worker_kwargs(self) -> dict:
        """Доп. аргументы реконструкции для process-pool воркера."""
        d = super()._worker_kwargs()
        d.update(node_path=self._node_path, elk_js=self._elk_js,
                 output_format=self.output_format, axis_mode=self._axis_mode,
                 simplified=self.simplified)
        return d

    # ── ELK runner ───────────────────────────────────────────────────────────

    def _get_elk_server(self) -> _ElkServer:
        """Постоянный node-процесс текущего потока (создаётся лениво)."""
        srv = getattr(self._elk_tls, "server", None)
        if srv is None:
            srv = _ElkServer(self._node_path, self._elk_js)
            self._elk_tls.server = srv
            with self._elk_lock:
                self._elk_servers.append(srv)
        return srv

    def close_elk_servers(self):
        """Останавливает все постоянные node-процессы (после генерации)."""
        with self._elk_lock:
            for srv in self._elk_servers:
                srv.close()
            self._elk_servers.clear()

    def _run_elkjs(self, graph: dict) -> Optional[dict]:
        # Постоянный процесс на поток: без старта node и без temp-файла на каждый вызов.
        return self._get_elk_server().layout(graph)

    # ── Main override ─────────────────────────────────────────────────────────

    @staticmethod
    def _subtree_count(node) -> int:
        c = 1
        for ch in node.get("children", []):
            c += ELKFlowchartGenerator._subtree_count(ch)
        return c

    def _paginate_roots(self, roots: list, page_size: int) -> list:
        """Делит верхнеуровневые операторы на страницы ~page_size узлов.
        Рез только МЕЖДУ операторами — структуры (циклы/if) не разрываются."""
        pages, cur, cum = [], [], 0
        for r in roots:
            rc = self._subtree_count(r)
            if cur and cum + rc > page_size:
                pages.append(cur); cur, cum = [], 0
            cur.append(r); cum += rc
        if cur:
            pages.append(cur)
        return pages or [[]]

    def generate(
        self,
        func_name: str,
        func_num: int,
        stmts,
        func_index: Dict[str, int],
        var_index:  Dict[str, int],
    ) -> str:
        safe = (func_name.replace("::", "_").replace("<", "_").replace(">", "_")
                .replace(" ", "_").replace("(", "_").replace(")", "_")
                .replace("[", "_").replace("]", "_").replace(",", "_").replace("~", "_")
                .replace("*", "_").replace("&", "_").replace("|", "_").replace("?", "_"))
        base = f"{func_num}_{safe}"

        roots = self._build_hierarchy(stmts)
        if self.simplified:
            from viz.flowchart_generator import _simplify_seq
            roots = _simplify_seq(roots)
        page_size = getattr(self, "page_size", 0)
        # Постранично режем только крупные ФО; мелкие — одна схема (без соединителей).
        if page_size and roots and self._subtree_count_list(roots) > page_size:
            pages = self._paginate_roots(roots, page_size)
        else:
            pages = [roots]
        total = len(pages)

        results = []
        for pi, page_roots in enumerate(pages):
            fname = base if total == 1 else f"{base}__p{pi + 1:02d}"
            r = self._render_page(func_name, func_num, page_roots, func_index,
                                  var_index, fname, pi, total)
            if r:
                results.append(r)
        return results[0] if results else ""

    def _subtree_count_list(self, roots: list) -> int:
        return sum(self._subtree_count(r) for r in roots)

    def _render_page(self, func_name, func_num, page_roots, func_index, var_index,
                     fname, pi, total) -> str:
        """Строит и рендерит ОДНУ страницу блок-схемы.

        Стыки страниц — межстраничный соединитель ГОСТ 19.701 (пятиугольник):
        первая страница начинается «Началом», последняя кончается «Концом»,
        промежуточные — соединителями «со стр.K» / «на стр.K»."""
        builder = GraphBuilder(f"ELK {func_name} p{pi + 1}")
        is_first, is_last = (pi == 0), (pi == total - 1)

        if is_first:
            builder.node("start", f"Начало\n({func_num}){func_name}",
                         shape="box", style="rounded,filled", fillcolor="#e8e8e8")
            entry = "start"
        else:
            builder.node("pgin", f"со стр. {pi}", shape="pentagon",
                         style="filled", fillcolor="#fff3e0")
            entry = "pgin"

        if is_last:
            builder.node("end", "Конец", shape="box", style="rounded,filled",
                         fillcolor="#e8e8e8")
            exit_target = "end"
        else:
            builder.node("pgout", f"на стр. {pi + 2}", shape="pentagon",
                         style="filled", fillcolor="#fff3e0")
            exit_target = "pgout"

        if page_roots:
            first_id = self._dot_id(func_name, page_roots[0]["stmt_id"])
            builder.edge(entry, first_id)
            prev = [(first_id, page_roots[0]["stmt_type"])]
            for i, root in enumerate(page_roots):
                nxt = (self._dot_id(func_name, page_roots[i + 1]["stmt_id"])
                       if i + 1 < len(page_roots) else None)
                self._render_node(builder, root, func_name, func_index,
                                  var_index, prev, exit_target, nxt)
            info = prev[0]
            if info:
                pid = info[0] if isinstance(info, tuple) else info
                ptype = info[1] if isinstance(info, tuple) else ""
                if pid and pid not in (exit_target, "end", None, ""):
                    kw = {"tailport": "e"} if ptype in ("while", "for", "do") else {}
                    builder.edge(pid, exit_target, **kw)
        else:
            builder.edge(entry, exit_target)

        # Убираем неиспользуемые узлы выхода (если в них ничего не входит).
        if not any(e["head"] == "end" for e in builder._edges):
            builder._nodes.pop("end", None)
        if not is_last and not any(e["head"] == "pgout" for e in builder._edges):
            builder._nodes.pop("pgout", None)

        elk_in = (_build_elk_json_axis(builder) if self._axis_mode
                  else _build_elk_json(builder))
        elk_out = self._run_elkjs(elk_in)
        if not elk_out:
            print(f"       ELK failed for {func_name} p{pi + 1}", flush=True)
            del elk_in, builder
            return ""

        filepath = self.output_dir / fname
        fmt = getattr(self, "output_format", "svg")
        result = ""
        try:
            if fmt == "png":
                if _render_pillow(elk_out, builder._nodes, builder._edges,
                                  Path(str(filepath) + ".png")):
                    result = f"{fname}.png"
            else:
                if _render_svg(elk_out, builder._nodes, builder._edges,
                               Path(str(filepath) + ".svg")):
                    result = f"{fname}.svg"
        finally:
            del elk_in, elk_out, builder
            gc.collect()
        if not result:
            print(f"       Render failed for {func_name} p{pi + 1}", flush=True)
        return result
