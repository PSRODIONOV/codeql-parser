/**
 * Utils - заголовочный файл
 * Вспомогательные функции
 */

#ifndef UTILS_H
#define UTILS_H

#include <vector>

// Факториал
int factorial(int n);

// Проверка на четность
bool isEven(int n);

// Сумма элементов вектора
int sumVector(const std::vector<int>& numbers);

// Проверка на простое число
bool isPrime(int n);

// НОД двух чисел
int gcd(int a, int b);

// Неиспользуемая функция (для теста избыточных объектов)
void unusedUtility();

#endif // UTILS_H
