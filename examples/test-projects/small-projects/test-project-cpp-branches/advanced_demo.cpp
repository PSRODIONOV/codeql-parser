#include "advanced_demo.h"
#include <stdexcept>

// 1 ветвь (while): тело пустое.
std::size_t cstr_len(const char* s) {
    const char* p = s;
    while (*p++) ;                  // ветвь #1 (while), пустое тело
    return static_cast<std::size_t>(p - s - 1);
}

// 1 ветвь (for): тело пустое.
int skip_spaces(const char* s) {
    int i = 0;
    for (; s[i] == ' '; ++i) ;      // ветвь #1 (for), пустое тело
    return i;
}

// 1 ветвь (if): then-ветвь пустая (намеренная заглушка), else не отслеживается.
int classify_empty(int x) {
    int r = 0;
    if (x > 0) ;                    // ветвь #1 (if), пустой then
    else r = -x;
    return r;
}

// 2 ветви: тело do (#1) + вложенный if (#2). do-while(0) написан руками.
int do_once(int x) {
    int r = 0;
    do {                           // ветвь #1 (do)
        if (x < 0) break;          // ветвь #2 (if)
        r = x * x;
    } while (0);
    return r;
}

// 3 ветви: тело for (#1) + два вложенных if (#2, #3). Бесконечный for с break.
int find_first_zero(const int* a, int n) {
    int i = 0;
    for (;;) {                     // ветвь #1 (for)
        if (i >= n) return -1;     // ветвь #2 (if)
        if (a[i] == 0) return i;   // ветвь #3 (if)
        ++i;
    }
}

// 2 ветви: тело for (#1) + вложенный if (#2). for с запятыми (встречные индексы).
bool is_palindrome(const char* s, int n) {
    for (int i = 0, j = n - 1; i < j; ++i, --j) {   // ветвь #1 (for)
        if (s[i] != s[j]) return false;             // ветвь #2 (if)
    }
    return true;
}

// 2 ветви: тело function-try-block (#1, try) + вложенный if (#2).
int safe_div(int a, int b) try {            // ветвь #1 (try) — function-try-block
    if (b == 0)                             // ветвь #2 (if)
        throw std::runtime_error("div by zero");
    return a / b;
} catch (const std::exception&) {
    return 0;
}

// 2 ветви: тело for (#1) в count_positive + if (#2) в теле lambda (operator()).
int count_positive(const std::vector<int>& v) {
    auto pred = [](int x) {
        if (x > 0) return 1;       // ветвь (if) — на operator() замыкания
        return 0;
    };
    int c = 0;
    for (std::size_t i = 0; i < v.size(); ++i)   // ветвь (for)
        c += pred(v[i]);
    return c;
}

// 1 ветвь (if) + маршрут вызовов factorial -> factorial (рекурсия).
long factorial(int n) {
    if (n <= 1) return 1;          // ветвь #1 (if)
    return n * factorial(n - 1);
}
