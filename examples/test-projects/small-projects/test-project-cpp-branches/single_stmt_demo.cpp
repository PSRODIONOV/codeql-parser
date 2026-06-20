#include "single_stmt_demo.h"

// 1 отслеживаемая ветвь: then-оператор if без скобок.
int if_single(int x) {
    int r = 0;
    if (x > 0)          // ветвь #1 (if), тело — одиночный оператор
        r = x * 2;
    return r;
}

// 1 отслеживаемая ветвь: then оператора if без скобок
// (else-ветвь не отслеживается).
int if_else_single(int x) {
    int r;
    if (x % 2 == 0)     // ветвь #1 (if), одиночный оператор
        r = x / 2;
    else
        r = x * 3 + 1;
    return r;
}

// 1 отслеживаемая ветвь: тело for без скобок.
long for_single(int n) {
    long s = 0;
    for (int i = 1; i <= n; ++i)    // ветвь #1 (for), одиночный оператор
        s += i;
    return s;
}

// 1 отслеживаемая ветвь: тело while без скобок.
int while_single(int n) {
    int steps = 0;
    while (n > 1)       // ветвь #1 (while), одиночный оператор
        n /= 2, ++steps;
    return steps;
}

// 1 отслеживаемая ветвь: тело do-while без скобок.
int do_single(int n) {
    int acc = 0;
    do
        acc += n--;     // ветвь #1 (do), одиночный оператор
    while (n > 0);
    return acc;
}

// 2 отслеживаемые ветви: тело for и вложенный if — оба без скобок.
int nested_single(const int* data, int n) {
    int positive = 0;
    for (int i = 0; i < n; ++i)     // ветвь #1 (for), одиночный оператор
        if (data[i] > 0)            // ветвь #2 (if), одиночный оператор
            ++positive;
    return positive;
}
