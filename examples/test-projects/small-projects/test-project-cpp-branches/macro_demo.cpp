#include "macro_demo.h"
#include <cstdlib>

// ── 1. ФО ЦЕЛИКОМ генерируется макросом ──────────────────────────────────────
// Имя формируется через ## (в исходнике как текст НЕ встречается), вся функция —
// часть раскрытия макроса. Перечень ФО и инструментатор должны ИСКЛЮЧИТЬ такие:
// у функции нет отдельного места в исходнике, f.isInMacroExpansion()=true.
#define DEFINE_GETTER(suffix, value) \
    int get_##suffix(void) { return (value); }

DEFINE_GETTER(answer, 42)       // -> int get_answer(void) { return 42; }
DEFINE_GETTER(zero, 0)          // -> int get_zero(void)   { return 0; }

// Полностью-макро ФО С ОПАСНОЙ КОНСТРУКЦИЕЙ внутри: имя из ##, тело — system().
// ФО исключается → его ПОК (system, CWE-078) НЕ должен попасть в отчёты:
// исключённый ФО не оставляет ни ветвей, ни ИО, ни опасных конструкций.
#define DEFINE_RUNNER(suffix) \
    void run_##suffix(const char* c) { system(c); }
DEFINE_RUNNER(macro)            // -> void run_macro(const char* c) { system(c); }

// ── 2. Тело ФО (открывающая { и пролог) генерируется макросом ────────────────
// Сигнатура написана БУКВАЛЬНО, а открывающая { и пролог — из макроса (паттерн
// HotSpot JNI_ENTRY/JVM_ENTRY). ФО должен инструментироваться: датчик входа
// вставляется с учётом того, что { синтезирована макросом (см. probe_points.ql
// и обработку newline_after / _find_macro_call_end_idx в instrument_cpp.py).
#define FN_ENTER  { int __depth = 0; (void)__depth;
#define FN_LEAVE  }

int macro_body(int x) FN_ENTER
    if (x > 0)                  // ветвь #1 (if) — реальный код внутри макро-тела
        return x;
    return -x;
FN_LEAVE

// ── 3. Сигнатура настоящая, ВСЁ тело — ОДИН макрос (вид: void f() MACRO;) ─────
// И открывающая {, и содержимое, и закрывающая } находятся внутри одного
// макроса. Имя ФО — НАСТОЯЩЕЕ (написано буквально), поэтому это полноценный ФО:
// инструментатор оборачивает макро-тело и ставит датчик входа/выхода
// (отличие от случая 1, где из макроса и само ИМЯ — такой ФО исключается).
#define MACRO_BODY { (void)0; }
void macro_full_body() MACRO_BODY;

// Обычный ФО — вызывает всё, чтобы макро-функции попали в сборку/БД.
int call_macro_demo(void) {
    macro_full_body();
    run_macro("");              // вызвать опасный макро-ФО (его ПОК исключается)
    return get_answer() + get_zero() + macro_body(5) + macro_body(-3);
}
