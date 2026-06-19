<?php
/** Вспомогательные функции — аналог Utils из других малых проектов. */

function factorial(int $n): int {
    if ($n < 0) {
        throw new InvalidArgumentException('factorial: n must be non-negative');
    }
    if ($n <= 1) {
        return 1;
    }
    $result = 1;
    for ($i = 2; $i <= $n; $i++) {
        $result *= $i;
    }
    return $result;
}

function isEven(int $n): bool {
    return $n % 2 === 0;
}

function sumArray(array $numbers): int {
    $total = 0;
    foreach ($numbers as $num) {
        $total += $num;
    }
    return $total;
}

function isPrime(int $n): bool {
    if ($n <= 1) {
        return false;
    }
    if ($n <= 3) {
        return true;
    }
    if ($n % 2 === 0 || $n % 3 === 0) {
        return false;
    }
    $i = 5;
    while ($i * $i <= $n) {
        if ($n % $i === 0 || $n % ($i + 2) === 0) {
            return false;
        }
        $i += 6;
    }
    return true;
}

function gcd(int $a, int $b): int {
    while ($b !== 0) {
        [$a, $b] = [$b, $a % $b];
    }
    return $a;
}

function unusedUtility(): void {
    $localInUnused = 0;
    $localInUnused++;
}
