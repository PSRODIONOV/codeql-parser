#ifndef IF_DEMO_H
#define IF_DEMO_H

// Демонстрация ветвлений на основе оператора if во всех формах,
// которые отслеживает инструментатор (probe_points.ql отслеживает
// then-ветвь оператора if).

// Простой if без else.
int simple_if(int x);

// if / else.
int if_else(int x);

// Цепочка else-if (each `if` дает отдельную точку ветвления).
int else_if_chain(int score);

// Вложенные if-ы.
int nested_if(int a, int b);

// if внутри условия с логическими операторами (&&/|| НЕ отслеживаются
// как отдельные ветви, но then-ветвь самого if — отслеживается).
int if_with_logical(int x, int y);

#endif // IF_DEMO_H
