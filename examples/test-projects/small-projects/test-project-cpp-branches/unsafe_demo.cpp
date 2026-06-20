#include "unsafe_demo.h"
#include <cstring>
#include <cstdio>
#include <cstdlib>

// Без ветвлений: только опасные вызовы для сигнатурного анализа (ПОК).
void run_unsafe(const char* src) {
    char buf[64];
    strcpy(buf, src);                       // CWE-120 (небезопасное копирование)
    char cmd[128];
    sprintf(cmd, "echo %s", buf);           // CWE-120 (нет границы буфера)
    system(cmd);                            // CWE-078 (внедрение команд ОС)
    printf(buf);                            // CWE-134 (неконстантная строка формата)
}
