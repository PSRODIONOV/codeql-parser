/**
 * Test C++ Project for CodeQL Analyzer
 * Главный файл программы
 */

#include <iostream>
#include <vector>
#include "calculator.h"
#include "utils.h"
#include "string_processor.h"
#include "counter.h"
#include "file_storage.h"
#include "unsafe_demo.h"

void runCounterExample();

// Глобальные переменные для тестирования анализа
int globalCounter = 0;
static int staticGlobal = 42;
const int MAX_BUFFER = 1024;

// Неиспользуемая функция (должна попасть в избыточные объекты)
void unusedGlobalFunction() {
    int localInUnused = 100;
    std::cout << "This function is never called" << std::endl;
}

int main(int argc, char* argv[]) {
    std::cout << "=== Test C++ Project ===" << std::endl;
    
    // Используем глобальную переменную
    globalCounter++;
    
    // Создаем калькулятор
    Calculator calc;
    
    // Тестовые вычисления
    int a = 10, b = 5;
    
    std::cout << "a = " << a << ", b = " << b << std::endl;
    std::cout << "Add: " << calc.add(a, b) << std::endl;
    std::cout << "Sub: " << calc.sub(a, b) << std::endl;
    std::cout << "Mul: " << calc.mul(a, b) << std::endl;
    std::cout << "Div: " << calc.div(a, b) << std::endl;
    std::cout << "Power: " << calc.power(2, 10) << std::endl;
    std::cout << "Mod: " << calc.mod(17, 5) << std::endl;

    // try-catch #1: перехват деления на ноль
    try {
        double result = calc.div(a, 0);
        std::cout << "Div by zero: " << result << std::endl;
    } catch (const std::invalid_argument& e) {
        std::cout << "Caught div error: " << e.what() << std::endl;
    }

    // Тест утилит
    // try-catch #2: перехват отрицательного аргумента факториала
    try {
        int f = factorial(-1);
        std::cout << "Factorial(-1): " << f << std::endl;
    } catch (const std::invalid_argument& e) {
        std::cout << "Caught factorial error: " << e.what() << std::endl;
    }
    std::cout << "Factorial of 5: " << factorial(5) << std::endl;
    std::cout << "Is even(10): " << isEven(10) << std::endl;
    std::cout << "Is prime(13): " << isPrime(13) << std::endl;
    std::cout << "GCD(48, 18): " << gcd(48, 18) << std::endl;
    
    // Тест вектора
    std::vector<int> numbers = {1, 2, 3, 4, 5};
    std::cout << "Sum of vector: " << sumVector(numbers) << std::endl;
    
    // Тест обработчика строк
    StringProcessor sp;
    std::string text = "Hello World";
    std::cout << "Original: " << text << std::endl;
    std::cout << "Upper: " << sp.toUpper(text) << std::endl;
    std::cout << "Lower: " << sp.toLower(text) << std::endl;
    std::cout << "Reversed: " << sp.reverse(text) << std::endl;
    std::cout << "Is palindrome: " << sp.isPalindrome("radar") << std::endl;
    std::cout << "Contains 'o': " << sp.contains(text, 'o') << std::endl;
    std::cout << "Count 'l': " << sp.countChars(text, 'l') << std::endl;
    std::cout << "Word count: " << sp.wordCount(text) << std::endl;

    // Тест сигналов/слотов (Qt-стиль)
    runCounterExample();

    // Тест файлового ввода-вывода: данные циркулируют через файлы
    saveCounter(globalCounter);
    int restored = loadCounter();
    std::cout << "Restored counter: " << restored << std::endl;

    appendLog("Program finished");
    std::cout << "Log contents: " << readLog() << std::endl;

    // Демонстрация потенциально опасных конструкций (ПОК)
    runUnsafeDemo(argv[0]);

    return 0;
}
