package testproject;

/** Счётчик с порогом — аналог C++ Counter (сигналы заменены вызовами-заглушками). */
public class Counter {
    private int value;
    private static final int THRESHOLD = 10;

    public Counter(int initial) {
        value = initial;
    }

    public void valueChanged(int v) {}

    public void thresholdReached(int t) {}

    public int getValue() {
        return value;
    }

    public void setValue(int newValue) {
        if (value == newValue) {
            return;
        }
        value = newValue;
        valueChanged(value);
        if (value >= THRESHOLD) {
            thresholdReached(THRESHOLD);
        }
    }

    public void increment() {
        setValue(value + 1);
    }

    public void reset() {
        setValue(0);
    }
}
