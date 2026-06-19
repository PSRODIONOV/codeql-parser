"""Демонстрация потенциально опасных конструкций (ПОК).

Модуль намеренно содержит опасные паттерны разных CWE-категорий.
"""
import os


def run_unsafe_demo(user_input):
    # CWE-095: динамическое исполнение кода через eval
    eval(user_input)

    # CWE-095: динамическое исполнение через exec
    exec(user_input)

    # CWE-078: внедрение команд ОС через os.system
    os.system(user_input)

    # CWE-020: непроверенный пользовательский ввод
    data = input()

    return data


def build_query(table, user_value):
    # CWE-089-подобное: построение SQL конкатенацией (демо)
    query = "SELECT * FROM " + table + " WHERE id = " + user_value
    return _run_query(query)


def _run_query(query):
    return query
