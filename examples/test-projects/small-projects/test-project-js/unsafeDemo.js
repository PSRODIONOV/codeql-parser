/**
 * UnsafeDemo - демонстрация потенциально опасных конструкций (ПОК)
 * Модуль намеренно содержит опасные паттерны разных категорий CWE
 */
'use strict';

const { exec } = require('child_process');

function runUnsafeDemo(userInput) {
    // CWE-078: Внедрение команд ОС
    exec('echo ' + userInput, function execCallback(err, stdout) {
        if (!err) {
            console.log(stdout);
        }
    });

    // CWE-095: Динамическое исполнение кода через eval
    eval('console.log("' + userInput + '")');

    // CWE-095: Динамическое создание функции
    const fn = new Function('x', 'return ' + userInput);
    fn(userInput);

    // CWE-079: Небезопасная вставка HTML (имитация DOM)
    const element = { innerHTML: '' };
    element.innerHTML = userInput;
}

module.exports = { runUnsafeDemo };
