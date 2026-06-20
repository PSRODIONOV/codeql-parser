#ifndef ONELINE_DEMO_H
#define ONELINE_DEMO_H

// Однострочные ветвления: заголовок оператора И его тело на ОДНОЙ строке.
// Проверяются оба варианта — с фигурными скобками и без них.
// Это отдельный случай для инструментатора: место вставки датчика
// (начало тела) совпадает по строке с заголовком ветви.

// --- без фигурных скобок (тело — одиночный оператор на той же строке) ---
int if_oneline_nobrace(int x);

// --- if/else в одну строку, разные комбинации скобок ---
// (отслеживается только then-ветвь; else не отслеживается)
int if_else_oneline_nn(int x);  // if op1;        else op2;
int if_else_oneline_bb(int x);  // if { op1; }    else { op2; }
int if_else_oneline_nb(int x);  // if op1;        else { op2; }
int if_else_oneline_bn(int x);  // if { op1; }    else op2;
long for_oneline_nobrace(int n);
int while_oneline_nobrace(int n);
int do_oneline_nobrace(int n);

// --- с фигурными скобками на той же строке ---
int if_oneline_brace(int x);
long for_oneline_brace(int n);
int while_oneline_brace(int n);
int do_oneline_brace(int n);
int try_oneline_brace(int x);

// --- вложенные однострочные ---
int nested_oneline(const int* data, int n);

#endif // ONELINE_DEMO_H
