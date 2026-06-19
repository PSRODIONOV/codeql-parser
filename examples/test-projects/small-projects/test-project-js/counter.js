/**
 * Counter - счётчик с событиями (аналог Qt signals/slots)
 */
'use strict';

const EventEmitter = require('events');

const THRESHOLD = 5;

class Counter extends EventEmitter {
    constructor(initial) {
        super();
        this._value = (initial !== undefined) ? initial : 0;
    }

    value() {
        return this._value;
    }

    setValue(newValue) {
        if (this._value === newValue) {
            return;
        }
        this._value = newValue;
        this.emit('valueChanged', this._value);
        if (this._value >= THRESHOLD) {
            this.emit('thresholdReached', THRESHOLD);
        }
    }

    increment() {
        this.setValue(this._value + 1);
    }

    reset() {
        this.setValue(0);
    }
}

module.exports = Counter;
