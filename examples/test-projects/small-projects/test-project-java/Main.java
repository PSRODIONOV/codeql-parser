package testproject;

import java.io.IOException;

/** Главный класс — аналог C++ main.cpp. */
public class Main {

    static int globalCounter = 0;
    static final int MAX_BUFFER = 1024;

    // Неиспользуемый метод (должен попасть в избыточные ФО)
    static void unusedGlobalFunction() {
        int localInUnused = 100;
        System.out.println("This function is never called");
    }

    public static void main(String[] args) {
        System.out.println("=== Test Java Project ===");

        globalCounter++;

        Calculator calc = new Calculator();
        int a = 10, b = 5;

        System.out.println("Add: " + calc.add(a, b));
        System.out.println("Sub: " + calc.sub(a, b));
        System.out.println("Mul: " + calc.mul(a, b));
        System.out.println("Div: " + calc.div(a, b));
        System.out.println("Power: " + calc.power(2, 10));
        System.out.println("Mod: " + calc.mod(17, 5));

        // try-catch #1: перехват отрицательного аргумента факториала
        try {
            int badFact = Utils.factorial(-1);
            System.out.println("Factorial(-1): " + badFact);
        } catch (IllegalArgumentException e) {
            System.out.println("Caught factorial error: " + e.getMessage());
        }

        System.out.println("Factorial of 5: " + Utils.factorial(5));
        System.out.println("Is even(10): " + Utils.isEven(10));
        System.out.println("Is prime(13): " + Utils.isPrime(13));
        System.out.println("GCD(48, 18): " + Utils.gcd(48, 18));

        int[] numbers = {1, 2, 3, 4, 5};
        System.out.println("Sum of array: " + Utils.sumArray(numbers));

        StringProcessor sp = new StringProcessor();
        String text = "Hello World";
        System.out.println("Upper: " + sp.toUpper(text));
        System.out.println("Lower: " + sp.toLower(text));
        System.out.println("Reversed: " + sp.reverse(text));
        System.out.println("Is palindrome: " + sp.isPalindrome("radar"));
        System.out.println("Contains 'o': " + sp.contains(text, 'o'));
        System.out.println("Count 'l': " + sp.countChars(text, 'l'));
        System.out.println("Word count: " + sp.wordCount(text));

        runCounterExample();

        // try-catch #2: перехват ошибок файлового ввода-вывода
        FileStorage storage = new FileStorage();
        try {
            storage.saveCounter(globalCounter);
            int restored = storage.loadCounter();
            System.out.println("Restored counter: " + restored);
            storage.appendLog("Program finished");
            System.out.println("Log contents: " + storage.readLog());
        } catch (IOException e) {
            System.out.println("Caught IO error: " + e.getMessage());
        }
    }

    static void runCounterExample() {
        Counter sender = new Counter(0);
        Counter receiver = new Counter(0);
        for (int i = 0; i < 5; i++) {
            sender.increment();
        }
        System.out.println("Sender value: " + sender.getValue());
        receiver.setValue(sender.getValue());
        System.out.println("Receiver value: " + receiver.getValue());
        sender.reset();
        System.out.println("After reset: " + sender.getValue());
    }
}
