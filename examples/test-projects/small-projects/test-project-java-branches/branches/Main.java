package branches;

import java.util.Arrays;
import java.util.List;

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

        // ---- IfDemo ----
        IfDemo id = new IfDemo();
        System.out.println(id.simpleIf(5));
        System.out.println(id.ifElse(4));
        System.out.println(id.ifElse(7));
        System.out.println(id.elseIfChain(95));
        System.out.println(id.elseIfChain(80));
        System.out.println(id.elseIfChain(65));
        System.out.println(id.elseIfChain(45));
        System.out.println(id.nestedIf(3, 2));
        System.out.println(id.nestedIf(3, -2));
        System.out.println(id.ifWithLogical(2, 3));

        // ---- AdvancedDemo ----
        AdvancedDemo ad = new AdvancedDemo();
        System.out.println(ad.cstrLen("hello"));
        System.out.println(ad.skipSpaces("   x"));
        System.out.println(ad.classifyEmpty(5));
        System.out.println(ad.classifyEmpty(-5));
        System.out.println(ad.doOnce(6));
        System.out.println(ad.doOnce(-1));
        int[] az = {3, 1, 0, 7};
        System.out.println(ad.findFirstZero(az, 4));
        int[] azNz = {3, 1, 7};   // без нуля -> ветвь "i >= n" (не найдено)
        System.out.println(ad.findFirstZero(azNz, 3));
        System.out.println(ad.isPalindrome("abba", 4));
        System.out.println(ad.isPalindrome("abc", 3));
        System.out.println(ad.safeDiv(10, 2));
        System.out.println(ad.safeDiv(10, 0));
        System.out.println(ad.countPositive(Arrays.asList(-1, 2, -3, 4, 5)));
        System.out.println(ad.factorial(5));
        System.out.println(ad.braceLiteralGuard('x', true));
        // открывающая фигурная скобка через код символа (0x7B) — литерал
        // самой скобки не должен попадать в текст Main.java (регресс на
        // символ скобки в условии проверяется внутри AdvancedDemo.braceLiteralGuard).
        char openBrace = (char) 0x7B;
        System.out.println(ad.braceLiteralGuard(openBrace, true));
        System.out.println(ad.caseNoSpaceKind(9));
        System.out.println(ad.caseNoSpaceKind(0));

        // ---- Pipeline ----
        Pipeline pipe = new Pipeline(3);
        List<Integer> data = Arrays.asList(1, 5, 2, 8, 4);
        System.out.println(pipe.classify(data));
        System.out.println(pipe.normalize(350));
        System.out.println(pipe.process(data));
        System.out.println(pipe.process(Arrays.<Integer>asList()));
        // 101 элемент > порога: classify -> 101 hits; normalize(101):
        // 101-100=1, do+1=2 -> norm=3; hits(101) > norm(3) -> ветвь process if#3
        // (см. тот же расчёт в main.cpp у test-project-cpp-branches).
        List<Integer> big = new java.util.ArrayList<>();
        for (int i = 0; i < 101; ++i) { big.add(5); }
        System.out.println(pipe.process(big));

        // ---- OtherDemo ----
        OtherDemo od = new OtherDemo();
        System.out.println(od.describe());
    }
}
