"""Калькулятор — аналог Calculator из других малых проектов."""


class Calculator:
    """Простой целочисленный калькулятор с запоминанием последнего результата."""

    def __init__(self):
        self.last_result = 0

    def add(self, a, b):
        result = a + b
        self._store_result(result)
        return result

    def sub(self, a, b):
        result = a - b
        self._store_result(result)
        return result

    def mul(self, a, b):
        result = a * b
        self._store_result(result)
        return result

    def div(self, a, b):
        if b == 0:
            return 0
        result = a // b
        self._store_result(result)
        return result

    def power(self, base, exp):
        result = 1
        for _ in range(exp):
            result *= base
        self._store_result(result)
        return result

    def mod(self, a, b):
        if b == 0:
            return 0
        result = a % b
        self._store_result(result)
        return result

    def _store_result(self, result):
        self.last_result = result
        return self.last_result
