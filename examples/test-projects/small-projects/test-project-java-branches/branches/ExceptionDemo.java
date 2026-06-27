package branches;

public class ExceptionDemo {

    // 2 отслеживаемые ветви: тело try + вложенный if. catch делит номер
    // ветви с try (см. probe_points.ql: ref_line catch = ref_line try) —
    // отдельной строки в Перечень_ветвей для catch нет (датчик покрытия,
    // не ветвь, паритет с C++, см. docs/PRINCIPLES_C_CPP.md).
    int simpleTry(int x) {
        int r = -1;
        try {                            // ветвь #1 (try)
            if (x < 0) {                 // ветвь #2 (if) — внутри try-блока
                throw new RuntimeException("negative");
            }
            r = x * 2;
        } catch (RuntimeException e) {
            r = 0;
        }
        return r;
    }

    // 4 отслеживаемые ветви: тело try + 3 вложенных if (несколько catch не
    // дают доп. ветвей).
    int tryMultipleCatch(int code) {
        try {                                    // ветвь #1 (try)
            if (code == 1) {                      // ветвь #2 (if)
                throw new IllegalArgumentException("bad arg");
            }
            if (code == 2) {                      // ветвь #3 (if)
                throw new IndexOutOfBoundsException("oor");
            }
            if (code == 3) {                       // ветвь #4 (if)
                throw new RuntimeException("rt");
            }
            return 100;
        } catch (IllegalArgumentException e) {
            return 1;
        } catch (IndexOutOfBoundsException e) {
            return 2;
        } catch (RuntimeException e) {
            return 3;
        }
    }

    // 3 отслеживаемые ветви: внешний try + вложенный try + вложенный if.
    int nestedTry(int x) {
        int r = 0;
        try {                            // ветвь #1 (try, внешний)
            try {                        // ветвь #2 (try, вложенный)
                if (x == 0) {            // ветвь #3 (if)
                    throw new RuntimeException("zero");
                }
                r = 1000 / x;
            } catch (RuntimeException e) {
                throw e;                 // переброс наружу
            }
        } catch (RuntimeException e) {
            r = -1;
        }
        return r;
    }

    // 4 отслеживаемые ветви: тело try + тело for + вложенный if.
    int tryWithLoop(String s) {
        int vowels = 0;
        try {                                          // ветвь #1 (try)
            for (int i = 0; i < s.length(); ++i) {      // ветвь #2 (for)
                char c = s.charAt(i);
                if (c == 'a' || c == 'e' || c == 'i' ||
                    c == 'o' || c == 'u') {             // ветвь #3 (if)
                    ++vowels;
                }
            }
            if (vowels == 0) {                          // ветвь #4 (if)
                throw new RuntimeException("no vowels");
            }
        } catch (RuntimeException e) {
            return -1;
        }
        return vowels;
    }

    // 1 отслеживаемая ветвь: тело try (finally без своей ветви — как и
    // catch, это не точка решения).
    int tryFinally(int x) {
        int r;
        try {            // ветвь #1 (try)
            r = 100 / x;
        } finally {
            x = 0;
        }
        return r;
    }
}
