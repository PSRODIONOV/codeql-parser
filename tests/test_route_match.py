"""Юнит-тесты матчера маршрутов (dynamic/route_match_report.py).

Регрессия нормализации циклов: фактический маршрут (рантайм пишет каждую
итерацию цикла) схлопывается до одного прохода, как в статическом перечислителе,
поэтому чисто-цикловые маршруты перестают быть «непредусмотренными».
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dynamic"))
from route_match_report import _collapse_cycles, _branch_sig, is_instrumented  # noqa: E402


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

    def test_else_outcome_now_instrumented_with_own_number(self):
        """"нет" (else) входит в сигнатуру со своим номером, отличным от
        номера if — у else свой датчик, не общий с if."""
        assert _branch_sig("if #2 -нет->Конец") == (2,)
        assert _branch_sig("if #1 -да->Конец") == (1,)

    def test_switch_case_route_in_sig(self):
        """Метки switch (case/default) инструментируются — входят в сигнатуру
        (fallthrough case0->case6 даёт (1,2))."""
        assert _branch_sig("case #1 -да->case #2 -да->Конец") == (1, 2)
        assert _branch_sig("default #8 -да->Конец") == (8,)


class TestIsInstrumented:

    @pytest.mark.parametrize("btype,outcome,exp", [
        ("if", "да", True), ("if", "нет", True),  # см. test_else_outcome_now_instrumented_with_own_number
        ("for", "да", True), ("while", "нет", False),
        ("try", "catch", True), ("try", "нет исключения", True),
        ("case", "да", True), ("default", "да", True),
        ("else", "да", False),   # else не инструментируется (датчик на then)
    ])
    def test_is_instrumented(self, btype, outcome, exp):
        assert is_instrumented(btype, outcome) is exp
