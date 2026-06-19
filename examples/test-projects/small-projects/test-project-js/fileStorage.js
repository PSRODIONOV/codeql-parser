/**
 * FileStorage - файловое хранилище (аналог file_storage.cpp)
 */
'use strict';

const fs = require('fs');

// Запись значения в файл "counter.dat"
function saveCounter(value) {
    fs.writeFileSync('counter.dat', String(value));
}

// Чтение значения из файла "counter.dat"
function loadCounter() {
    try {
        const data = fs.readFileSync('counter.dat', 'utf8');
        return parseInt(data, 10) || 0;
    } catch (e) {
        return 0;
    }
}

// Дозапись сообщения в журнал "app.log"
function appendLog(message) {
    fs.appendFileSync('app.log', message + '\n');
}

// Чтение всего журнала "app.log"
function readLog() {
    try {
        return fs.readFileSync('app.log', 'utf8');
    } catch (e) {
        return '';
    }
}

module.exports = { saveCounter, loadCounter, appendLog, readLog };
