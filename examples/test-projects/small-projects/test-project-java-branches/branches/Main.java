package branches;

import java.util.Arrays;

// main вызывает все методы так, чтобы КАЖДАЯ отслеживаемая ветвь (then у if,
// тело for/while/do, тело try, каждая case-метка) реально выполнилась хотя бы
// раз — нужно для проверки сопоставления статических и динамических маршрутов
// (см. main.cpp в test-project-cpp-branches, тот же принцип).
public class Main {
    public static void main(String[] args) {
        // ---- BranchDemo ----
        BranchDemo bd = new BranchDemo(5);
        System.out.println(bd.ifBranch(3));
        System.out.println(bd.ifBranch(-3));
        System.out.println(bd.forBranch(4));
        System.out.println(bd.whileBranch(3));
        System.out.println(bd.tryBranch(2));
        System.out.println(bd.tryBranch(0));
        System.out.println(bd.helper());
        System.out.println(bd.helper(7));
        System.out.println(bd.helper(-7));

        // ---- LoopDemo ----
        LoopDemo ld = new LoopDemo();
        System.out.println(ld.sumFor(10));
        System.out.println(ld.nestedFor(3, 4));
        int[] arr = {1, -2, 3, 7, 5};
        System.out.println(ld.forWithBreak(arr, 5, 7));
        System.out.println(ld.countDownWhile(64));
        System.out.println(ld.doWhileDemo(4));
        System.out.println(ld.whileWithIf(9));

        // ---- SwitchDemo ----
        SwitchDemo sd = new SwitchDemo();
        System.out.println(sd.weekdayKind(0));   // case 0 (+fallthrough 6)
        System.out.println(sd.weekdayKind(1));   // case 1..5
        System.out.println(sd.weekdayKind(6));   // case 6
        System.out.println(sd.weekdayKind(9));   // default
        System.out.println(sd.fallthroughSum(1)); // case 1 -> падает в case 2
        System.out.println(sd.fallthroughSum(2)); // case 2
        System.out.println(sd.fallthroughSum(9)); // default

        // ---- ExceptionDemo ----
        ExceptionDemo ed = new ExceptionDemo();
        System.out.println(ed.simpleTry(5));
        System.out.println(ed.simpleTry(-1));
        System.out.println(ed.tryMultipleCatch(1));
        System.out.println(ed.tryMultipleCatch(2));
        System.out.println(ed.tryMultipleCatch(3));
        System.out.println(ed.tryMultipleCatch(0));
        System.out.println(ed.nestedTry(4));
        System.out.println(ed.nestedTry(0));
        System.out.println(ed.tryWithLoop("hello"));
        System.out.println(ed.tryWithLoop("xyz"));
        System.out.println(ed.tryFinally(5));

        // ---- NegativeDemo (НЕ должно инструментироваться) ----
        NegativeDemo nd = new NegativeDemo();
        System.out.println(nd.sumRange(Arrays.asList(1, 2, 3, 4)));
        System.out.println(nd.signAndFlags(2, 3));
        System.out.println(nd.retryLabeled(3));

        // ---- OtherDemo ----
        OtherDemo od = new OtherDemo();
        System.out.println(od.describe());
    }
}
