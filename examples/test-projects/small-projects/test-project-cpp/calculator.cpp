/**
 * Calculator - реализация
 */

#include "calculator.h"
#include <stdexcept>

Calculator::Calculator() : lastResult(0) {
}

Calculator::~Calculator() {
}

int Calculator::add(int a, int b) {
    int result = a + b;
    storeResult(result);
    return result;
}

int Calculator::sub(int a, int b) {
    int result = a - b;
    storeResult(result);
    return result;
}

int Calculator::mul(int a, int b) {
    int result = a * b;
    storeResult(result);
    return result;
}

double Calculator::div(int a, int b) {
    if (b == 0) {
        throw std::invalid_argument("Division by zero");
    }
    double result = static_cast<double>(a) / b;
    storeResult(static_cast<int>(result));
    return result;
}

int Calculator::power(int base, int exp) {
    int result = 1;
    for (int i = 0; i < exp; i++) {
        result *= base;
    }
    storeResult(result);
    return result;
}

int Calculator::mod(int a, int b) {
    if (b == 0) {
        throw std::invalid_argument("Modulo by zero");
    }
    int result = a % b;
    storeResult(result);
    return result;
}

void Calculator::storeResult(int result) {
    lastResult = result;
}
