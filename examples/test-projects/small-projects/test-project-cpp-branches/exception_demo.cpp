#include "exception_demo.h"
#include <stdexcept>

// 1 отслеживаемая ветвь: тело try.
int simple_try(int x) {
    int r = -1;
    try {                       // ветвь #1 (try)
        if (x < 0) {            // ветвь #2 (if) — внутри try-блока
            throw std::runtime_error("negative");
        }
        r = x * 2;
    } catch (const std::exception&) {
        r = 0;
    }
    return r;
}

// 1 отслеживаемая ветвь: тело try (несколько catch не дают доп. ветвей).
int try_multiple_catch(int code) {
    try {                               // ветвь #1 (try)
        if (code == 1) {                // ветвь #2 (if)
            throw std::invalid_argument("bad arg");
        }
        if (code == 2) {                // ветвь #3 (if)
            throw std::out_of_range("oor");
        }
        if (code == 3) {                // ветвь #4 (if)
            throw std::runtime_error("rt");
        }
        return 100;
    } catch (const std::invalid_argument&) {
        return 1;
    } catch (const std::out_of_range&) {
        return 2;
    } catch (const std::exception&) {
        return 3;
    }
}

// 2 отслеживаемые ветви: внешний try + вложенный try.
int nested_try(int x) {
    int r = 0;
    try {                       // ветвь #1 (try, внешний)
        try {                   // ветвь #2 (try, вложенный)
            if (x == 0) {       // ветвь #3 (if)
                throw std::runtime_error("zero");
            }
            r = 1000 / x;
        } catch (const std::exception&) {
            throw;              // переброс наружу
        }
    } catch (const std::exception&) {
        r = -1;
    }
    return r;
}

// Регресс бага #8: while(...) try { ... } catch (...) { ... } БЕЗ своих {}
// вокруг тела while (тело while — это сам TryStmt). CodeQL для TryStmt.
// getLocation() даёт конец ТОЛЬКО try-блока, не включая catch-обработчик,
// поэтому закрывающая '}' обёртки одиночного оператора (has_block=0) могла
// попасть ПРЯМО ПЕРЕД catch — он оставался "осиротевшим" вне фигурных
// скобок while, и сборка ломалась. Прототип: GDAL/RIK rikdataset.cpp
// (RIKRasterBand::IReadBlock — while(...) try {...} catch(...) {...}).
// 4 отслеживаемые ветви: while (тело — try), try, if, catch.
int while_try_no_brace(int n) {
    int total = 0;
    int i = 0;
    while (i < n)                  // ветвь #1 (while), тело — TryStmt без {}
    try {                           // ветвь #2 (try)
        if (i == 2) {               // ветвь #3 (if)
            throw std::runtime_error("skip");
        }
        total += i;
        ++i;
    } catch (const std::exception&) { // ветвь #4 (catch)
        ++i;                         // пропустить проблемный элемент
    }
    return total;
}

// 3 отслеживаемые ветви: тело try + тело for + вложенный if.
int try_with_loop(const std::string& s) {
    int vowels = 0;
    try {                                       // ветвь #1 (try)
        for (size_t i = 0; i < s.size(); ++i) { // ветвь #2 (for)
            char c = s[i];
            if (c == 'a' || c == 'e' || c == 'i' ||
                c == 'o' || c == 'u') {         // ветвь #3 (if)
                ++vowels;
            }
        }
        if (vowels == 0) {                      // ветвь #4 (if)
            throw std::runtime_error("no vowels");
        }
    } catch (const std::exception&) {
        return -1;
    }
    return vowels;
}
