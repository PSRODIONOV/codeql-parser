#include "loop_demo.h"

// 1 отслеживаемая ветвь: тело for.
long sum_for(int n) {
    long s = 0;
    for (int i = 1; i <= n; ++i) {  // ветвь #1 (for)
        s += i;
    }
    return s;
}

// 2 отслеживаемые ветви: внешний for + вложенный for.
int nested_for(int rows, int cols) {
    int cnt = 0;
    for (int i = 0; i < rows; ++i) {        // ветвь #1 (for, внешний)
        for (int j = 0; j < cols; ++j) {    // ветвь #2 (for, вложенный)
            ++cnt;
        }
    }
    return cnt;
}

// 2 отслеживаемые ветви: тело for + вложенный if.
int for_with_break(const int* data, int n, int target) {
    int idx = -1;
    for (int i = 0; i < n; ++i) {   // ветвь #1 (for)
        if (data[i] == target) {    // ветвь #2 (if)
            idx = i;
            break;
        }
        if (data[i] < 0) {          // ветвь #3 (if)
            continue;
        }
    }
    return idx;
}

// 1 отслеживаемая ветвь: тело while.
int count_down_while(int n) {
    int steps = 0;
    while (n > 0) {     // ветвь #1 (while)
        n /= 2;
        ++steps;
    }
    return steps;
}

// 1 отслеживаемая ветвь: тело do-while.
int do_while_demo(int n) {
    int acc = 0;
    do {                // ветвь #1 (do)
        acc += n;
        --n;
    } while (n > 0);
    return acc;
}

// 2 отслеживаемые ветви: тело while + вложенный if.
int while_with_if(int n) {
    int odd = 0;
    while (n > 0) {         // ветвь #1 (while)
        if (n % 2 == 1) {   // ветвь #2 (if)
            ++odd;
        }
        --n;
    }
    return odd;
}
