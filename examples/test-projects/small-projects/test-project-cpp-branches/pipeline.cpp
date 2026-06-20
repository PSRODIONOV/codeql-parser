#include "pipeline.h"
#include <stdexcept>

Pipeline::Pipeline(int threshold) : threshold_(threshold) {}

// 1 отслеживаемая ветвь: then if.
bool Pipeline::above_threshold(int v) const {
    if (v > threshold_) {   // ветвь #1 (if)
        return true;
    }
    return false;
}

// 2 отслеживаемые ветви: тело for + вложенный if.
// Маршрут вызовов: classify -> above_threshold.
int Pipeline::classify(const std::vector<int>& data) {
    int hits = 0;
    for (size_t i = 0; i < data.size(); ++i) {  // ветвь #1 (for)
        if (above_threshold(data[i])) {         // ветвь #2 (if)
            ++hits;
        }
    }
    return hits;
}

// 2 отслеживаемые ветви: тело while + тело do-while.
int Pipeline::normalize(int value) {
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
// Маршрут вызовов: process -> classify (-> above_threshold), process -> normalize.
int Pipeline::process(const std::vector<int>& data) {
    try {                                   // ветвь #1 (try)
        if (data.empty()) {                 // ветвь #2 (if)
            throw std::invalid_argument("empty data");
        }
        int hits = classify(data);
        int norm = normalize(static_cast<int>(data.size()));
        if (hits > norm) {                  // ветвь #3 (if)
            return hits;
        }
        return norm;
    } catch (const std::exception&) {
        return -1;
    }
}
