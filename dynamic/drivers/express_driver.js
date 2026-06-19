/*
 * Драйвер для Express: поднимает приложение на loopback и шлёт несколько запросов,
 * задействуя роутинг/middleware/ответы. Путь к express и HOME задаются снаружи.
 */
'use strict';
const http = require('http');
const express = require('./index.js');

const app = express();

// middleware
app.use((req, res, next) => { req.startedAt = Date.now(); next(); });
app.use(express.json());

// маршруты
app.get('/', (req, res) => { res.status(200).send('home'); });
app.get('/users/:id', (req, res) => {
    if (req.params.id === '0') { res.status(404).json({ error: 'not found' }); return; }
    res.json({ id: req.params.id, q: req.query });
});
app.post('/echo', (req, res) => { res.status(201).json({ got: req.body }); });
app.get('/redir', (req, res) => { res.redirect('/'); });
app.all('/any', (req, res) => { res.set('X-Custom', '1').send('any'); });

// 404 handler
app.use((req, res) => { res.status(404).send('missing'); });

function reqP(opts, body) {
    return new Promise((resolve) => {
        const r = http.request(opts, (res) => {
            let d = ''; res.on('data', (c) => d += c); res.on('end', () => resolve({ s: res.statusCode, d }));
        });
        r.on('error', () => resolve({ s: 0, d: '' }));
        if (body) r.write(body);
        r.end();
    });
}

const server = app.listen(0, '127.0.0.1', async () => {
    const port = server.address().port;
    const base = { host: '127.0.0.1', port };
    try {
        await reqP({ ...base, path: '/' });
        await reqP({ ...base, path: '/users/42?x=1' });
        await reqP({ ...base, path: '/users/0' });
        await reqP({ ...base, path: '/echo', method: 'POST',
                    headers: { 'Content-Type': 'application/json' } }, JSON.stringify({ a: 1 }));
        await reqP({ ...base, path: '/redir' });
        await reqP({ ...base, path: '/any', method: 'PUT' });
        await reqP({ ...base, path: '/nope' });
    } finally {
        server.close(() => { console.log('express driver: OK'); process.exit(0); });
    }
});
