const express = require('express');
const path = require('path');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const history = [];
const MAX_HISTORY = 3600;

app.post('/api/gps', (req, res) => {
    const data = req.body;
    data.received_at = Date.now();
    history.push(data);
    if (history.length > MAX_HISTORY) history.shift();
    res.json({ ok: true, count: history.length });
});

app.get('/api/latest', (req, res) => {
    if (history.length === 0) return res.json({ data: null });
    res.json({ data: history[history.length - 1] });
});

app.get('/api/history', (req, res) => {
    const count = Math.min(parseInt(req.query.count) || 100, 500);
    res.json({ data: history.slice(-count) });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`GPS 服务器运行在 http://0.0.0.0:${PORT}`);
    console.log(`本机地址: http://localhost:${PORT}`);
});
