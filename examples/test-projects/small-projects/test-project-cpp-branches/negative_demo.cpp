#include "negative_demo.h"

// switch/case с fallthrough — НЕ отслеживается (0 ветвей).
int weekday_kind(int d) {
    switch (d) {
        case 0:
        case 6:
            return 0;   // выходной
        case 1:
        case 2:
        case 3:
        case 4:
        case 5:
            return 1;   // рабочий
        default:
            return -1;
    }
}

// range-based for — НЕ отслеживается (0 ветвей).
int sum_range(const std::vector<int>& v) {
    int s = 0;
    for (int x : v)         // range-based for — игнорируется
        s += x;
    return s;
}

// тернарный ?: и && / || — НЕ дают ветвей (0 ветвей).
int sign_and_flags(int x, int y) {
    int sign = (x > 0) ? 1 : (x < 0 ? -1 : 0);   // ?: — игнорируется
    bool both = (x > 0) && (y > 0);              // && — игнорируется
    bool any  = (x > 0) || (y > 0);              // || — игнорируется
    return sign + (both ? 10 : 0) + (any ? 100 : 0);
}

// goto — не ветвь. Но управляющий им if — настоящий if и ОТСЛЕЖИВАЕТСЯ (1 ветвь).
int retry_goto(int n) {
    int tries = 0;
again:
    ++tries;
    if (tries < n)          // ветвь #1 (if) — ОТСЛЕЖИВАЕТСЯ; goto — нет
        goto again;
    return tries;
}

// Управление из макроса — исключается (0 ветвей).
#define RETURN_IF_NEG(x) if ((x) < 0) return -1;

int macro_control(int x) {
    RETURN_IF_NEG(x)        // if сгенерирован макросом — игнорируется
    return x * 2;
}

// case-метка из ОДНОГО макровызова разворачивается в НЕСКОЛЬКО независимых
// case (паттерн HotSpot REP8/REP16 в assembler_x86.cpp: `case REP8(0xB8):`
// -> `case (0xB8)+0: case (0xB8)+1: ... case (0xB8)+7:`). Все такие метки
// физически указывают на одно и то же место вызова макроса — надёжного
// отдельного места для датчика КАЖДОЙ из них нет, поэтому они исключаются
// из отслеживания (0 ветвей для CASES4(10), в отличие от обычных меток
// этого же switch, которые отслеживаются как и раньше).
#define CASES4(x) (x)+0: case (x)+1: case (x)+2: case (x)+3

int macro_generated_cases(int op) {
    switch (op) {
        case CASES4(10):    // case-метки из макроса — игнорируются (0 ветвей)
            return 1;
        case 20:            // обычная метка — ОТСЛЕЖИВАЕТСЯ (1 ветвь)
            return 2;
        default:            // ОТСЛЕЖИВАЕТСЯ (1 ветвь)
            return 0;
    }
}
#undef CASES4
