<?php
/** Обработчик строк — аналог StringProcessor из других малых проектов. */

class StringProcessor {
    private int $processedCount = 0;

    public function toUpper(string $s): string {
        $result = strtoupper($s);
        $this->incrementProcessed();
        return $result;
    }

    public function toLower(string $s): string {
        $result = strtolower($s);
        $this->incrementProcessed();
        return $result;
    }

    public function reverse(string $s): string {
        $result = strrev($s);
        $this->incrementProcessed();
        return $result;
    }

    public function isPalindrome(string $s): bool {
        $reversed = $this->reverse($s);
        return $s === $reversed;
    }

    public function contains(string $s, string $ch): bool {
        $this->incrementProcessed();
        return str_contains($s, $ch);
    }

    public function countChars(string $s, string $ch): int {
        $count = 0;
        for ($i = 0; $i < strlen($s); $i++) {
            if ($s[$i] === $ch) {
                $count++;
            }
        }
        $this->incrementProcessed();
        return $count;
    }

    public function wordCount(string $s): int {
        if ($s === '') {
            return 0;
        }
        $count = 1;
        for ($i = 0; $i < strlen($s); $i++) {
            if ($s[$i] === ' ') {
                $count++;
            }
        }
        return $count;
    }

    private function incrementProcessed(): void {
        $this->processedCount++;
    }
}
