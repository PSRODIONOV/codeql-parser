/*
 * __trace.h — рантайм датчиков динамического анализа (C/C++).
 * Подключается в каждый инструментируемый файл.
 *
 * Датчики:
 *   __TRACE_FN(fo, se, sx) — первым оператором тела ФО: пишет fo:0 на входе и
 *                            fo:-1 на ЛЮБОМ выходе (return/исключение/проброс).
 *                            C++  — через RAII-деструктор; C — через cleanup-атрибут.
 *   __TRACE(sid, fo, br)   — в начало блока ветви: пишет fo:br.
 *
 * Анти-спам: каждый датчик пишет срабатывания №1,2,4,8,16… (степени двойки),
 * поэтому цикл из 10^6 итераций даёт ~20 строк, а не миллион.
 */
#ifndef __TRACE_H
#define __TRACE_H

#ifdef __cplusplus
extern "C" {
#endif
void __trace_hit(unsigned sid, int fo, int br);
#ifdef __cplusplus
}
#endif

#define __TRACE(sid, fo, br) __trace_hit((unsigned)(sid), (int)(fo), (int)(br))

#ifdef __cplusplus
/* C++: RAII-страж. Деструктор срабатывает на всех путях выхода, включая исключения. */
struct __TraceGuard {
    int fo; unsigned sx;
    __TraceGuard(int f, unsigned se, unsigned s) : fo(f), sx(s) { __trace_hit(se, f, 0); }
    ~__TraceGuard() { __trace_hit(sx, fo, -1); }
};
#define __TRACE_FN(fo, se, sx) __TraceGuard __tg_##se((int)(fo), (unsigned)(se), (unsigned)(sx))
#else
/* C: cleanup-атрибут GCC/Clang — функция вызывается при выходе из области видимости. */
typedef struct { int fo; unsigned sx; } __trace_g;
static inline __trace_g __trace_enter(unsigned se, unsigned sx, int fo) {
    __trace_hit(se, fo, 0); { __trace_g g; g.fo = fo; g.sx = sx; return g; }
}
static inline void __trace_leave(__trace_g *g) { __trace_hit(g->sx, g->fo, -1); }
#define __TRACE_FN(fo, se, sx) \
    __trace_g __tg_##se __attribute__((cleanup(__trace_leave))) = \
        __trace_enter((unsigned)(se), (unsigned)(sx), (int)(fo))
#endif

#endif /* __TRACE_H */
