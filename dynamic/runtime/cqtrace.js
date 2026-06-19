/*
 * cqtrace.js — рантайм датчиков динамического анализа (JavaScript).
 *
 * Работает в Node.js (CommonJS) и в браузере (window.cqtrace).
 *
 * cqtrace.hit(fo, br) — срабатывание датчика: выводит "fo:br" в console.log.
 *   Вход ФО:  hit(fo, 0);   Выход ФО: hit(fo, -1) (в finally);   Ветвь: hit(fo, N).
 *
 * Coverage-строки `fo:br` — анти-спам (№1,2,4,8…). На выходе из вызова ФО также
 * пишутся маршруты: «R fo:b1>b2>...» (ветви) и «C fo:fo>c1>c2>...» (вызовы).
 * Подряд идущие повторы схлопываются (циклы/рекурсия); уникальные маршруты —
 * 1,2,4,8… раз. Модель однопоточная (event loop), стек кадров — модульный.
 *
 * Сбор трасс:
 *   Node.js  — перенаправить stdout в файл: node app.js > traces.log
 *   Браузер  — DevTools → Console → Export, либо переопределить console.log до загрузки.
 */
'use strict';

const _cnt = Object.create(null);
const _rsig = Object.create(null);
const _stack = [];   // кадры: {fo, br:[ветви], cl:[self, вызовы]}

function _emit(tag, fo, seq) {
    const key = tag + fo + ':' + seq.join('>');
    const c = (_rsig[key] || 0) + 1;
    _rsig[key] = c;
    if (c & (c - 1)) return;          // не степень двойки → пропуск
    console.log(tag + ' ' + fo + ':' + seq.join('>'));
}

function _routeEvent(fo, br) {
    if (br === 0) {                   // вход в ФО
        if (_stack.length) {          // записать как вызов в кадре-родителе
            const cl = _stack[_stack.length - 1].cl;
            if (cl[cl.length - 1] !== fo) cl.push(fo);   // анти-спам (вызов в цикле/рекурсия)
        }
        _stack.push({ fo: fo, br: [], cl: [fo] });
    } else if (br === -1) {           // выход — выгрузка обоих маршрутов
        const fr = _stack.pop();
        if (fr) { _emit('R', fr.fo, fr.br); _emit('C', fr.fo, fr.cl); }
    } else {                          // ветвь — дописать (без подряд-повторов)
        if (_stack.length) {
            const b = _stack[_stack.length - 1].br;
            if (b[b.length - 1] !== br) b.push(br);
        }
    }
}

function hit(fo, br) {
    _routeEvent(fo, br);
    const k = fo + ':' + br;
    const c = (_cnt[k] || 0) + 1;
    _cnt[k] = c;
    if (c & (c - 1)) return;          // не степень двойки → пропуск coverage-строки
    console.log(fo + ':' + br);
}

// CommonJS (Node.js) или глобал браузера
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { hit };
} else if (typeof window !== 'undefined') {
    window.cqtrace = { hit };
}
