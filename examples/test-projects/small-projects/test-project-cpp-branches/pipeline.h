#ifndef PIPELINE_H
#define PIPELINE_H

#include <vector>
#include <string>

// Класс-конвейер: методы вызывают друг друга и сторонние функции,
// чтобы получить разнообразные МАРШРУТЫ ВЫЗОВОВ (call routes), а также
// смешанные ветви всех отслеживаемых типов внутри методов.
class Pipeline {
public:
    explicit Pipeline(int threshold);

    // Метод с if + for: классифицирует элементы.
    int classify(const std::vector<int>& data);

    // Метод с while + do-while.
    int normalize(int value);

    // Метод с try + вложенными ветвями; вызывает classify и normalize
    // (формирует маршрут вызовов: process -> classify, process -> normalize).
    int process(const std::vector<int>& data);

private:
    int threshold_;

    // Приватный помощник (вызывается из classify) — для маршрута вызовов.
    bool above_threshold(int v) const;
};

#endif // PIPELINE_H
