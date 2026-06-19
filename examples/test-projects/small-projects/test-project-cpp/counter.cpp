#include "counter.h"
#include <stdexcept>

Counter::Counter(int initial) : m_value(initial) {}

// В Qt тела сигналов генерирует moc. В нашем mock — пустые заглушки.
void Counter::valueChanged(int) {}
void Counter::thresholdReached(int) {}

int Counter::value() const {
    return m_value;
}

void Counter::setValue(int newValue) {
    if (m_value == newValue) {
        return;
    }
    m_value = newValue;
    emit valueChanged(m_value);
    if (m_value >= THRESHOLD) {
        emit thresholdReached(THRESHOLD);
    }
}

void Counter::increment() {
    setValue(m_value + 1);
}

void Counter::reset() {
    setValue(0);
}
