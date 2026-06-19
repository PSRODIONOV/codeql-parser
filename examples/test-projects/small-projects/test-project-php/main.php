<?php
/** Точка входа — аналог main из других малых проектов. */

require_once __DIR__ . '/Calculator.php';
require_once __DIR__ . '/Counter.php';
require_once __DIR__ . '/StringProcessor.php';
require_once __DIR__ . '/FileStorage.php';
require_once __DIR__ . '/Utils.php';

define('GLOBAL_COUNTER_INIT', 0);
$globalCounter = GLOBAL_COUNTER_INIT;

function unusedGlobalFunction(): void {
    $localInUnused = 100;
    echo "This function is never called\n";
}

function main(): void {
    global $globalCounter;
    echo "=== Test PHP Project ===\n";

    $globalCounter++;

    $calc = new Calculator();
    $a = 10;
    $b = 5;

    echo 'Add: '   . $calc->add($a, $b)       . "\n";
    echo 'Sub: '   . $calc->sub($a, $b)       . "\n";
    echo 'Mul: '   . $calc->mul($a, $b)       . "\n";
    echo 'Div: '   . $calc->div($a, $b)       . "\n";
    echo 'Power: ' . $calc->power(2, 10)      . "\n";
    echo 'Mod: '   . $calc->mod(17, 5)        . "\n";

    // try/catch #1: перехват ошибки при отрицательном факториале
    try {
        $badFact = factorial(-1);
        echo 'Factorial(-1): ' . $badFact . "\n";
    } catch (InvalidArgumentException $e) {
        echo 'Caught factorial error: ' . $e->getMessage() . "\n";
    }

    echo 'Factorial of 5: ' . factorial(5)       . "\n";
    echo 'Is even(10): '    . (isEven(10) ? 'true' : 'false') . "\n";
    echo 'Is prime(13): '   . (isPrime(13) ? 'true' : 'false') . "\n";
    echo 'GCD(48, 18): '    . gcd(48, 18)        . "\n";

    $numbers = [1, 2, 3, 4, 5];
    echo 'Sum of array: ' . sumArray($numbers) . "\n";

    $sp   = new StringProcessor();
    $text = 'Hello World';
    echo 'Upper: '       . $sp->toUpper($text)          . "\n";
    echo 'Lower: '       . $sp->toLower($text)          . "\n";
    echo 'Reversed: '    . $sp->reverse($text)          . "\n";
    echo 'Is palindrome: ' . ($sp->isPalindrome('radar') ? 'true' : 'false') . "\n";
    echo "Contains 'o': "  . ($sp->contains($text, 'o') ? 'true' : 'false') . "\n";
    echo "Count 'l': "     . $sp->countChars($text, 'l') . "\n";
    echo 'Word count: '    . $sp->wordCount($text)       . "\n";

    runCounterExample();

    // try/catch #2: перехват ошибок файлового ввода-вывода
    $storage = new FileStorage();
    try {
        $storage->saveCounter($globalCounter);
        $restored = $storage->loadCounter();
        echo 'Restored counter: ' . $restored . "\n";
        $storage->appendLog('Program finished');
        echo 'Log contents: ' . $storage->readLog() . "\n";
    } catch (Exception $e) {
        echo 'Caught IO error: ' . $e->getMessage() . "\n";
    }
}

function runCounterExample(): void {
    $sender   = new Counter(0);
    $receiver = new Counter(0);
    for ($i = 0; $i < 5; $i++) {
        $sender->increment();
    }
    echo 'Sender value: '   . $sender->getValue() . "\n";
    $receiver->setValue($sender->getValue());
    echo 'Receiver value: ' . $receiver->getValue() . "\n";
    $sender->reset();
    echo 'After reset: '    . $sender->getValue() . "\n";
}

main();
