#ifndef LOOP_DEMO_H
#define LOOP_DEMO_H

// Демонстрация ветвлений на основе циклов.
// probe_points.ql отслеживает тело цикла как ветвь для:
//   for, while, do-while.
// Диапазонный for (range-based for) НЕ отслеживается.

// Классический for.
long sum_for(int n);

// Вложенные for.
int nested_for(int rows, int cols);

// for с break / continue (сами break/continue не дают ветвей,
// но тело for — отслеживается).
int for_with_break(const int* data, int n, int target);

// while.
int count_down_while(int n);

// do-while (тело выполняется хотя бы раз).
int do_while_demo(int n);

// Цикл while + вложенный if (комбинация: 2 ветви).
int while_with_if(int n);

#endif // LOOP_DEMO_H
