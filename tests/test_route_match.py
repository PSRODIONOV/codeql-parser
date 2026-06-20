"""Юнит-тесты матчера маршрутов (dynamic/route_match_report.py).

Регрессия нормализации циклов: фактический маршрут (рантайм пишет каждую
итерацию цикла) схлопывается до одного прохода, как в статическом перечислителе,
поэтому чисто-цикловые маршруты перестают быть «непредусмотренными».
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dynamic"))
from route_match_report import _collapse_cycles, _branch_sig  # noqa: E402


class TestCollapseCycles:

    @pytest.mark.parametrize("inp,exp", [
        ((1, 2, 1, 2, 1, 2), (1, 2)),     # цикл из 2 ветвей, 3 итерации
        ((1, 1, 1), (1,)),                # одна ветвь, 3 итерации
        ((2, 2), (2,)),                   # 2 итерации
        ((1, 2, 3, 2, 3), (1, 2, 3)),     # вложенный повтор (внутренний цикл)
        ((1, 2, 1, 2, 3), (1, 2, 3)),     # цикл, затем выход
        ((), ()),                         # пустой маршрут
        ((5,), (5,)),                     # один проход
        ((1, 2, 3), (1, 2, 3)),           # без повторов
    ])
    def test_collapse(self, inp, exp):
        assert _collapse_cycles(inp) == exp

    def test_varying_iterations_not_collapsed(self):
        """Итерации с РАЗНЫМИ ветвями (continue/выход) — не повтор блока, не схлопываются."""
        assert _collapse_cycles((1, 3, 1, 2)) == (1, 3, 1, 2)

    def test_idempotent(self):
        once = _collapse_cycles((1, 2, 1, 2, 1, 2))
        assert _collapse_cycles(once) == once


class TestBranchSig:

    def test_loop_route_collapsed_to_single_pass(self):
        """Статическая сигнатура цикла нормализуется так же, как фактическая."""
        route = ("for #1 -да->while #2 -да->for #1 -да->while #2 -да->"
                 "for #1 -да->while #2 -да->Конец")
        assert _branch_sig(route) == (1, 2)

    def test_else_outcome_not_instrumented(self):
        """else (-нет / тело else) не входит в сигнатуру — датчик на «да»-стороне."""
        assert _branch_sig("if #1 -нет->Конец") == ()
        assert _branch_sig("if #1 -да->Конец") == (1,)
