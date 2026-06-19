#ifndef FILE_STORAGE_H
#define FILE_STORAGE_H

#include <string>

// Сохранение/загрузка значения через файл "counter.dat".
// saveCounter записывает, loadCounter читает — обмен данными через файл.
void saveCounter(int value);
int loadCounter();

// Журналирование в файл "app.log" (запись) и его чтение.
void appendLog(const std::string& message);
std::string readLog();

#endif // FILE_STORAGE_H
