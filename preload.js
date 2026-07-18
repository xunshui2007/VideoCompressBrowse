const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('browserAPI', {
  webviewReady: (webContentsId) => ipcRenderer.send('webview-ready', webContentsId),
  onCompressStats: (callback) => ipcRenderer.on('compress-stats', (_event, data) => callback(data)),
});
