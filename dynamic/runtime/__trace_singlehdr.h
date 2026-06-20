/*
 * __trace.h — единый header-only рантайм датчиков для C/C++ проектов со
 * своей сборкой (make, Debian rules и т.п.), напр. nginx, gosjava.
 *
 * Размещение: положить в системный include-путь (например /usr/include).
 * Тогда '#include "__trace.h"' находится из ЛЮБОГО файла проекта —
 * независимо от его -I путей и от того, сколько отдельных бинарников
 * (.so/.exe) собирается из исходников (gcc/clang по умолчанию проверяют
 * системные include-пути и для '#include "..."', не только для '<...>').
 * Сборочные скрипты обычно трогать не нужно; если конкретный тулчейн
 * собран с --sysroot/-nostdinc — поправьте его, чтобы /usr/include
 * (или иной выбранный каталог) оставался в путях поиска заголовков.
 *
 * Реализация __trace_hit — ПОЛНОСТЬЮ в заголовке, компилируется в КАЖДОЙ
 * единице трансляции, которая его подключает. Чтобы при линковке N копий
 * не возникло "multiple definition", функция и большие данные состояния
 * помечены GNU/Clang-атрибутом weak (CQ_WEAK): линкер сам сводит все
 * одноимённые слабые символы в РОВНО ОДИН экземпляр на конечный бинарник,
 * остальные отбрасывает на этапе разрешения символов (это касается и
 * данных — иначе тысячи .cpp с большими static-массивами раздули бы
 * итоговый .so на гигабайты .bss). Поэтому все .c/.cpp одного so/exe в
 * итоге делят ОДНО состояние (счётчики, файл трасс, стек маршрутов), а
 * разные бинарники друг с другом не пересекаются — без ручной разметки
 * "одного impl-файла на бинарник", которая требовалась раньше через
 * #define CQ_TRACE_IMPL в одном выбранном файле. Обычного
 * #include "__trace.h" во всех файлах достаточно самого по себе.
 *
 * Маленькие static-помощники (__cq_rotate, __cq_write, ...) НЕ weak —
 * они вызываются только из __trace_hit в той же единице трансляции;
 * каждая единица получает свою копию их машинного кода, но т.к. реально
 * исполняется лишь та копия __trace_hit, что осталась после слияния
 * слабых символов, лишних побочных эффектов это не создаёт (код прочих
 * копий просто не вызывается).
 *
 * Без pthread (однопоточный сценарий: воркеры — отдельные процессы).
 * Анти-спам: пишем только срабатывания №1,2,4,8,16… (степени двойки) на
 * каждый sid. Трассы: $HOME/<lang>-<ts>-<pid>.log, ротация при 100 МБ.
 */
#if defined(__GNUC__) || defined(__clang__)
#  define CQ_WEAK __attribute__((weak))
#else
#  error "__trace.h: нужен GCC или Clang (weak-символы, __attribute__((cleanup)))"
#endif

#ifndef CQ_TRACE_H
#define CQ_TRACE_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#if defined(_WIN32)
#  include <process.h>
#  define CQ_GETPID _getpid
#else
#  include <unistd.h>
#  define CQ_GETPID getpid
#endif

#ifndef CQ_LANG
#define CQ_LANG "cpp"
#endif
#ifndef CQ_N
#define CQ_N 300000           /* максимум sid (с запасом) */
#endif
#define CQ_LIMIT (100u * 1024u * 1024u)

#ifdef __cplusplus
extern "C" {
#endif
CQ_WEAK void __trace_hit(unsigned sid, int fo, int br);
#ifdef __cplusplus
}
#endif

#define __TRACE(sid, fo, br) __trace_hit((unsigned)(sid), (int)(fo), (int)(br))

/* Вход/выход ФО через cleanup-атрибут GCC/Clang (срабатывает на всех
 * выходах, включая return из середины тела и проброс исключений в C++). */
typedef struct { int fo; unsigned sx; } __trace_g;
static inline __trace_g __trace_enter(unsigned se, unsigned sx, int fo) {
    __trace_hit(se, fo, 0);
    { __trace_g g; g.fo = fo; g.sx = sx; return g; }
}
static inline void __trace_leave(__trace_g *g) { __trace_hit(g->sx, g->fo, -1); }
#define __TRACE_FN(fo, se, sx) \
    __trace_g __tg_##se __attribute__((cleanup(__trace_leave))) = \
        __trace_enter((unsigned)(se), (unsigned)(sx), (int)(fo))

/* ── Состояние рантайма: weak-данные, слитые линкером в один экземпляр
 * на конечный бинарник (см. пояснение в шапке файла). ────────────────── */
CQ_WEAK unsigned      __cq_cnt[CQ_N + 1];
CQ_WEAK FILE         *__cq_fp = 0;
CQ_WEAK unsigned long __cq_bytes = 0;

static void __cq_rotate(void) {
    char path[1024], ts[32];
    time_t t = time(0);
    struct tm tmv;
#if defined(_WIN32)
    { struct tm *tp = localtime(&t); if (tp) tmv = *tp; }
#else
    localtime_r(&t, &tmv);
#endif
    strftime(ts, sizeof ts, "%Y%m%d-%H%M%S", &tmv);
    const char *home = getenv("HOME");
#if defined(_WIN32)
    if (!home) home = getenv("USERPROFILE");
#endif
    if (!home) home = ".";
    snprintf(path, sizeof path, "%s/%s-%s-%d.log", home, CQ_LANG, ts, (int)CQ_GETPID());
    if (__cq_fp) fclose(__cq_fp);
    __cq_fp = fopen(path, "a");
    __cq_bytes = 0;
}

static void __cq_write(const char *buf) {
    if (!__cq_fp || __cq_bytes >= CQ_LIMIT) __cq_rotate();
    if (__cq_fp) {
        size_t len = strlen(buf);
        fputs(buf, __cq_fp);
        __cq_bytes += (unsigned long)len;
        fflush(__cq_fp);
    }
}

/* ── Запись ФАКТИЧЕСКИХ маршрутов выполнения ───────────────────────────────
 * Поток буфера пути: на входе в ФО (br==0) — кадр в стеке; на каждой ветви
 * (br>=1) — номер ветви дописывается в текущий кадр; на выходе (br==-1) —
 * полная последовательность ветвей выгружается строкой «R fo:b1>b2>...» с
 * дедупликацией по сигнатуре (каждый уникальный путь пишется 1,2,4,8… раз).
 * Однопоточная модель (как и весь рантайм). Отключается -DCQ_NO_ROUTES. */
#ifndef CQ_NO_ROUTES
#ifndef CQ_ROUTE_DEPTH
#define CQ_ROUTE_DEPTH 128      /* макс. глубина вложенности вызовов */
#endif
#ifndef CQ_ROUTE_BR
#define CQ_ROUTE_BR    256      /* макс. ветвей в одном маршруте */
#endif
#ifndef CQ_ROUTE_TAB
#define CQ_ROUTE_TAB   8192     /* размер таблицы сигнатур (степень двойки) */
#endif

/* Кадр на вызов ФО: последовательность сработавших ветвей (br) и цепочка
 * вызванных ФО (cl, начинается с self). На выходе выгружаются обе:
 *   R fo:b1>b2>...   — фактический маршрут по ВЕТВЯМ;
 *   C fo:fo>c1>c2... — фактический маршрут по ВЫЗОВАМ (процедур/функций). */
CQ_WEAK int      __cq_rstk_fo[CQ_ROUTE_DEPTH];
CQ_WEAK int      __cq_rstk_br[CQ_ROUTE_DEPTH][CQ_ROUTE_BR];   /* ветви */
CQ_WEAK int      __cq_rstk_bn[CQ_ROUTE_DEPTH];
CQ_WEAK int      __cq_rstk_cl[CQ_ROUTE_DEPTH][CQ_ROUTE_BR];   /* вызовы (self, callee…) */
CQ_WEAK int      __cq_rstk_cn[CQ_ROUTE_DEPTH];
CQ_WEAK int      __cq_rsp = 0;          /* указатель стека (глубина) */
CQ_WEAK int      __cq_rover = 0;        /* переполнение глубины — для баланса */
CQ_WEAK unsigned long __cq_rsig_key[CQ_ROUTE_TAB];
CQ_WEAK unsigned      __cq_rsig_cnt[CQ_ROUTE_TAB];

/* Должна ли последовательность с такой сигнатурой быть выгружена сейчас (1,2,4,8…). */
static int __cq_route_should_emit(unsigned long h) {
    unsigned idx = (unsigned)(h & (CQ_ROUTE_TAB - 1));
    unsigned i;
    for (i = 0; i < CQ_ROUTE_TAB; i++) {
        unsigned p = (idx + i) & (CQ_ROUTE_TAB - 1);
        if (__cq_rsig_cnt[p] == 0) {           /* новая сигнатура */
            __cq_rsig_key[p] = h; __cq_rsig_cnt[p] = 1; return 1;
        }
        if (__cq_rsig_key[p] == h) {           /* уже встречалась */
            unsigned c = ++__cq_rsig_cnt[p];
            return (c & (c - 1)) ? 0 : 1;
        }
    }
    return 1;                                   /* таблица полна — пишем всегда */
}

/* Выгрузка одной последовательности «<tag> fo:a>b>...» с дедупликацией.
 * salt разводит сигнатуры ветвей (R) и вызовов (C) по таблице. */
static void __cq_emit_seq(char tag, int fo, const int *arr, int n, unsigned long salt) {
    char seq[8 * CQ_ROUTE_BR + 1];
    int  pos = 0, i;
    unsigned long h = 1469598103934665603UL ^ salt;   /* FNV-1a, c учётом fo */
    h ^= (unsigned long)fo; h *= 1099511628211UL;
    for (i = 0; i < n; i++) {
        h ^= (unsigned long)arr[i]; h *= 1099511628211UL;
        pos += snprintf(seq + pos, sizeof seq - (size_t)pos, (i ? ">%d" : "%d"), arr[i]);
        if (pos >= (int)sizeof seq - 16) break;
    }
    seq[pos] = 0;
    if (__cq_route_should_emit(h)) {
        char line[8 * CQ_ROUTE_BR + 32];
        snprintf(line, sizeof line, "%c %d:%s\n", tag, fo, seq);
        __cq_write(line);
    }
}

static void __cq_route_event(int fo, int br) {
    if (br == 0) {                              /* вход в ФО */
        if (__cq_rover == 0 && __cq_rsp > 0) {  /* записать как вызов в кадре-родителе */
            int p = __cq_rsp - 1;
            /* анти-спам маршрута: не дублируем подряд (вызов в цикле/рекурсия) */
            if (__cq_rstk_cn[p] < CQ_ROUTE_BR &&
                __cq_rstk_cl[p][__cq_rstk_cn[p] - 1] != fo)
                __cq_rstk_cl[p][__cq_rstk_cn[p]++] = fo;
        }
        if (__cq_rsp < CQ_ROUTE_DEPTH) {        /* новый кадр; self — первым в цепочке вызовов */
            int t = __cq_rsp;
            __cq_rstk_fo[t] = fo; __cq_rstk_bn[t] = 0;
            __cq_rstk_cl[t][0] = fo; __cq_rstk_cn[t] = 1;
            __cq_rsp++;
        } else __cq_rover++;
    } else if (br == -1) {                      /* выход — выгрузка обоих маршрутов */
        if (__cq_rover > 0) __cq_rover--;
        else if (__cq_rsp > 0) {
            int t = --__cq_rsp;
            __cq_emit_seq('R', __cq_rstk_fo[t], __cq_rstk_br[t], __cq_rstk_bn[t], 0UL);
            __cq_emit_seq('C', __cq_rstk_fo[t], __cq_rstk_cl[t], __cq_rstk_cn[t], 0x9E3779B97F4A7C15UL);
        }
    } else {                                    /* ветвь — дописать в текущий кадр */
        /* Ветвь записываем ТОЛЬКО если её ФО совпадает с ФО верхнего кадра, т.е.
         * ветвь принадлежит выполняющейся сейчас функции. Иначе ветвь сработала,
         * когда кадр её функции уже снят — типичный случай: catch
         * function-try-block (страж входа/выхода живёт ВНУТРИ try-блока, при
         * исключении он разрушается до запуска catch, и кадр функции уже снят).
         * Без этой проверки такая ветвь липла бы к маршруту ВЫЗЫВАЮЩЕГО
         * (напр. фантомная #1 у main). На coverage-строки (fo:br) это не влияет. */
        if (__cq_rover == 0 && __cq_rsp > 0 && __cq_rstk_fo[__cq_rsp - 1] == fo) {
            int t = __cq_rsp - 1;
            /* анти-спам маршрута: не дублируем подряд (итерации цикла) */
            if (__cq_rstk_bn[t] < CQ_ROUTE_BR &&
                (__cq_rstk_bn[t] == 0 || __cq_rstk_br[t][__cq_rstk_bn[t] - 1] != br))
                __cq_rstk_br[t][__cq_rstk_bn[t]++] = br;
        }
    }
}
#else
static void __cq_route_event(int fo, int br) { (void)fo; (void)br; }
#endif /* CQ_NO_ROUTES */

/* extern "C" на реализации — иначе при компиляции файла как C++ имя
 * __trace_hit будет mangled, а вызовы (из extern "C" объявления выше) —
 * нет → undefined symbol при линковке. */
#ifdef __cplusplus
extern "C"
#endif
CQ_WEAK void __trace_hit(unsigned sid, int fo, int br) {
    __cq_route_event(fo, br);             /* фактический маршрут — всегда, до анти-спама */
    if (sid <= (unsigned)CQ_N) {
        unsigned c = ++__cq_cnt[sid];
        if (c & (c - 1)) return;          /* не степень двойки → пропуск coverage-строки */
    }
    {
        char line[64];
        snprintf(line, sizeof line, "%d:%d\n", fo, br);
        __cq_write(line);
    }
}

#endif /* CQ_TRACE_H */
