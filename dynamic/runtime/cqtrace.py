"""
__trace.py — рантайм датчиков динамического анализа (Python).

Датчики:
  @__trace.fn(fo)     — декоратор ФО: пишет fo:0 на входе и fo:-1 на ЛЮБОМ
                        выходе (return/исключение) через try/finally.
  __trace._t(fo, br)  — в начало блока ветви: пишет fo:br.

Coverage-строки `fo:br` — анти-спам: каждый датчик пишет №1,2,4,8… (степени двойки).
Маршруты выполнения — на выходе из каждого вызова ФО пишутся две строки:
  R fo:b1>b2>...      — фактический маршрут по «да»-ветвям;
  C fo:fo>c1>c2>...   — фактическая цепочка вызовов (self, затем вызванные ФО).
Подряд идущие повторы схлопываются (итерации цикла/рекурсия → один раз); уникальные
маршруты пишутся 1,2,4,8… раз. Стек кадров — поток-локальный.
Трассы: $HOME/python-<timestamp>-<pid>.log, ротация 100 МБ.
"""
import io
import os
import time
import threading

_cnt = {}
_rsig = {}
_lock = threading.Lock()
_tls = threading.local()
_fp = None
_bytes = 0
_LIMIT = 100 * 1024 * 1024
_LANG = "python"


def _rotate():
    global _fp, _bytes
    ts = time.strftime("%Y%m%d-%H%M%S")
    home = os.path.expanduser("~")
    if _fp:
        _fp.close()
    _fp = io.open(os.path.join(home, u"%s-%s-%d.log" % (_LANG, ts, os.getpid())),
                  "a", encoding="utf-8")
    _bytes = 0


def _write(line):
    """Запись строки в трассу. Предполагает захваченный _lock."""
    global _fp, _bytes
    if _fp is None or _bytes >= _LIMIT:
        _rotate()
    _bytes += _fp.write(line)
    _fp.flush()


# ── Фактические маршруты ──────────────────────────────────────────────────────

def _stack():
    s = getattr(_tls, "stk", None)
    if s is None:
        s = _tls.stk = []           # кадры: {"fo":fo, "br":[ветви], "cl":[self, вызовы]}
    return s


def _emit(tag, fo, seq):
    """Выгрузка маршрута с анти-спамом по сигнатуре (1,2,4,8…)."""
    key = (tag, fo, tuple(seq))
    with _lock:
        c = _rsig.get(key, 0) + 1
        _rsig[key] = c
        if c & (c - 1):
            return
        _write(u"%s %d:%s\n" % (tag, fo, u">".join(str(x) for x in seq)))


def _route_event(fo, br):
    s = _stack()
    if br == 0:                              # вход в ФО
        if s:                               # записать как вызов в кадре-родителе
            cl = s[-1]["cl"]
            if not cl or cl[-1] != fo:      # анти-спам маршрута (вызов в цикле/рекурсия)
                cl.append(fo)
        s.append({"fo": fo, "br": [], "cl": [fo]})
    elif br == -1:                          # выход — выгрузка обоих маршрутов
        if s:
            fr = s.pop()
            _emit(u"R", fr["fo"], fr["br"])
            _emit(u"C", fr["fo"], fr["cl"])
    else:                                   # ветвь — дописать (без подряд-повторов)
        if s:
            b = s[-1]["br"]
            if not b or b[-1] != br:
                b.append(br)


def _t(fo, br):
    """Срабатывание датчика: фактический маршрут + coverage-строка (с анти-спамом)."""
    _route_event(fo, br)                    # буфер маршрута — всегда (поток-локально)
    with _lock:
        c = _cnt.get((fo, br), 0) + 1
        _cnt[(fo, br)] = c
        if c & (c - 1):                     # не степень двойки → пропуск coverage-строки
            return
        _write(u"%d:%d\n" % (fo, br))


def fn(fo):
    """Декоратор: вход (fo:0) и выход (fo:-1), в т.ч. при исключении."""
    def deco(f):
        def wrap(*a, **k):
            _t(fo, 0)
            try:
                return f(*a, **k)
            finally:
                _t(fo, -1)
        wrap.__name__ = getattr(f, "__name__", "wrap")
        wrap.__doc__ = getattr(f, "__doc__", None)
        return wrap
    return deco
