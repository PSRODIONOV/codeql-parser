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
