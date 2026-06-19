<?php
/**
 * cqtrace.php — рантайм датчиков динамического анализа для PHP.
 *
 * Копируется в корень инструментированного проекта; каждый .php-файл
 * получает в начале: require_once __DIR__ . '/cqtrace.php';
 *
 * API:
 *   cqtrace_hit(int $fo, int $br)           — датчик ветви (br ≥ 0).
 *   cqtrace_fn(int $fo, int $se, int $sx)   — вход ФО; возвращает
 *     __CqtraceGuard, деструктор которого автоматически пишет выход.
 *
 * Анти-спам: датчик ($fo,$br) пишется при срабатываниях №1,2,4,8,…
 * Ротация:   ~/php-YYYYMMDD-HHMMSS-<pid>.log, новый файл каждые 100 МБ.
 */

if (!defined('CQTRACE_LOADED')) {
    define('CQTRACE_LOADED', true);

    $__cq_cnt   = [];
    $__cq_rsig  = [];
    $__cq_stack = [];   // кадры: ['fo'=>fo, 'br'=>[ветви], 'cl'=>[self, вызовы]]
    $__cq_fp    = null;
    $__cq_bytes = 0;

    define('__CQ_ROT_LIMIT', 100 * 1024 * 1024);

    function __cq_write(string $s): void {
        global $__cq_fp, $__cq_bytes;
        if ($__cq_fp === null || $__cq_bytes >= __CQ_ROT_LIMIT) {
            __cq_rotate();
        }
        if ($__cq_fp !== null) {
            $n = fwrite($__cq_fp, $s);
            if ($n !== false) {
                $__cq_bytes += $n;
            }
            fflush($__cq_fp);
        }
    }

    // Выгрузка маршрута с анти-спамом по сигнатуре (1,2,4,8…).
    function __cq_emit(string $tag, int $fo, array $seq): void {
        global $__cq_rsig;
        $body = implode('>', $seq);
        $key  = $tag . $fo . ':' . $body;
        $c = ($__cq_rsig[$key] ?? 0) + 1;
        $__cq_rsig[$key] = $c;
        if ($c !== 1 && ($c & ($c - 1)) !== 0) {
            return;
        }
        __cq_write("$tag $fo:$body\n");
    }

    // Обслуживание буфера фактического маршрута (схлопывание подряд-повторов).
    function __cq_route_event(int $fo, int $br): void {
        global $__cq_stack;
        if ($br === 0) {                       // вход в ФО
            $n = count($__cq_stack);
            if ($n > 0) {                      // записать как вызов в кадре-родителе
                $cl =& $__cq_stack[$n - 1]['cl'];
                if (end($cl) !== $fo) { $cl[] = $fo; }
                unset($cl);
            }
            $__cq_stack[] = ['fo' => $fo, 'br' => [], 'cl' => [$fo]];
        } elseif ($br === -1) {                // выход — выгрузка обоих маршрутов
            $fr = array_pop($__cq_stack);
            if ($fr !== null) {
                __cq_emit('R', $fr['fo'], $fr['br']);
                __cq_emit('C', $fr['fo'], $fr['cl']);
            }
        } else {                               // ветвь — дописать (без подряд-повторов)
            $n = count($__cq_stack);
            if ($n > 0) {
                $b =& $__cq_stack[$n - 1]['br'];
                if (end($b) !== $br) { $b[] = $br; }
                unset($b);
            }
        }
    }

    function __cq_rotate(): void {
        global $__cq_fp, $__cq_bytes;
        $ts   = date('Ymd-His');
        $home = getenv('HOME') ?: (getenv('USERPROFILE') ?: '.');
        $path = $home . DIRECTORY_SEPARATOR . 'php-' . $ts . '-' . getmypid() . '.log';
        if ($__cq_fp !== null) {
            fclose($__cq_fp);
        }
        $__cq_fp    = fopen($path, 'a');
        $__cq_bytes = 0;
    }

    function cqtrace_hit(int $fo, int $br): void {
        global $__cq_cnt;
        __cq_route_event($fo, $br);   // фактический маршрут — всегда
        $k = "$fo:$br";
        $c = ($__cq_cnt[$k] ?? 0) + 1;
        $__cq_cnt[$k] = $c;
        // coverage-строка: только степени двойки 1,2,4,8,…
        if ($c !== 1 && ($c & ($c - 1)) !== 0) {
            return;
        }
        __cq_write("$fo:$br\n");
    }

    class __CqtraceGuard {
        private int $fo;
        public function __construct(int $fo, int $se, int $sx) {
            $this->fo = $fo;
            cqtrace_hit($fo, 0);   // вход ФО
        }
        public function __destruct() {
            cqtrace_hit($this->fo, -1);  // выход ФО (любой путь возврата)
        }
    }

    function cqtrace_fn(int $fo, int $se, int $sx): __CqtraceGuard {
        return new __CqtraceGuard($fo, $se, $sx);
    }
}
?>
