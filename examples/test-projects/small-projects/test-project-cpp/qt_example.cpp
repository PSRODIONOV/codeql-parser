#include "counter.h"
#include <iostream>
#include <stdexcept>

/**
 * runCounterExample — демонстрация сигналов/слотов и системного выхода.
 * Два Counter связаны: изменение sender синхронизирует receiver через connect.
 */
void runCounterExample() {
    Counter sender(0);
    Counter receiver(0);

    // Связываем сигнал valueChanged со слотом setValue
    connect(&sender, "valueChanged(int)", &receiver, "setValue(int)");

    // Наращиваем значение — при превышении порога будет сигнал thresholdReached
    for (int i = 0; i < 5; i++) {
        sender.increment();
    }

    std::cout << "Sender value:   " << sender.value()   << std::endl;
    std::cout << "Receiver value: " << receiver.value() << std::endl;

    // Проверяем граничное условие — демонстрация exit
    if (sender.value() < 0) {
        std::cerr << "Fatal: counter underflow" << std::endl;
        exit(1);
    }

    sender.reset();
    std::cout << "After reset: " << sender.value() << std::endl;
}
