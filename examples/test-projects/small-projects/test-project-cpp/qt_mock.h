#pragma once

// Минимальный mock Qt для тестирования CodeQL-анализа.
// Позволяет компилировать код с сигналами/слотами без установки Qt.

#define Q_OBJECT
#define signals public
#define slots   /* slots — обычные методы */
#define emit    /* emit раскрывается в прямой вызов метода */

class QObject {
public:
    virtual ~QObject() = default;
};

// Упрощённый connect — в реальном Qt регистрирует связь через мета-систему
inline void connect(const QObject* /*sender*/,   const char* /*signal*/,
                    const QObject* /*receiver*/, const char* /*slot*/) {}
