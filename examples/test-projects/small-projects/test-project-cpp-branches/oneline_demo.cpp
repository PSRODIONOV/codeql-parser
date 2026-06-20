#include "oneline_demo.h"
#include <stdexcept>

// ============ без фигурных скобок, всё в одну строку ============

// 1 ветвь (if): заголовок и тело на одной строке, без скобок.
int if_oneline_nobrace(int x) {
    int r = 0;
    if (x > 0) r = x * 2;                       // ветвь #1 (if)
    return r;
}

// --- if/else в одну строку, разные комбинации скобок ---
// Во всех вариантах отслеживается только then-ветвь (ветвь #1, if);
// else-ветвь не отслеживается.

// then без скобок, else без скобок.
int if_else_oneline_nn(int x) {
    int r;
    if (x % 2 == 0) r = x / 2; else r = x * 3 + 1;   // ветвь #1 (if)
    return r;
}

// then со скобками, else со скобками.
int if_else_oneline_bb(int x) {
    int r;
    if (x % 2 == 0) { r = x / 2; } else { r = x * 3 + 1; }   // ветвь #1 (if)
    return r;
}

// then без скобок, else со скобками.
int if_else_oneline_nb(int x) {
    int r;
    if (x % 2 == 0) r = x / 2; else { r = x * 3 + 1; }   // ветвь #1 (if)
    return r;
}

// then со скобками, else без скобок.
int if_else_oneline_bn(int x) {
    int r;
    if (x % 2 == 0) { r = x / 2; } else r = x * 3 + 1;   // ветвь #1 (if)
    return r;
}

// 1 ветвь (for): всё в одну строку, без скобок.
long for_oneline_nobrace(int n) {
    long s = 0;
    for (int i = 1; i <= n; ++i) s += i;        // ветвь #1 (for)
    return s;
}

// 1 ветвь (while): всё в одну строку, без скобок (тело — оператор-запятая).
int while_oneline_nobrace(int n) {
    int steps = 0;
    while (n > 1) n /= 2, ++steps;              // ветвь #1 (while)
    return steps;
}

// 1 ветвь (do): всё в одну строку, без скобок.
int do_oneline_nobrace(int n) {
    int acc = 0;
    do acc += n--; while (n > 0);               // ветвь #1 (do)
    return acc;
}

// ============ с фигурными скобками, всё в одну строку ============

// 1 ветвь (if): заголовок, { тело } — одной строкой.
int if_oneline_brace(int x) {
    int r = 0;
    if (x > 0) { r = x * 2; }                   // ветвь #1 (if)
    return r;
}

// 1 ветвь (for): одной строкой со скобками.
long for_oneline_brace(int n) {
    long s = 0;
    for (int i = 1; i <= n; ++i) { s += i; }    // ветвь #1 (for)
    return s;
}

// 1 ветвь (while): одной строкой со скобками.
int while_oneline_brace(int n) {
    int steps = 0;
    while (n > 1) { n /= 2; ++steps; }          // ветвь #1 (while)
    return steps;
}

// 1 ветвь (do): одной строкой со скобками.
int do_oneline_brace(int n) {
    int acc = 0;
    do { acc += n--; } while (n > 0);           // ветвь #1 (do)
    return acc;
}

// 1 ветвь (try): try { ... } catch (...) { ... } одной строкой.
int try_oneline_brace(int x) {
    try { if (x < 0) throw std::runtime_error("neg"); return x; }  // ветвь #1 (try) + #2 (if)
    catch (const std::exception&) { return -1; }
}

// 2 ветви (for + вложенный if): обе однострочные.
int nested_oneline(const int* data, int n) {
    int positive = 0;
    for (int i = 0; i < n; ++i) if (data[i] > 0) ++positive;   // ветвь #1 (for), #2 (if)
    return positive;
}
