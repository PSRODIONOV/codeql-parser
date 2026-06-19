package testproject;

import java.io.IOException;

/** Демонстрация потенциально опасных конструкций (ПОК) для этапа 1. */
public class UnsafeDemo {

    public void runUnsafeDemo(String userInput) throws IOException {
        // CWE-078: запуск команды ОС с непроверенным вводом
        Runtime.getRuntime().exec(userInput);

        // CWE-078: запуск через командный интерпретатор
        Runtime.getRuntime().exec("sh -c " + userInput);

        // CWE-089-подобное: построение строки запроса конкатенацией (демо)
        String query = "SELECT * FROM users WHERE name = '" + userInput + "'";
        runQuery(query);
    }

    private void runQuery(String query) {
        // заглушка
    }
}
