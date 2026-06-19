"""Файловое хранилище — аналог FileStorage из других малых проектов."""


class FileStorage:
    """Хранит счётчик и лог в текстовых файлах."""

    def save_counter(self, value):
        f = open("counter.dat", "w")
        f.write(str(value))
        f.close()

    def load_counter(self):
        f = open("counter.dat", "r")
        value = int(f.read())
        f.close()
        return value

    def append_log(self, message):
        f = open("app.log", "a")
        f.write(message + "\n")
        f.close()

    def read_log(self):
        f = open("app.log", "r")
        line = f.readline()
        f.close()
        return line
