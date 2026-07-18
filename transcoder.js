const http = require('http');
const https = require('https');
const { spawn } = require('child_process');

function hasFFmpeg() {
  return new Promise((resolve) => {
    const p = spawn('ffmpeg', ['-version'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let ok = false;
    p.on('error', () => resolve(false));
    p.on('close', (code) => resolve(code === 0));
    p.stdout.on('data', () => { ok = true; });
    p.stderr.on('data', () => {});
    setTimeout(() => resolve(ok), 3000);
  });
}

function createTranscodeServer(opts = {}) {
  const { onStats } = opts;

  const server = http.createServer((req, res) => {
    const reqUrl = new URL(req.url, `http://${req.headers.host}`);
    if (reqUrl.pathname !== '/proxy') {
      res.writeHead(404); res.end();
      return;
    }

    const targetUrl = reqUrl.searchParams.get('url');
    if (!targetUrl) {
      res.writeHead(400); res.end('Missing url param');
      return;
    }

    const cookie = reqUrl.searchParams.get('cookie') || '';
    const referer = reqUrl.searchParams.get('referer') || '';

    proxyAndTranscode(targetUrl, { cookie, referer }, res, onStats);
  });

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      resolve({ server, port: server.address().port });
    });
  });
}

function proxyAndTranscode(targetUrl, headers, res, onStats) {
  const url = new URL(targetUrl);
  const mod = url.protocol === 'https:' ? https : http;

  const opts = {
    hostname: url.hostname,
    port: url.port || (url.protocol === 'https:' ? 443 : 80),
    path: url.pathname + url.search,
    method: 'GET',
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      Accept: '*/*',
    },
    timeout: 60000,
  };

  if (headers.cookie) opts.headers.Cookie = headers.cookie;
  if (headers.referer) opts.headers.Referer = headers.referer;

  const proxyReq = mod.request(opts, (proxyRes) => {
    const ct = proxyRes.headers['content-type'] || '';
    const sc = proxyRes.statusCode;

    if (sc >= 300 && sc < 400 && proxyRes.headers.location) {
      const loc = proxyRes.headers.location;
      const absUrl = loc.startsWith('http') ? loc : new URL(loc, targetUrl).href;
      const p = new URLSearchParams({ url: absUrl });
      if (headers.cookie) p.set('cookie', headers.cookie);
      if (headers.referer) p.set('referer', headers.referer);
      res.writeHead(302, { Location: `/proxy?${p}` });
      res.end();
      return;
    }

    if (ct.startsWith('video/') || ct.startsWith('application/vnd.apple.mpegurl')) {
      transcodeStream(proxyRes, res, onStats);
    } else {
      const outHeaders = { ...proxyRes.headers };
      delete outHeaders['transfer-encoding'];
      res.writeHead(sc, outHeaders);
      proxyRes.pipe(res);
    }
  });

  proxyReq.on('error', (err) => {
    res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Proxy error: ' + err.message);
  });

  proxyReq.on('timeout', () => {
    proxyReq.destroy();
    res.writeHead(504, { 'Content-Type': 'text/plain' });
    res.end('Gateway timeout');
  });

  proxyReq.end();
}

function transcodeStream(inputStream, res, onStats) {
  const ffmpeg = spawn('ffmpeg', [
    '-i', 'pipe:0',
    '-vf', 'fps=20',
    '-c:v', 'libx264',
    '-preset', 'ultrafast',
    '-crf', '28',
    '-c:a', 'copy',
    '-movflags', 'frag_keyframe+empty_moov',
    '-f', 'mp4',
    'pipe:1',
  ], { stdio: ['pipe', 'pipe', 'pipe'] });

  ffmpeg.stderr.on('data', () => {});

  let origBytes = 0;
  let compBytes = 0;

  inputStream.on('data', (c) => { origBytes += c.length; });
  ffmpeg.stdout.on('data', (c) => { compBytes += c.length; });

  res.writeHead(200, {
    'Content-Type': 'video/mp4',
    'Access-Control-Allow-Origin': '*',
    'Accept-Ranges': 'none',
  });

  inputStream.pipe(ffmpeg.stdin);
  ffmpeg.stdout.pipe(res);

  const cleanup = () => {
    try { ffmpeg.stdin.destroy(); } catch {}
    try { ffmpeg.kill(); } catch {}
    try { inputStream.destroy(); } catch {}
  };

  res.on('close', cleanup);
  inputStream.on('error', cleanup);
  ffmpeg.on('error', cleanup);

  ffmpeg.on('close', (code) => {
    if (code !== 0 && onStats) {
      onStats({ originalBytes: origBytes, compressedBytes: origBytes });
    } else if (onStats) {
      onStats({ originalBytes: origBytes, compressedBytes: compBytes });
    }
  });
}

module.exports = { createTranscodeServer, hasFFmpeg };
