"""Обработчик строк — аналог StringProcessor из других малых проектов."""


class StringProcessor:
    """Класс для базовых операций над строками."""

    def __init__(self):
        self.processed_count = 0

    def to_upper(self, s):
        result = s.upper()
        self._increment_processed()
        return result

    def to_lower(self, s):
        result = s.lower()
        self._increment_processed()
        return result

    def reverse(self, s):
        result = s[::-1]
        self._increment_processed()
        return result

    def is_palindrome(self, s):
        reversed_s = self.reverse(s)
        return s == reversed_s

    def contains(self, s, ch):
        self._increment_processed()
        return ch in s

    def count_chars(self, s, ch):
        count = 0
        for c in s:
            if c == ch:
                count += 1
        self._increment_processed()
        return count

    def word_count(self, s):
        if not s:
            return 0
        count = 1
        for ch in s:
            if ch == ' ':
                count += 1
        return count

    def _increment_processed(self):
        self.processed_count += 1
