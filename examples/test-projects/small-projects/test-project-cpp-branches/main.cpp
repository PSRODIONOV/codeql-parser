#include <iostream>
#include <vector>
#include <string>

#include "if_demo.h"
#include "loop_demo.h"
#include "exception_demo.h"
#include "single_stmt_demo.h"
#include "oneline_demo.h"
#include "advanced_demo.h"
#include "negative_demo.h"
#include "unsafe_demo.h"
#include "macro_demo.h"
#include "pipeline.h"

// main вызывает все функции так, чтобы КАЖДАЯ отслеживаемая ветвь
// (then у if, тело for/while/do, тело try) реально выполнилась хотя бы раз.
// Это нужно для проверки сопоставления статических и динамических маршрутов:
// после инструментации все ветви должны быть отмечены как исполнявшиеся.
int main() {
    // ---- if_demo ----
    std::cout << "simple_if(5)         = " << simple_if(5) << "\n";
    std::cout << "if_else(4)           = " << if_else(4) << "\n";
    std::cout << "if_else(7)           = " << if_else(7) << "\n";
    std::cout << "else_if_chain(95)    = " << else_if_chain(95) << "\n";
    std::cout << "else_if_chain(80)    = " << else_if_chain(80) << "\n";
    std::cout << "else_if_chain(65)    = " << else_if_chain(65) << "\n";
    std::cout << "else_if_chain(45)    = " << else_if_chain(45) << "\n";
    std::cout << "nested_if(3,2)       = " << nested_if(3, 2) << "\n";
    std::cout << "nested_if(3,-2)      = " << nested_if(3, -2) << "\n";
    std::cout << "if_with_logical(2,3) = " << if_with_logical(2, 3) << "\n";

    // ---- loop_demo ----
    std::cout << "sum_for(10)          = " << sum_for(10) << "\n";
    std::cout << "nested_for(3,4)      = " << nested_for(3, 4) << "\n";
    int arr[] = {1, -2, 3, 7, 5};
    std::cout << "for_with_break       = " << for_with_break(arr, 5, 7) << "\n";
    std::cout << "count_down_while(64) = " << count_down_while(64) << "\n";
    std::cout << "do_while_demo(4)     = " << do_while_demo(4) << "\n";
    std::cout << "while_with_if(9)     = " << while_with_if(9) << "\n";

    // ---- exception_demo ----
    std::cout << "simple_try(5)        = " << simple_try(5) << "\n";
    std::cout << "simple_try(-1)       = " << simple_try(-1) << "\n";
    std::cout << "try_multiple_catch(1)= " << try_multiple_catch(1) << "\n";
    std::cout << "try_multiple_catch(2)= " << try_multiple_catch(2) << "\n";
    std::cout << "try_multiple_catch(3)= " << try_multiple_catch(3) << "\n";
    std::cout << "try_multiple_catch(0)= " << try_multiple_catch(0) << "\n";
    std::cout << "nested_try(4)        = " << nested_try(4) << "\n";
    std::cout << "nested_try(0)        = " << nested_try(0) << "\n";
    std::cout << "try_with_loop(hello) = " << try_with_loop("hello") << "\n";
    std::cout << "try_with_loop(xyz)   = " << try_with_loop("xyz") << "\n";

    // ---- single_stmt_demo (одиночные операторы без скобок) ----
    std::cout << "if_single(5)         = " << if_single(5) << "\n";
    std::cout << "if_else_single(8)    = " << if_else_single(8) << "\n";
    std::cout << "if_else_single(5)    = " << if_else_single(5) << "\n";
    std::cout << "for_single(10)       = " << for_single(10) << "\n";
    std::cout << "while_single(64)     = " << while_single(64) << "\n";
    std::cout << "do_single(4)         = " << do_single(4) << "\n";
    int arr2[] = {1, -2, 3, -4, 5};
    std::cout << "nested_single        = " << nested_single(arr2, 5) << "\n";

    // ---- oneline_demo (заголовок и тело на одной строке) ----
    std::cout << "if_oneline_nobrace   = " << if_oneline_nobrace(5) << "\n";
    std::cout << "if_else_oneline_nn   = " << if_else_oneline_nn(8) << "\n";
    std::cout << "if_else_oneline_bb   = " << if_else_oneline_bb(8) << "\n";
    std::cout << "if_else_oneline_nb   = " << if_else_oneline_nb(5) << "\n";
    std::cout << "if_else_oneline_bn   = " << if_else_oneline_bn(5) << "\n";
    std::cout << "for_oneline_nobrace  = " << for_oneline_nobrace(10) << "\n";
    std::cout << "while_oneline_nobrace= " << while_oneline_nobrace(64) << "\n";
    std::cout << "do_oneline_nobrace   = " << do_oneline_nobrace(4) << "\n";
    std::cout << "if_oneline_brace     = " << if_oneline_brace(5) << "\n";
    std::cout << "for_oneline_brace    = " << for_oneline_brace(10) << "\n";
    std::cout << "while_oneline_brace  = " << while_oneline_brace(64) << "\n";
    std::cout << "do_oneline_brace     = " << do_oneline_brace(4) << "\n";
    std::cout << "try_oneline_brace(5) = " << try_oneline_brace(5) << "\n";
    std::cout << "try_oneline_brace(-1)= " << try_oneline_brace(-1) << "\n";
    int arr3[] = {1, -2, 3, -4, 5};
    std::cout << "nested_oneline       = " << nested_oneline(arr3, 5) << "\n";

    // ---- advanced_demo (специфические формы) ----
    std::cout << "cstr_len(hello)      = " << cstr_len("hello") << "\n";
    std::cout << "skip_spaces('   x')  = " << skip_spaces("   x") << "\n";
    std::cout << "classify_empty(5)    = " << classify_empty(5) << "\n";
    std::cout << "classify_empty(-5)   = " << classify_empty(-5) << "\n";
    std::cout << "do_once(6)           = " << do_once(6) << "\n";
    std::cout << "do_once(-1)          = " << do_once(-1) << "\n";
    int az[] = {3, 1, 0, 7};
    std::cout << "find_first_zero      = " << find_first_zero(az, 4) << "\n";
    int az_nz[] = {3, 1, 7};   // без нуля → ветвь "i >= n" (не найдено)
    std::cout << "find_first_zero(nz)  = " << find_first_zero(az_nz, 3) << "\n";
    std::cout << "is_palindrome(abba)  = " << is_palindrome("abba", 4) << "\n";
    std::cout << "is_palindrome(abc)   = " << is_palindrome("abc", 3) << "\n";
    std::cout << "safe_div(10,2)       = " << safe_div(10, 2) << "\n";
    std::cout << "safe_div(10,0)       = " << safe_div(10, 0) << "\n";
    std::vector<int> cp = {-1, 2, -3, 4, 5};
    std::cout << "count_positive       = " << count_positive(cp) << "\n";
    std::cout << "factorial(5)         = " << factorial(5) << "\n";
    std::cout << "clamp_val(15,0,10)   = " << clamp_val(15, 0, 10) << "\n";
    std::cout << "clamp_val(-3,0,10)   = " << clamp_val(-3, 0, 10) << "\n";
    std::cout << "clamp_val(5,0,10)    = " << clamp_val(5, 0, 10) << "\n";

    // ---- negative_demo (НЕ должно инструментироваться) ----
    std::cout << "weekday_kind(0)      = " << weekday_kind(0) << "\n";  // case 0 (+fallthrough 6)
    std::cout << "weekday_kind(1)      = " << weekday_kind(1) << "\n";  // case 1..5
    std::cout << "weekday_kind(6)      = " << weekday_kind(6) << "\n";  // case 6
    std::cout << "weekday_kind(9)      = " << weekday_kind(9) << "\n";  // default
    std::cout << "sum_range            = " << sum_range({1, 2, 3, 4}) << "\n";
    std::cout << "sign_and_flags(2,3)  = " << sign_and_flags(2, 3) << "\n";
    std::cout << "retry_goto(3)        = " << retry_goto(3) << "\n";
    std::cout << "macro_control(5)     = " << macro_control(5) << "\n";
    std::cout << "macro_control(-5)    = " << macro_control(-5) << "\n";

    // ---- unsafe_demo (опасные конструкции для сигнатурного анализа) ----
    run_unsafe("demo");

    // ---- macro_demo (ФО из макроса: целиком / только тело) ----
    std::cout << "call_macro_demo      = " << call_macro_demo() << "\n";

    // ---- pipeline (маршруты вызовов) ----
    Pipeline pipe(3);
    std::vector<int> data = {1, 5, 2, 8, 4};
    std::cout << "pipe.classify        = " << pipe.classify(data) << "\n";
    std::cout << "pipe.normalize(350)  = " << pipe.normalize(350) << "\n";
    std::cout << "pipe.process(data)   = " << pipe.process(data) << "\n";
    std::cout << "pipe.process(empty)  = " << pipe.process({}) << "\n";
    // 101 элемента > порога: classify -> 101 hits; normalize(101): 101-100=1,
    // do+1=2 -> norm=3; hits(101) > norm(3) -> ветвь process if#3.
    std::vector<int> big(101, 5);
    std::cout << "pipe.process(big)    = " << pipe.process(big) << "\n";

    return 0;
}
