<?php
/** Калькулятор — аналог Calculator из других малых проектов. */

class Calculator {
    private int $lastResult = 0;

    public function add(int $a, int $b): int {
        $result = $a + $b;
        $this->storeResult($result);
        return $result;
    }

    public function sub(int $a, int $b): int {
        $result = $a - $b;
        $this->storeResult($result);
        return $result;
    }

    public function mul(int $a, int $b): int {
        $result = $a * $b;
        $this->storeResult($result);
        return $result;
    }

    public function div(int $a, int $b): int {
        if ($b === 0) {
            return 0;
        }
        $result = intdiv($a, $b);
        $this->storeResult($result);
        return $result;
    }

    public function power(int $base, int $exp): int {
        $result = 1;
        for ($i = 0; $i < $exp; $i++) {
            $result *= $base;
        }
        $this->storeResult($result);
        return $result;
    }

    public function mod(int $a, int $b): int {
        if ($b === 0) {
            return 0;
        }
        $result = $a % $b;
        $this->storeResult($result);
        return $result;
    }

    private function storeResult(int $result): int {
        $this->lastResult = $result;
        return $this->lastResult;
    }
}
