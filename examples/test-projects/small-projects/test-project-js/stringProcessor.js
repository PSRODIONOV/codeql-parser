/**
 * StringProcessor - обработчик строк
 */
'use strict';

class StringProcessor {
    constructor() {
        this.processedCount = 0;
    }

    toUpper(str) {
        const result = str.toUpperCase();
        this._incrementProcessed();
        return result;
    }

    toLower(str) {
        const result = str.toLowerCase();
        this._incrementProcessed();
        return result;
    }

    reverse(str) {
        const result = str.split('').reverse().join('');
        this._incrementProcessed();
        return result;
    }

    isPalindrome(str) {
        const reversed = this.reverse(str);
        return str === reversed;
    }

    contains(str, char) {
        this._incrementProcessed();
        return str.includes(char);
    }

    countChars(str, char) {
        let count = 0;
        for (let i = 0; i < str.length; i++) {
            if (str[i] === char) {
                count++;
            }
        }
        this._incrementProcessed();
        return count;
    }

    wordCount(str) {
        if (str.length === 0) {
            return 0;
        }
        let count = 1;
        for (let i = 0; i < str.length; i++) {
            if (str[i] === ' ') {
                count++;
            }
        }
        this._incrementProcessed();
        return count;
    }

    _incrementProcessed() {
        this.processedCount++;
    }
}

module.exports = StringProcessor;
