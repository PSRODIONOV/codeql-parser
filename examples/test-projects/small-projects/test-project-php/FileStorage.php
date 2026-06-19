<?php
/** Файловое хранилище — аналог FileStorage из других малых проектов. */

class FileStorage {

    public function saveCounter(int $value): void {
        $f = fopen('counter.dat', 'w');
        fwrite($f, (string)$value);
        fclose($f);
    }

    public function loadCounter(): int {
        $f = fopen('counter.dat', 'r');
        $value = (int)fread($f, 64);
        fclose($f);
        return $value;
    }

    public function appendLog(string $message): void {
        $f = fopen('app.log', 'a');
        fwrite($f, $message . "\n");
        fclose($f);
    }

    public function readLog(): string {
        $f = fopen('app.log', 'r');
        $line = fgets($f);
        fclose($f);
        return $line !== false ? $line : '';
    }
}
