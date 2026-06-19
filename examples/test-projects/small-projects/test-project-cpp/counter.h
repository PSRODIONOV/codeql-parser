#pragma once
#include "qt_mock.h"

/**
 * Counter — демонстрационный класс с сигналами и слотами (Qt-стиль).
 * Отслеживает числовое значение и генерирует сигналы при его изменении.
 */
class Counter : public QObject {
    Q_OBJECT

public:
    explicit Counter(int initial = 0);
    int value() const;

public slots:
    void setValue(int newValue);
    void increment();
    void reset();

signals:
    void valueChanged(int newValue);
    void thresholdReached(int threshold);

private:
    int m_value;
    static const int THRESHOLD = 10;
};
