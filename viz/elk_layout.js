// elk_layout.js — вычисляет позиции узлов и маршруты рёбер через ELK
// Режимы:
//   node elk_layout.js <input.json>   — разовый: раскладка файла в stdout (обратная совместимость)
//   node elk_layout.js --server       — постоянный: по строке JSON-графа из stdin →
//                                        строка JSON-результата в stdout (без перезапуска node)

const ELK = require('elkjs/lib/elk.bundled.js');
const fs  = require('fs');

const elk = new ELK();
const arg = process.argv[2];

if (arg === '--server') {
    // ── Постоянный режим (persistent worker) ────────────────────────────────
    // Запросы — построчно (newline-delimited JSON, JSON.stringify не даёт literal \n).
    // Обрабатываем СТРОГО последовательно (очередь): elk.layout асинхронен.
    // Любая ошибка отдаётся как {"error": ...} и НЕ роняет процесс — пайп жив.
    let buffer = '';
    const queue = [];
    let busy = false;

    function pump() {
        if (busy || queue.length === 0) return;
        busy = true;
        const line = queue.shift();
        let graph;
        try {
            graph = JSON.parse(line);
        } catch (e) {
            process.stdout.write(JSON.stringify({ error: 'parse: ' + e.message }) + '\n');
            busy = false;
            return pump();
        }
        elk.layout(graph)
            .then(result => { process.stdout.write(JSON.stringify(result) + '\n'); })
            .catch(err   => { process.stdout.write(JSON.stringify({ error: String(err && err.message || err) }) + '\n'); })
            .then(()     => { busy = false; pump(); });
    }

    process.stdin.setEncoding('utf8');
    process.stdin.on('data', chunk => {
        buffer += chunk;
        let idx;
        while ((idx = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 1);
            if (line.trim()) { queue.push(line); pump(); }
        }
    });
    process.stdin.on('end', () => process.exit(0));

} else {
    // ── Разовый файловый режим ───────────────────────────────────────────────
    const path = arg;
    if (!path) {
        process.stderr.write('Usage: node elk_layout.js <input.json | --server>\n');
        process.exit(1);
    }
    const graph = JSON.parse(fs.readFileSync(path, 'utf8'));
    elk.layout(graph)
        .then(result => process.stdout.write(JSON.stringify(result)))
        .catch(err  => { process.stderr.write('ELK: ' + err.message + '\n'); process.exit(1); });
}
