#ifndef ADVANCED_DEMO_H
#define ADVANCED_DEMO_H

#include <vector>
#include <cstddef>

// Специфические, но реальные формы ветвлений, которые ДОЛЖНЫ отслеживаться.

// --- пустое тело ветви ---
std::size_t cstr_len(const char* s);   // while с пустым телом
int skip_spaces(const char* s);        // for с пустым телом
int classify_empty(int x);             // if с пустым then (заглушка)

// --- идиомы циклов ---
int do_once(int x);                    // do { ... } while (0) (написан руками)
int find_first_zero(const int* a, int n);   // for (;;) { ... break; }
bool is_palindrome(const char* s, int n);    // for с запятыми (встречные индексы)

// --- function-try-block ---
int safe_div(int a, int b);            // int f(...) try { ... } catch (...) { ... }

// --- ветви в lambda ---
int count_positive(const std::vector<int>& v);   // if внутри замыкания

// --- рекурсия (ветвь + маршрут вызовов factorial -> factorial) ---
long factorial(int n);

// --- ветви в шаблонной функции (инструментируется по инстанцированию) ---
template <class T>
T clamp_val(T v, T lo, T hi) {
    if (v < lo) return lo;   // ветвь (if)
    if (v > hi) return hi;   // ветвь (if)
    return v;
}

#endif // ADVANCED_DEMO_H
