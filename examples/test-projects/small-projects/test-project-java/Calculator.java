package testproject;

/** Калькулятор — аналог C++ Calculator. */
public class Calculator {
    private int lastResult;

    public Calculator() {
        lastResult = 0;
    }

    public int add(int a, int b) {
        int result = a + b;
        storeResult(result);
        return result;
    }

    public int sub(int a, int b) {
        int result = a - b;
        storeResult(result);
        return result;
    }

    public int mul(int a, int b) {
        int result = a * b;
        storeResult(result);
        return result;
    }

    public int div(int a, int b) {
        if (b == 0) {
            return 0;
        }
        int result = a / b;
        storeResult(result);
        return result;
    }

    public int power(int base, int exp) {
        int result = 1;
        for (int i = 0; i < exp; i++) {
            result *= base;
        }
        storeResult(result);
        return result;
    }

    public int mod(int a, int b) {
        if (b == 0) {
            return 0;
        }
        int result = a % b;
        storeResult(result);
        return result;
    }

    public int storeResult(int result) {
        lastResult = result;
        return lastResult;
    }
}
