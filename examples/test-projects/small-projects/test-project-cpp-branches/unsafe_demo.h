#ifndef UNSAFE_DEMO_H
#define UNSAFE_DEMO_H

// Опасные конструкции (ПОК) для проверки сигнатурного анализа:
// strcpy/sprintf (CWE-120), system (CWE-078), printf с внешней строкой (CWE-134).
// Ветвей здесь НЕТ — файл влияет только на сигнатурный анализ, не на счёт ветвей.
void run_unsafe(const char* src);

#endif // UNSAFE_DEMO_H
