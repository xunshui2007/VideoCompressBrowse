const { app, BrowserWindow, session } = require('electron');
const path = require('path');
const { createTranscodeServer, hasFFmpeg } = require('./transcoder');

let mainWindow;
let transcodeServer;
let ffmpegAvailable = false;

const VIDEO_EXT_RE = /\.(mp4|webm|m3u8|ts|m4s|mkv|avi|mov)(\?.*)?$/i;

let stats = { originalBytes: 0, compressedBytes: 0, count: 0 };

app.whenReady().then(async () => {
  ffmpegAvailable = await hasFFmpeg();
  transcodeServer = await createTranscodeServer({
    onStats: (s) => {
      stats.originalBytes += s.originalBytes;
      stats.compressedBytes += s.compressedBytes;
      stats.count += 1;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('compress-stats', { ...stats });
      }
    },
  });

  const ses = session.fromPartition('persist:browser');
  ses.webRequest.onBeforeRequest((details, callback) => {
    if (!ffmpegAvailable) return callback({});

    const isVideo = details.resourceType === 'media' || VIDEO_EXT_RE.test(details.url);
    if (!isVideo || details.url.startsWith('http://127.0.0.1:')) {
      return callback({});
    }

    const params = new URLSearchParams({ url: details.url });
    const h = details.requestHeaders || {};
    if (h.cookie) params.set('cookie', h.cookie);
    if (h.referer) params.set('referer', h.referer);

    callback({
      redirectURL: `http://127.0.0.1:${transcodeServer.port}/proxy?${params}`,
    });
  });

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      webviewTag: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
    autoHideMenuBar: true,
    title: '视频压缩浏览器',
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.send('compress-stats', { ...stats });
  });
});

app.on('window-all-closed', () => {
  if (transcodeServer) transcodeServer.close();
  if (process.platform !== 'darwin') app.quit();
});
