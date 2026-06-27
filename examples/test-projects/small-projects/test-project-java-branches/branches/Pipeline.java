package branches;

import java.util.List;

public class Pipeline {
    private final int threshold;

    public Pipeline(int threshold) {
        this.threshold = threshold;
    }

    // 1 отслеживаемая ветвь: then if.
    boolean aboveThreshold(int v) {
        if (v > threshold) {   // ветвь #1 (if)
            return true;
        }
        return false;
    }

    // 2 отслеживаемые ветви: тело for + вложенный if.
    // Маршрут вызовов: classify -> aboveThreshold.
    int classify(List<Integer> data) {
        int hits = 0;
        for (int i = 0; i < data.size(); ++i) {     // ветвь #1 (for)
            if (aboveThreshold(data.get(i))) {      // ветвь #2 (if)
                ++hits;
            }
        }
        return hits;
    }

    // 2 отслеживаемые ветви: тело while + тело do-while.
    int normalize(int value) {
        int steps = 0;
        while (value > 100) {       // ветвь #1 (while)
            value -= 100;
            ++steps;
        }
        do {                        // ветвь #2 (do)
            value += 1;
        } while (value < 0);
        return value + steps;
    }

    // 3 отслеживаемые ветви: тело try + 2 вложенных if.
    // Маршрут вызовов: process -> classify (-> aboveThreshold), process -> normalize.
    int process(List<Integer> data) {
        try {                                       // ветвь #1 (try)
            if (data.isEmpty()) {                   // ветвь #2 (if)
                throw new IllegalArgumentException("empty data");
            }
            int hits = classify(data);
            int norm = normalize(data.size());
            if (hits > norm) {                      // ветвь #3 (if)
                return hits;
            }
            return norm;
        } catch (RuntimeException e) {
            return -1;
        }
    }
}
