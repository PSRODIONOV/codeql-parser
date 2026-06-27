package branches;

public class LoopDemo {

    // 1 отслеживаемая ветвь: тело for.
    long sumFor(int n) {
        long s = 0;
        for (int i = 1; i <= n; ++i) {  // ветвь #1 (for)
            s += i;
        }
        return s;
    }

    // 2 отслеживаемые ветви: внешний for + вложенный for.
    int nestedFor(int rows, int cols) {
        int cnt = 0;
        for (int i = 0; i < rows; ++i) {        // ветвь #1 (for, внешний)
            for (int j = 0; j < cols; ++j) {    // ветвь #2 (for, вложенный)
                ++cnt;
            }
        }
        return cnt;
    }

    // 3 отслеживаемые ветви: тело for + два вложенных if (break/continue).
    int forWithBreak(int[] data, int n, int target) {
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
    int countDownWhile(int n) {
        int steps = 0;
        while (n > 0) {     // ветвь #1 (while)
            n /= 2;
            ++steps;
        }
        return steps;
    }

    // 1 отслеживаемая ветвь: тело do-while.
    int doWhileDemo(int n) {
        int acc = 0;
        do {                // ветвь #1 (do)
            acc += n;
            --n;
        } while (n > 0);
        return acc;
    }

    // 2 отслеживаемые ветви: тело while + вложенный if.
    int whileWithIf(int n) {
        int odd = 0;
        while (n > 0) {         // ветвь #1 (while)
            if (n % 2 == 1) {   // ветвь #2 (if)
                ++odd;
            }
            --n;
        }
        return odd;
    }
}
