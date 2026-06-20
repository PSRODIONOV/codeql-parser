#ifndef SINGLE_STMT_DEMO_H
#define SINGLE_STMT_DEMO_H

// Ветвления с ОДИНОЧНЫМ оператором в теле (без фигурных скобок).
// Это отдельный случай для инструментатора: датчик нужно вставлять,
// оборачивая одиночный оператор в блок { ... }.
// Применимо к if / for / while / do (try/catch в C++ всегда требуют {}).

// if с одиночным оператором.
int if_single(int x);

// if / else, обе ветви — одиночные операторы (отслеживается только then).
int if_else_single(int x);

// for с одиночным оператором.
long for_single(int n);

// while с одиночным оператором.
int while_single(int n);

// do-while с одиночным оператором.
int do_single(int n);

// Вложенные одиночные операторы: if внутри for, оба без скобок.
int nested_single(const int* data, int n);

#endif // SINGLE_STMT_DEMO_H
