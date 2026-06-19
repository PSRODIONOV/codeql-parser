/**
 * Calculator - заголовочный файл
 * Класс калькулятора с базовыми операциями
 */

#ifndef CALCULATOR_H
#define CALCULATOR_H

class Calculator {
public:
    Calculator();
    ~Calculator();
    
    // Базовые операции
    int add(int a, int b);
    int sub(int a, int b);
    int mul(int a, int b);
    double div(int a, int b);
    
    // Дополнительные операции
    int power(int base, int exp);
    int mod(int a, int b);
    
private:
    int lastResult;
    void storeResult(int result);
};

#endif // CALCULATOR_H
