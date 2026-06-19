#include "file_storage.h"

#include <fstream>
#include <sstream>
#include <string>

// Запись значения в файл "counter.dat" через выходной файловый поток.
void saveCounter(int value) {
    std::ofstream ofs("counter.dat");
    ofs << value << std::endl;
    ofs.close();
}

// Чтение значения из файла "counter.dat" через входной файловый поток.
int loadCounter() {
    std::ifstream ifs("counter.dat");
    int value = 0;
    ifs >> value;
    ifs.close();
    return value;
}

// Дозапись сообщения в журнал "app.log".
void appendLog(const std::string& message) {
    std::ofstream log("app.log", std::ios::app);
    log << message << std::endl;
    log.close();
}

// Чтение всего журнала "app.log".
std::string readLog() {
    std::ifstream log("app.log");
    std::stringstream buffer;
    buffer << log.rdbuf();
    log.close();
    return buffer.str();
}
