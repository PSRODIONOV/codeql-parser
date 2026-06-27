package branches;

public class SwitchDemo {

    // 8 отслеживаемых ветвей: каждая case-метка (включая участников
    // fallthrough-групп) и default — отдельная ветвь (как в C++,
    // см. negative_demo.cpp::weekday_kind в test-project-cpp-branches).
    int weekdayKind(int d) {
        switch (d) {
            case 0:                 // ветвь #1 (case)
            case 6:                 // ветвь #2 (case)
                return 0;           // выходной
            case 1:                 // ветвь #3 (case)
            case 2:                 // ветвь #4 (case)
            case 3:                 // ветвь #5 (case)
            case 4:                 // ветвь #6 (case)
            case 5:                 // ветвь #7 (case)
                return 1;           // рабочий
            default:                // ветвь #8 (default)
                return -1;
        }
    }

    // 3 отслеживаемые ветви: один case без break (настоящий fallthrough
    // в теле, а не группа меток подряд), второй case + default.
    int fallthroughSum(int x) {
        int r = 0;
        switch (x) {
            case 1:                 // ветвь #1 (case)
                r += 1;
                // упал дальше в case 2 — без break
            case 2:                 // ветвь #2 (case)
                r += 2;
                break;
            default:                // ветвь #3 (default)
                r = -1;
        }
        return r;
    }
}
