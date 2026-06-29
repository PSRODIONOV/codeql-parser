"""Регресс: рантайм Cqtrace.java должен переживать повторный вход (re-entrancy)
датчика на самого себя на ОДНОМ потоке — при инструментации целого JDK
java.util.HashMap/ArrayDeque/ArrayList/ThreadLocal/Writer, на которых
построен этот рантайм, сами оказываются под датчиками: hit() →
cnt.put()/stack.get()/fp.write() (инструментированы) → hit() → … без защиты
— бесконечная рекурсия. См. dynamic/runtime/Cqtrace.java.tmpl: boolean[]
inHit, индексируемый по слоту потока (Thread.currentThread().getId() —
нативный метод, не рекурсирует) + catch (Throwable) вокруг тела hit() (NPE
при вызове до завершения <clinit> — java.lang.invoke.LambdaForm/ASM-байткод
на раннем бутстрапе JVM).

Тест не инструментирует реальный java.util.* (нужен полный CodeQL Java
пайплайн) — проверяет КОНТРАКТ гарда напрямую через рефлексию на скомпилированном
рантайме: повторный вход на ТОМ ЖЕ потоке при уже взведённом слоте должен
мгновенно вернуться без побочных эффектов, а обычный вызов должен сам
сбросить свой слот в finally."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TMPL = ROOT / "dynamic" / "runtime" / "Cqtrace.java.tmpl"

DRIVER = """
package test;
import java.lang.reflect.Field;

public class Driver {
    public static void main(String[] args) throws Exception {
        Field inHit = Cqtrace.class.getDeclaredField("inHit");
        inHit.setAccessible(true);
        boolean[] arr = (boolean[]) inHit.get(null);
        int slot = (int) (Thread.currentThread().getId() & (arr.length - 1));

        // Слот ЭТОГО потока уже "взведён" (как если бы мы сейчас были
        // внутри hit(), вызванного из инструментированного
        // HashMap.put()/ArrayDeque.push() и т.п.) — повторный вызов на
        // ЭТОМ ЖЕ потоке должен мгновенно вернуться.
        arr[slot] = true;
        Cqtrace.hit(999, 0);
        if (!arr[slot]) {
            System.out.println("FAIL: guard was reset during simulated re-entrant call");
            System.exit(1);
        }
        System.out.println("REENTRANT_CALL_SHORT_CIRCUITED_OK");

        // После сброса гарда обычный вызов проходит штатно и сам сбрасывает
        // свой слот обратно в false через finally (не остаётся взведённым
        // навечно).
        arr[slot] = false;
        Cqtrace.hit(1, 0);
        Cqtrace.hit(1, -1);
        if (arr[slot]) {
            System.out.println("FAIL: guard left armed after normal call");
            System.exit(1);
        }
        System.out.println("NORMAL_CALL_RESETS_GUARD_OK");
    }
}
"""

CONCURRENCY_DRIVER = """
package test;

public class ConcurrencyDriver {
    public static void main(String[] args) throws Exception {
        int nThreads = 8, iters = 5000;
        Thread[] ts = new Thread[nThreads];
        for (int t = 0; t < nThreads; t++) {
            final int id = t;
            ts[t] = new Thread(() -> {
                for (int i = 0; i < iters; i++) {
                    Cqtrace.hit(id, 0);
                    Cqtrace.hit(id, -1);
                }
            });
        }
        for (Thread th : ts) th.start();
        for (Thread th : ts) th.join();
        System.out.println("DONE");
    }
}
"""


@pytest.fixture(scope="module")
def compiled_classes(tmp_path_factory):
    if shutil.which("javac") is None or shutil.which("java") is None:
        pytest.skip("javac/java не найдены в PATH")
    d = tmp_path_factory.mktemp("cqtrace_runtime")
    src_dir = d / "src" / "test"
    src_dir.mkdir(parents=True)
    tmpl = TMPL.read_text(encoding="utf-8")
    cq = tmpl.replace("@PACKAGE@", "test").replace("@LANG@", "reentrancy-test")
    (src_dir / "Cqtrace.java").write_text(cq, encoding="utf-8")
    (src_dir / "Driver.java").write_text(DRIVER, encoding="utf-8")
    (src_dir / "ConcurrencyDriver.java").write_text(CONCURRENCY_DRIVER, encoding="utf-8")
    classes = d / "classes"
    classes.mkdir()
    # -encoding utf-8 обязателен: шаблон содержит кириллические комментарии,
    # без явной кодировки javac берёт платформную (cp1251 на русской Windows)
    # и падает "unmappable character" — независимо от проекта пользователя.
    res = subprocess.run(
        ["javac", "-encoding", "utf-8", "-d", str(classes),
         str(src_dir / "Cqtrace.java"), str(src_dir / "Driver.java"),
         str(src_dir / "ConcurrencyDriver.java")],
        capture_output=True, text=True)
    assert res.returncode == 0, f"javac не скомпилировал рантайм:\n{res.stderr}"
    return classes


def test_reentrant_hit_does_not_recurse(compiled_classes):
    res = subprocess.run(["java", "-cp", str(compiled_classes), "test.Driver"],
                         capture_output=True, text=True)
    assert res.returncode == 0, (
        f"Driver завершился с ошибкой (гард не сработал?):\n"
        f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    )
    assert "REENTRANT_CALL_SHORT_CIRCUITED_OK" in res.stdout
    assert "NORMAL_CALL_RESETS_GUARD_OK" in res.stdout


def test_concurrent_threads_are_not_starved(compiled_classes, tmp_path):
    """Один общий boolean inHit (без слотов на поток) давал лайвлок под
    конкуренцией многих потоков в тугом цикле: поток, успевающий взвести/
    снять флаг быстрее остальных, не оставляет другим окна, где флаг снят
    — остальные блокируются практически навсегда, а не "теряют одно
    событие". 8 потоков, каждый со своим fo; события всех 8 должны
    попасть в трассу, а не только у одного потока-"победителя"."""
    home = tmp_path / "home"
    home.mkdir()
    res = subprocess.run(
        ["java", f"-Duser.home={home}", "-cp", str(compiled_classes), "test.ConcurrencyDriver"],
        capture_output=True, text=True)
    assert res.returncode == 0, f"ConcurrencyDriver упал:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    logs = list(home.glob("reentrancy-test-*.log"))
    assert logs, "трасса не создана"
    text = "\n".join(p.read_text(encoding="utf-8") for p in logs)
    seen_fo = {int(line.split(":", 1)[0]) for line in text.splitlines()
               if line and ":" in line and line[0].isdigit()}
    missing = set(range(8)) - seen_fo
    assert not missing, f"события потоков {sorted(missing)} отсутствуют в трассе — гард их заблокировал"
