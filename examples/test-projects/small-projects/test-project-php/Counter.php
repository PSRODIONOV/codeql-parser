<?php
/** Счётчик с порогом — аналог Counter из других малых проектов. */

define('THRESHOLD', 10);

class Counter {
    private int $value;

    public function __construct(int $initial = 0) {
        $this->value = $initial;
    }

    public function valueChanged(int $v): void {
        // hook: вызывается при изменении значения
    }

    public function thresholdReached(int $t): void {
        // hook: вызывается при достижении порога
    }

    public function getValue(): int {
        return $this->value;
    }

    public function setValue(int $newValue): void {
        if ($this->value === $newValue) {
            return;
        }
        $this->value = $newValue;
        $this->valueChanged($this->value);
        if ($this->value >= THRESHOLD) {
            $this->thresholdReached(THRESHOLD);
        }
    }

    public function increment(): void {
        $this->setValue($this->value + 1);
    }

    public function reset(): void {
        $this->setValue(0);
    }
}
