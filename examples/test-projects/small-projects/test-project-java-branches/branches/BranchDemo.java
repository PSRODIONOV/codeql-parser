package branches;

public class BranchDemo {
    private final int base;

    public BranchDemo(int base) {
        this.base = base;
    }

    public int ifBranch(int x) {
        if (x > 0) {
            return x + base;
        } else {
            return x - base;
        }
    }

    public int forBranch(int n) {
        int sum = 0;
        for (int i = 0; i < n; i++) {
            sum += i;
        }
        return sum;
    }

    public int whileBranch(int n) {
        int sum = 0;
        while (n > 0) {
            sum += n;
            n--;
        }
        return sum;
    }

    public int tryBranch(int divisor) {
        try {
            return 10 / divisor;
        } catch (ArithmeticException e) {
            return -1;
        }
    }

    // Перегрузка: оба метода называются "helper" -> одинаковый qname в
    // Перечень_ФО ("branches.BranchDemo.helper") - регресс на дисамбигуацию
    // по файлу+строке при сопоставлении точек вставки (см. _lookup_fo в
    // instrument_java.py). Без веток внутри (тернарный оператор не
    // отслеживается как ветвь) - коллизия проверяется только на уровне
    // входа/выхода ФО, без дополнительной неоднозначности по branch-ref_line.
    public String helper() {
        return "no-arg";
    }

    public String helper(int x) {
        return x > 0 ? "positive" : "non-positive";
    }
}
