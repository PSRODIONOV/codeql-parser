#ifndef NEGATIVE_DEMO_H
#define NEGATIVE_DEMO_H

#include <vector>

// Конструкции, которые НЕ должны отслеживаться probe_points.ql.
// Это регрессионные сторожа: после инструментации они НЕ должны давать
// записей в Перечень_ветвей.csv (см. README — раздел про negative_demo).

// switch / case (в т.ч. fallthrough) — не ветвь для инструментатора.
int weekday_kind(int d);

// range-based for — не отслеживается (в отличие от обычного for).
int sum_range(const std::vector<int>& v);

// тернарный ?: и логические && / || — не дают ветвей.
int sign_and_flags(int x, int y);

// goto — не ветвь. ВНИМАНИЕ: управляющий им if — ОТСЛЕЖИВАЕТСЯ (это if).
int retry_goto(int n);

// Управление, сгенерированное макросом, — исключается из отслеживания.
int macro_control(int x);

// case-метки, сгенерированные ОДНИМ макровызовом (паттерн REP8/REP16) —
// исключаются из отслеживания; обычные метки того же switch — нет.
int macro_generated_cases(int op);

#endif // NEGATIVE_DEMO_H
