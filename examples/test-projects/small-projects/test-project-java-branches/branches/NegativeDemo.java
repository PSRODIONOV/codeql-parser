package branches;

import java.util.List;

public class NegativeDemo {

    // enhanced-for (for-each) — НЕ отслеживается (0 ветвей), паритет с
    // range-based for в C++ (см. negative_demo.cpp::sum_range): итерация
    // "для каждого элемента" не содержит точки решения.
    int sumRange(List<Integer> v) {
        int s = 0;
        for (int x : v) {       // enhanced-for — игнорируется
            s += x;
        }
        return s;
    }

    // тернарный ?: и && / || — НЕ дают ветвей (0 ветвей).
    int signAndFlags(int x, int y) {
        int sign = (x > 0) ? 1 : (x < 0 ? -1 : 0);   // ?: — игнорируется
        boolean both = (x > 0) && (y > 0);           // && — игнорируется
        boolean any  = (x > 0) || (y > 0);           // || — игнорируется
        return sign + (both ? 10 : 0) + (any ? 100 : 0);
    }

    // 2 отслеживаемые ветви: тело while + вложенный if. labeled break сам
    // не ветвь (как и goto в negative_demo.cpp::retry_goto), но управляющие
    // им while/if — настоящие ветви и ОТСЛЕЖИВАЮТСЯ.
    int retryLabeled(int n) {
        int tries = 0;
        outer:
        while (true) {          // ветвь #1 (while)
            ++tries;
            if (tries >= n) {   // ветвь #2 (if)
                break outer;    // labeled break — не ветвь
            }
        }
        return tries;
    }
}
