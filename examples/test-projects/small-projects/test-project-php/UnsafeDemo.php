<?php
/** Демонстрация потенциально опасных конструкций (ПОК).
 *  Модуль намеренно содержит опасные паттерны разных CWE-категорий.
 */

function runUnsafeDemo(string $userInput): string {
    // CWE-095: динамическое исполнение кода через eval
    eval($userInput);

    // CWE-078: внедрение команд ОС через system()
    system($userInput);

    // CWE-020: непроверенный пользовательский ввод через $_GET
    $data = $_GET['input'] ?? '';

    return $data;
}

function buildQuery(string $table, string $userValue): string {
    // CWE-089: построение SQL конкатенацией без параметризации
    $query = "SELECT * FROM " . $table . " WHERE id = " . $userValue;
    return runQuery($query);
}

function runQuery(string $query): string {
    return $query;
}
