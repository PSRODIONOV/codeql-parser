/**
 * Calculator - класс калькулятора с базовыми операциями
 */
'use strict';

class Calculator {
    constructor() {
        this.lastResult = 0;
    }

    add(a, b) {
        const result = a + b;
        this._storeResult(result);
        return result;
    }

    sub(a, b) {
        const result = a - b;
        this._storeResult(result);
        return result;
    }

    mul(a, b) {
        const result = a * b;
        this._storeResult(result);
        return result;
    }

    div(a, b) {
        if (b === 0) {
            throw new Error('Division by zero');
        }
        const result = a / b;
        this._storeResult(result);
        return result;
    }

    power(base, exp) {
        let result = 1;
        for (let i = 0; i < exp; i++) {
            result *= base;
        }
        this._storeResult(result);
        return result;
    }

    mod(a, b) {
        if (b === 0) {
            throw new Error('Modulo by zero');
        }
        const result = a % b;
        this._storeResult(result);
        return result;
    }

    _storeResult(result) {
        this.lastResult = result;
    }
}

module.exports = Calculator;
