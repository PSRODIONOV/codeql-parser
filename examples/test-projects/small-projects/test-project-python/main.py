"""Точка входа — аналог main из других малых проектов."""
from calculator import Calculator
from counter import Counter
from string_processor import StringProcessor
from file_storage import FileStorage
from utils import factorial, is_even, is_prime, gcd, sum_array

GLOBAL_COUNTER = 0
MAX_BUFFER = 1024


def unused_global_function():
    local_in_unused = 100
    print("This function is never called")


def main():
    global GLOBAL_COUNTER
    print("=== Test Python Project ===")

    GLOBAL_COUNTER += 1

    calc = Calculator()
    a, b = 10, 5

    print("Add:", calc.add(a, b))
    print("Sub:", calc.sub(a, b))
    print("Mul:", calc.mul(a, b))
    print("Div:", calc.div(a, b))
    print("Power:", calc.power(2, 10))
    print("Mod:", calc.mod(17, 5))

    # try/except #1: перехват ошибки при отрицательном факториале
    try:
        bad_fact = factorial(-1)
        print("Factorial(-1):", bad_fact)
    except ValueError as e:
        print("Caught factorial error:", e)

    print("Factorial of 5:", factorial(5))
    print("Is even(10):", is_even(10))
    print("Is prime(13):", is_prime(13))
    print("GCD(48, 18):", gcd(48, 18))

    numbers = [1, 2, 3, 4, 5]
    print("Sum of array:", sum_array(numbers))

    sp = StringProcessor()
    text = "Hello World"
    print("Upper:", sp.to_upper(text))
    print("Lower:", sp.to_lower(text))
    print("Reversed:", sp.reverse(text))
    print("Is palindrome:", sp.is_palindrome("radar"))
    print("Contains 'o':", sp.contains(text, "o"))
    print("Count 'l':", sp.count_chars(text, "l"))
    print("Word count:", sp.word_count(text))

    _run_counter_example()

    # try/except #2: перехват ошибок файлового ввода-вывода
    storage = FileStorage()
    try:
        storage.save_counter(GLOBAL_COUNTER)
        restored = storage.load_counter()
        print("Restored counter:", restored)
        storage.append_log("Program finished")
        print("Log contents:", storage.read_log())
    except OSError as e:
        print("Caught IO error:", e)


def _run_counter_example():
    sender = Counter(0)
    receiver = Counter(0)
    for _ in range(5):
        sender.increment()
    print("Sender value:", sender.get_value())
    receiver.set_value(sender.get_value())
    print("Receiver value:", receiver.get_value())
    sender.reset()
    print("After reset:", sender.get_value())


if __name__ == "__main__":
    main()
