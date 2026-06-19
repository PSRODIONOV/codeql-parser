/**
 * Classes - тестовые классы (аналог classes.cpp)
 */
'use strict';

let staticField = 0;

class MyClass {
    constructor(val) {
        this.field = val;
    }

    doWork() {
        this.field++;
        staticField++;
        console.log('Working:', this.field);
    }

    unusedMethod() {
        console.log('Never called');
    }
}

class DataProcessor {
    constructor() {
        this.buffer = new Array(10).fill(0);
    }

    process(data) {
        this.buffer[0] = data;
        console.log('Processing:', data);
    }
}

module.exports = { MyClass, DataProcessor };
