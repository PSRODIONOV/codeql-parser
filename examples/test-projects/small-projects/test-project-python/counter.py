"""Счётчик с порогом — аналог Counter из других малых проектов."""

THRESHOLD = 10


class Counter:
    """Счётчик, уведомляющий при изменении значения и достижении порога."""

    def __init__(self, initial=0):
        self.value = initial

    def value_changed(self, v):
        pass

    def threshold_reached(self, t):
        pass

    def get_value(self):
        return self.value

    def set_value(self, new_value):
        if self.value == new_value:
            return
        self.value = new_value
        self.value_changed(self.value)
        if self.value >= THRESHOLD:
            self.threshold_reached(THRESHOLD)

    def increment(self):
        self.set_value(self.value + 1)

    def reset(self):
        self.set_value(0)
