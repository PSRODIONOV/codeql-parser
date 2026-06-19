package testproject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;

/** Файловое хранилище — аналог C++ file_storage. Данные циркулируют через файлы. */
public class FileStorage {

    // Сохраняет значение счётчика в файл (запись в файл — ИО-файл)
    public void saveCounter(int value) throws IOException {
        BufferedWriter writer = new BufferedWriter(new FileWriter("counter.dat"));
        writer.write(Integer.toString(value));
        writer.close();
    }

    // Загружает значение счётчика из файла (чтение из файла)
    public int loadCounter() throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader("counter.dat"));
        int value = Integer.parseInt(reader.readLine());
        reader.close();
        return value;
    }

    // Дописывает строку в лог-файл (запись в файл)
    public void appendLog(String message) throws IOException {
        BufferedWriter writer = new BufferedWriter(new FileWriter("app.log", true));
        writer.write(message);
        writer.newLine();
        writer.close();
    }

    // Читает первую строку из лог-файла (чтение из файла)
    public String readLog() throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader("app.log"));
        String line = reader.readLine();
        reader.close();
        return line;
    }
}
