#ifndef EXCEPTION_DEMO_H
#define EXCEPTION_DEMO_H

#include <string>

// Демонстрация ветвлений на основе try.
// probe_points.ql отслеживает try-блок (тело try) как ветвь.
// catch-блоки НЕ отслеживаются как отдельные ветви.

// Простой try / catch.
int simple_try(int x);

// try с несколькими catch.
int try_multiple_catch(int code);

// Вложенные try.
int nested_try(int x);

// Регресс бага #8: while(...) try {...} catch(...) {...} без {} вокруг while.
int while_try_no_brace(int n);

// try + цикл + if внутри try-блока (комбинация ветвей).
int try_with_loop(const std::string& s);

#endif // EXCEPTION_DEMO_H
