/**
 * Utils - реализация вспомогательных функций
 */

#include "utils.h"
#include <cstddef>
#include <stdexcept>

int factorial(int n) {
    if (n < 0) {
        throw std::invalid_argument("factorial: n must be non-negative");
    }
    if (n <= 1) {
        return 1;
    }
    int result = 1;
    for (int i = 2; i <= n; i++) {
        result *= i;
    }
    return result;
}

bool isEven(int n) {
    return n % 2 == 0;
}

int sumVector(const std::vector<int>& numbers) {
    int sum = 0;
    for (size_t i = 0; i < numbers.size(); i++) {
        sum += numbers[i];
    }
    return sum;
}

bool isPrime(int n) {
    if (n <= 1) {
        return false;
    }
    if (n <= 3) {
        return true;
    }
    if (n % 2 == 0 || n % 3 == 0) {
        return false;
    }
    for (int i = 5; i * i <= n; i += 6) {
        if (n % i == 0 || n % (i + 2) == 0) {
            return false;
        }
    }
    return true;
}

int gcd(int a, int b) {
    while (b != 0) {
        int temp = b;
        b = a % b;
        a = temp;
    }
    return a;
}

void unusedUtility() {
    int localInUnused = 0;
    localInUnused++;
}
