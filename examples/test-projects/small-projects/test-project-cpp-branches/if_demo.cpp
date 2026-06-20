#include "if_demo.h"

// 1 отслеживаемая ветвь: then оператора if.
int simple_if(int x) {
    int r = 0;
    if (x > 0) {        // ветвь #1 (if)
        r = x;
    }
    return r;
}

// 1 отслеживаемая ветвь: then оператора if (else-ветвь не отслеживается).
int if_else(int x) {
    if (x % 2 == 0) {   // ветвь #1 (if)
        return x / 2;
    } else {
        return x * 3 + 1;
    }
}

// 4 отслеживаемые ветви: каждый if в цепочке else-if.
int else_if_chain(int score) {
    if (score >= 90) {          // ветвь #1 (if)
        return 5;
    } else if (score >= 75) {   // ветвь #2 (if)
        return 4;
    } else if (score >= 60) {   // ветвь #3 (if)
        return 3;
    } else if (score >= 40) {   // ветвь #4 (if)
        return 2;
    }
    return 1;
}

// 3 отслеживаемые ветви: внешний if + два вложенных if.
int nested_if(int a, int b) {
    int r = 0;
    if (a > 0) {            // ветвь #1 (if, внешний)
        if (b > 0) {        // ветвь #2 (if, вложенный)
            r = a + b;
        }
        if (b < 0) {        // ветвь #3 (if, вложенный)
            r = a - b;
        }
    }
    return r;
}

// 1 отслеживаемая ветвь: then оператора if со сложным условием.
int if_with_logical(int x, int y) {
    int r = 0;
    if (x > 0 && y > 0) {   // ветвь #1 (if); && не дает отдельной ветви
        r = x * y;
    }
    return r;
}
