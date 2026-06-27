package branches;

import java.util.List;

public class AdvancedDemo {

    // 1 ветвь (while): тело пустое (валидный пустой BlockStmt — у Java нет
    // безблочных форм, см. probe_points.ql, поэтому в отличие от C++
    // (`while (*p++) ;`) пустое тело здесь оформлено как {}).
    int cstrLen(String s) {
        int i = 0;
        while (i < s.length()) { i++; }   // ветвь #1 (while)
        return i;
    }

    // 1 ветвь (for): тело пустое.
    int skipSpaces(String s) {
        int i = 0;
        for (; i < s.length() && s.charAt(i) == ' '; ++i) { }  // ветвь #1 (for)
        return i;
    }

    // 1 ветвь (if): then-ветвь пустая (намеренная заглушка), else — своя
    // ветвь с ТЕМ ЖЕ номером (паритет с BranchDemo.ifBranch).
    int classifyEmpty(int x) {
        int r = 0;
        if (x > 0) { }          // ветвь #1 (if), пустой then
        else { r = -x; }        // ветвь #1 (else)
        return r;
    }

    // 2 ветви: тело do (#1) + вложенный if (#2). do-while(false) написан руками.
    // У Java нет безблочных форм (см. probe_points.ql — branchBlock ждёт
    // BlockStmt), поэтому, в отличие от C++ (`if (x < 0) break;` без {}),
    // здесь тело if в скобках — иначе ветвь не получит датчик (probe-точки
    // без BlockStmt-тела молча пропускаются геометрией).
    int doOnce(int x) {
        int r = 0;
        do {                          // ветвь #1 (do)
            if (x < 0) { break; }     // ветвь #2 (if)
            r = x * x;
        } while (false);
        return r;
    }

    // 3 ветви: тело for (#1) + два вложенных if (#2, #3). Бесконечный for с break.
    int findFirstZero(int[] a, int n) {
        int i = 0;
        for (;;) {                       // ветвь #1 (for)
            if (i >= n) { return -1; }   // ветвь #2 (if)
            if (a[i] == 0) { return i; } // ветвь #3 (if)
            ++i;
        }
    }

    // 2 ветви: тело for (#1) + вложенный if (#2). for со встречными индексами
    // (две expr через запятую в update — валидный Java).
    boolean isPalindrome(String s, int n) {
        for (int i = 0, j = n - 1; i < j; ++i, --j) {     // ветвь #1 (for)
            if (s.charAt(i) != s.charAt(j)) { return false; }  // ветвь #2 (if)
        }
        return true;
    }

    // 2 ветви: тело try (#1) + вложенный if (#2). У Java нет
    // function-try-block (`int f() try {...} catch...`, см. safe_div в
    // advanced_demo.cpp) — обычный try внутри тела метода даёт тот же
    // паритет по числу ветвей.
    int safeDiv(int a, int b) {
        try {                              // ветвь #1 (try)
            if (b == 0) {                  // ветвь #2 (if)
                throw new RuntimeException("div by zero");
            }
            return a / b;
        } catch (RuntimeException e) {
            return 0;
        }
    }

    // 2 ветви: тело for (#1) + вложенный if (#2). В C++ analog (count_positive)
    // условие "x > 0" оформлено как if внутри лямбды (operator() замыкания
    // там инструментируется как самостоятельный ФО) — у Java синтетические
    // методы лямбд/method reference исключены из инструментации целиком
    // (см. probe_points.ql: not exists(FunctionalExpr fe | fe.asMethod() = ...) —
    // их «тело» не всегда литеральный блок, обёртка датчиком рискует
    // сломать синтаксис), поэтому здесь то же условие — обычный if в теле
    // метода, без лямбды.
    int countPositive(List<Integer> v) {
        int c = 0;
        for (int i = 0; i < v.size(); ++i) {   // ветвь #1 (for)
            if (v.get(i) > 0) {                // ветвь #2 (if)
                ++c;
            }
        }
        return c;
    }

    // 1 ветвь (if) + маршрут вызовов factorial -> factorial (рекурсия).
    long factorial(int n) {
        if (n <= 1) { return 1; }      // ветвь #1 (if)
        return n * factorial(n - 1);
    }

    // 1 ветвь (if): символьный литерал '{' в условии И настоящая открывающая
    // { тела — на ОДНОЙ строке (паттерн HotSpot adlc/adlparse.cpp::
    // get_oplist). Регресс на то, что инструментатор берёт уже проверенную
    // координату из CodeQL, а не ищет '{' заново наивным поиском по строке.
    boolean braceLiteralGuard(char c, boolean flag) {
        if (c != '{' && flag) {       // ветвь #1 (if) — литерал '{' в условии
            return true;
        }
        return false;
    }

    // 2 ветви (case): метки без пробела перед телом (паттерн HotSpot
    // c1_LIR.hpp::as_BasicType: `case ...:return ...;`). Регресс на то, что
    // колонка вставки датчика (ins_col-1) не разрезает первое слово тела.
    int caseNoSpaceKind(int x) {
        switch (x) {
            case 9:return 99;          // ветвь #1 (case) — без пробела перед телом
            default:return -1;         // ветвь #2 (default) — без пробела перед телом
        }
    }
}
