/**
 * Test JS Project for CodeQL Analyzer
 * Главный файл программы
 */
'use strict';

const Calculator = require('./calculator');
const { factorial, isEven, isPrime, gcd, sumArray } = require('./utils');
const StringProcessor = require('./stringProcessor');
const Counter = require('./counter');
const { saveCounter, loadCounter, appendLog, readLog } = require('./fileStorage');
const { runUnsafeDemo } = require('./unsafeDemo');

// Глобальные переменные для тестирования анализа
let globalCounter = 0;
const MAX_BUFFER = 1024;

// Неиспользуемая функция (должна попасть в избыточные объекты)
function unusedGlobalFunction() {
    const localInUnused = 100;
    console.log('This function is never called', localInUnused);
}

function runCounterExample() {
    const counter = new Counter(0);
    counter.on('valueChanged', function onValueChanged(val) {
        console.log('Counter value changed:', val);
    });
    counter.on('thresholdReached', function onThreshold(threshold) {
        console.log('Threshold reached:', threshold);
    });
    counter.increment();
    counter.increment();
    counter.increment();
    counter.setValue(10);
    console.log('Counter value:', counter.value());
    counter.reset();
}

function main() {
    console.log('=== Test JS Project ===');

    globalCounter++;

    const calc = new Calculator();

    const a = 10;
    const b = 5;

    console.log('a =', a, ', b =', b);
    console.log('Add:', calc.add(a, b));
    console.log('Sub:', calc.sub(a, b));
    console.log('Mul:', calc.mul(a, b));
    console.log('Div:', calc.div(a, b));
    console.log('Power:', calc.power(2, 10));
    console.log('Mod:', calc.mod(17, 5));

    console.log('Factorial of 5:', factorial(5));
    console.log('Is even(10):', isEven(10));
    console.log('Is prime(13):', isPrime(13));
    console.log('GCD(48, 18):', gcd(48, 18));

    const numbers = [1, 2, 3, 4, 5];
    console.log('Sum of array:', sumArray(numbers));

    const sp = new StringProcessor();
    const text = 'Hello World';
    console.log('Original:', text);
    console.log('Upper:', sp.toUpper(text));
    console.log('Lower:', sp.toLower(text));
    console.log('Reversed:', sp.reverse(text));
    console.log('Is palindrome:', sp.isPalindrome('radar'));
    console.log('Contains o:', sp.contains(text, 'o'));
    console.log('Count l:', sp.countChars(text, 'l'));
    console.log('Word count:', sp.wordCount(text));

    runCounterExample();

    saveCounter(globalCounter);
    const restored = loadCounter();
    console.log('Restored counter:', restored);

    appendLog('Program finished');
    console.log('Log contents:', readLog());

    runUnsafeDemo(process.argv[0]);
}

main();
