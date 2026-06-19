/**
 * Utils - вспомогательные функции
 */
'use strict';

function factorial(n) {
    if (n < 0) {
        throw new Error('factorial: n must be non-negative');
    }
    if (n <= 1) {
        return 1;
    }
    let result = 1;
    for (let i = 2; i <= n; i++) {
        result *= i;
    }
    return result;
}

function isEven(n) {
    return n % 2 === 0;
}

function sumArray(numbers) {
    let sum = 0;
    for (let i = 0; i < numbers.length; i++) {
        sum += numbers[i];
    }
    return sum;
}

function isPrime(n) {
    if (n <= 1) {
        return false;
    }
    if (n <= 3) {
        return true;
    }
    if (n % 2 === 0 || n % 3 === 0) {
        return false;
    }
    for (let i = 5; i * i <= n; i += 6) {
        if (n % i === 0 || n % (i + 2) === 0) {
            return false;
        }
    }
    return true;
}

function gcd(a, b) {
    while (b !== 0) {
        const temp = b;
        b = a % b;
        a = temp;
    }
    return a;
}

// Неиспользуемая функция (должна попасть в избыточные объекты)
function unusedUtility() {
    let localInUnused = 0;
    localInUnused++;
}

module.exports = { factorial, isEven, sumArray, isPrime, gcd, unusedUtility };
