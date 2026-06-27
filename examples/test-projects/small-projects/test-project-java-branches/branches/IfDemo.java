package branches;

public class IfDemo {

    // 1 отслеживаемая ветвь: then оператора if.
    int simpleIf(int x) {
        int r = 0;
        if (x > 0) {        // ветвь #1 (if)
            r = x;
        }
        return r;
    }

    // 1 отслеживаемая ветвь: then оператора if (else-ветвь — отдельная,
    // см. ifBranch в BranchDemo; здесь намеренно проверяем if БЕЗ else
    // в составе той же ветви: else не дублирует номер if).
    int ifElse(int x) {
        if (x % 2 == 0) {   // ветвь #1 (if)
            return x / 2;
        } else {
            return x * 3 + 1;
        }
    }

    // 4 отслеживаемые ветви: каждый if в цепочке else-if.
    int elseIfChain(int score) {
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
    int nestedIf(int a, int b) {
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
    int ifWithLogical(int x, int y) {
        int r = 0;
        if (x > 0 && y > 0) {   // ветвь #1 (if); && не даёт отдельной ветви
            r = x * y;
        }
        return r;
    }
}
