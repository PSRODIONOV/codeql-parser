#include "unsafe_demo.h"

#include <cstring>
#include <cstdlib>
#include <cstdio>

// Модуль намеренно содержит потенциально опасные конструкции (ПОК)
// разных категорий CWE — для демонстрации сигнатурного анализа.
void runUnsafeDemo(const char* userInput) {
    char buf[16];
    strcpy(buf, userInput);             // CWE-120: небезопасное копирование строки

    char cmd[64];
    sprintf(cmd, "echo %s", buf);       // CWE-120: форматирование в буфер без контроля длины

    system(cmd);                        // CWE-078: запуск команды ОС

    printf(userInput);                  // CWE-134: неконтролируемая форматная строка
}
