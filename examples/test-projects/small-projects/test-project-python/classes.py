"""Иерархия классов — Shape и Animal (аналог classes из других малых проектов)."""


class Shape:
    """Базовый класс геометрической фигуры."""

    def __init__(self, color="white"):
        self.color = color

    def area(self):
        return 0.0

    def perimeter(self):
        return 0.0

    def describe(self):
        return f"Shape(color={self.color})"


class Circle(Shape):
    """Круг с радиусом."""

    PI = 3.14159265

    def __init__(self, radius, color="white"):
        super().__init__(color)
        self.radius = radius

    def area(self):
        return self.PI * self.radius * self.radius

    def perimeter(self):
        return 2 * self.PI * self.radius

    def describe(self):
        return f"Circle(r={self.radius}, color={self.color})"


class Rectangle(Shape):
    """Прямоугольник с шириной и высотой."""

    def __init__(self, width, height, color="white"):
        super().__init__(color)
        self.width = width
        self.height = height

    def area(self):
        return self.width * self.height

    def perimeter(self):
        return 2 * (self.width + self.height)

    def is_square(self):
        return self.width == self.height

    def describe(self):
        return f"Rectangle({self.width}x{self.height}, color={self.color})"


class Animal:
    """Базовый класс животного."""

    def __init__(self, name, sound):
        self.name = name
        self.sound = sound

    def speak(self):
        return f"{self.name} says {self.sound}"

    def move(self):
        return f"{self.name} moves"


class Dog(Animal):
    """Собака — подкласс Animal."""

    def __init__(self, name):
        super().__init__(name, "Woof")
        self.tricks = []

    def learn_trick(self, trick):
        self.tricks.append(trick)

    def show_tricks(self):
        if not self.tricks:
            return f"{self.name} knows no tricks"
        return f"{self.name} knows: {', '.join(self.tricks)}"
