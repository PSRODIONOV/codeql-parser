"""Вспомогательные функции — аналог Utils из других малых проектов."""


def factorial(n):
    if n < 0:
        raise ValueError("factorial: n must be non-negative")
    if n <= 1:
        return 1
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def is_even(n):
    return n % 2 == 0


def sum_array(numbers):
    total = 0
    for num in numbers:
        total += num
    return total


def is_prime(n):
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def gcd(a, b):
    while b != 0:
        a, b = b, a % b
    return a


def unused_utility():
    local_in_unused = 0
    local_in_unused += 1
