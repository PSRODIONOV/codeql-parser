"""Регресс: рантайм Cqtrace.java должен переживать повторный вход (re-entrancy)
датчика на самого себя — реальный кейс из инструментации ЦЕЛОГО JDK-проекта
(nashorn/nasgen, gosjava): java.util.HashMap/ArrayDeque/ArrayList/ThreadLocal/
Writer, на которых построен ЭТОТ САМЫЙ рантайм, сами оказываются под
датчиками. hit() → cnt.put()/stack.get()/fp.write() (инструментированы) →
hit() → … без защиты — бесконечная рекурсия (StackOverflowError). См.
dynamic/runtime/Cqtrace.java.tmpl: static boolean inHit (НЕ ThreadLocal/
AtomicBoolean/synchronized — те сами были бы вызовами инструментируемых
методов) + catch (Throwable) вокруг тела hit() (NPE при вызове до завершения
<clinit> — java.lang.invoke.LambdaForm/ASM-байткод на раннем бутстрапе JVM).

Тест не инструментирует реальный java.util.* (нужен полный CodeQL Java
пайплайн) — проверяет КОНТРАКТ гарда напрямую через рефлексию на скомпилированном
рантайме: повторный вход при уже взведённом inHit должен мгновенно вернуться
без побочных эффектов, а обычный вызов должен сам сбросить inHit в finally."""
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

        // Гард уже "взведён" (как если бы мы сейчас были внутри hit(),
        // вызванного из инструментированного HashMap.put()/ArrayDeque.push()
        // и т.п.) — повторный вызов должен мгновенно вернуться.
        inHit.setBoolean(null, true);
        Cqtrace.hit(999, 0);
        if (!inHit.getBoolean(null)) {
            System.out.println("FAIL: guard was reset during simulated re-entrant call");
            System.exit(1);
        }
        System.out.println("REENTRANT_CALL_SHORT_CIRCUITED_OK");

        // После сброса гарда обычный вызов проходит штатно и сам сбрасывает
        // inHit обратно в false через finally (не остаётся взведённым навечно).
        inHit.setBoolean(null, false);
        Cqtrace.hit(1, 0);
        Cqtrace.hit(1, -1);
        if (inHit.getBoolean(null)) {
            System.out.println("FAIL: guard left armed after normal call");
            System.exit(1);
        }
        System.out.println("NORMAL_CALL_RESETS_GUARD_OK");
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
    classes = d / "classes"
    classes.mkdir()
    # -encoding utf-8 обязателен: шаблон содержит кириллические комментарии,
    # без явной кодировки javac берёт платформную (cp1251 на русской Windows)
    # и падает "unmappable character" — независимо от проекта пользователя.
    res = subprocess.run(
        ["javac", "-encoding", "utf-8", "-d", str(classes),
         str(src_dir / "Cqtrace.java"), str(src_dir / "Driver.java")],
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
