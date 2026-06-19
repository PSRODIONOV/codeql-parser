// ogdf_layout.cpp — мост к OGDF: граф (stdin) -> координаты (stdout).
// Планаризационная ортогональная раскладка (минимизация пересечений).
//
// Протокол stdin (числа через пробел/перевод строки):
//   <n>                      число узлов
//   <i> <w> <h>   (n строк)  индекс узла (0..n-1), ширина, высота
//   <m>                      число рёбер
//   <a> <b>       (m строк)  ребро: индексы узлов
//
// Протокол stdout:
//   NODES <n>
//   <i> <x> <y> <w> <h>      (x,y — ЦЕНТР узла)
//   EDGES <m>
//   <a> <b> <k> x1 y1 ... xk yk   (k изломов между a и b; может быть 0)
#include <ogdf/basic/Graph.h>
#include <ogdf/basic/GraphAttributes.h>
#include <ogdf/planarity/PlanarizationLayout.h>
#include <ogdf/layered/SugiyamaLayout.h>
#include <ogdf/layered/OptimalRanking.h>
#include <ogdf/layered/MedianHeuristic.h>
#include <ogdf/layered/OptimalHierarchyLayout.h>
#include <ogdf/upward/UpwardPlanarizationLayout.h>
#include <vector>
#include <cstring>
#include <cstdio>

using namespace ogdf;

// argv[1] = режим раскладки: planar (по умолч.) | sugiyama | upward
int main(int argc, char** argv) {
    const char* mode = (argc > 1) ? argv[1] : "planar";
    int n = 0;
    if (scanf("%d", &n) != 1) return 1;
    Graph G;
    GraphAttributes GA(G, GraphAttributes::nodeGraphics | GraphAttributes::edgeGraphics);
    std::vector<node> nd(n);
    for (int i = 0; i < n; ++i) nd[i] = G.newNode();
    for (int i = 0; i < n; ++i) {
        int idx; double w, h;
        if (scanf("%d %lf %lf", &idx, &w, &h) != 3) return 1;
        GA.width(nd[idx])  = w;
        GA.height(nd[idx]) = h;
    }
    int m = 0;
    if (scanf("%d", &m) != 1) return 1;
    std::vector<std::pair<int,int>> es(m);
    std::vector<edge> ed(m);
    for (int i = 0; i < m; ++i) {
        int a, b;
        if (scanf("%d %d", &a, &b) != 2) return 1;
        es[i] = {a, b};
        ed[i] = G.newEdge(nd[a], nd[b]);
    }

    try {
        if (strcmp(mode, "sugiyama") == 0) {
            // Иерархическая (слоистая) — сохраняет направление сверху-вниз.
            SugiyamaLayout SL;
            SL.setRanking(new OptimalRanking);
            SL.setCrossMin(new MedianHeuristic);
            OptimalHierarchyLayout* ohl = new OptimalHierarchyLayout;
            ohl->layerDistance(40.0);
            ohl->nodeDistance(30.0);
            SL.setLayout(ohl);
            SL.call(GA);
        } else if (strcmp(mode, "upward") == 0) {
            // Планаризация С СОХРАНЕНИЕМ направления рёбер (upward).
            UpwardPlanarizationLayout upl;
            upl.call(GA);
        } else {
            PlanarizationLayout pl;       // чистая планаризация (мин. пересечений)
            pl.call(GA);
        }
    } catch (...) {
        return 2;
    }

    printf("NODES %d\n", n);
    for (int i = 0; i < n; ++i)
        printf("%d %.2f %.2f %.2f %.2f\n", i, GA.x(nd[i]), GA.y(nd[i]),
               GA.width(nd[i]), GA.height(nd[i]));
    printf("EDGES %d\n", m);
    for (int i = 0; i < m; ++i) {
        const DPolyline &bends = GA.bends(ed[i]);
        printf("%d %d %d", es[i].first, es[i].second, (int)bends.size());
        for (const DPoint &p : bends) printf(" %.2f %.2f", p.m_x, p.m_y);
        printf("\n");
    }
    return 0;
}
