import csv
import json
import os
import threading
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import deque
import time as _time_mod

latest_data = {}
data_lock = threading.Lock()
rssi_history = deque(maxlen=120)
rssi_lock = threading.Lock()
gpx_points = []
request_count = 0
request_lock = threading.Lock()
last_contact = 0.0
gpx_lock = threading.Lock()

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
SESSION_START = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
CSV_LOG = os.path.join(LOG_DIR, f'gps_{SESSION_START}.csv')
JSON_LOG = os.path.join(LOG_DIR, f'gps_{SESSION_START}.jsonl')
GPX_LOG = os.path.join(LOG_DIR, f'gps_{SESSION_START}.gpx')
_csv_header_lock = threading.Lock()

BEARING_NAMES = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
CONST_COLORS = {'GPS': '#2e7d32', 'GLO': '#e65100', 'BDS': '#c62828', 'GAL': '#1565c0',
                'QZSS': '#6a1b9a', 'IRN': '#4e342e', 'SBAS': '#37474f'}
CONST_TAGS = {'GPS': 'G', 'GLO': 'R', 'BDS': 'C', 'GAL': 'E', 'QZSS': 'J', 'IRN': 'I', 'SBAS': 'S'}
BG = '#f0f2f5'; CARD = '#ffffff'; ACCENT = '#0078d4'; TEXT = '#1a1a1a'; SECONDARY = '#666666'; BORDER = '#e0e0e0'

def fmt_ts(ts_str):
    try:
        t = datetime.strptime(ts_str, '%H:%M:%S')
        return t.strftime('%Y-%m-%dT%H:%M:%SZ')
    except: return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

def write_gpx():
    with gpx_lock:
        pts = list(gpx_points)
    if not pts: return
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="GPSMonitor" xmlns="http://www.topografix.com/GPX/1/1">',
             '  <trk><name>GPS Track</name><trkseg>']
    for p in pts:
        lat, lon, alt, spd, brg, sats, ts = p
        lines.append(f'    <trkpt lat="{lat}" lon="{lon}">')
        if alt: lines.append(f'      <ele>{alt}</ele>')
        if spd: lines.append(f'      <speed>{spd}</speed>')
        if brg: lines.append(f'      <course>{brg}</course>')
        if sats: lines.append(f'      <sat>{sats}</sat>')
        lines.append(f'      <time>{ts}</time>')
        lines.append(f'    </trkpt>')
    lines.append('  </trkseg></trk></gpx>')
    with open(GPX_LOG, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

def write_log(d):
    ts = d.get('received_at', datetime.now().strftime('%H:%M:%S'))
    with open(JSON_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')
    row = {'time': ts, 'lat': d.get('latitude'), 'lon': d.get('longitude'),
           'alt': d.get('altitude'), 'acc': d.get('accuracy'), 'speed': d.get('speed'),
           'bearing': d.get('bearing'), 'sats': d.get('satellites'),
           'wifi_ssid': d.get('wifi_ssid'), 'wifi_rssi': d.get('wifi_rssi'),
           'wifi_freq': d.get('wifi_frequency'), 'phone_ip': d.get('phone_ip')}
    with _csv_header_lock:
        exists = os.path.exists(CSV_LOG) and os.path.getsize(CSV_LOG) > 0
        with open(CSV_LOG, 'a' if exists else 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists: w.writeheader()
            w.writerow(row)
    lat, lon = d.get('latitude'), d.get('longitude')
    if lat and lon:
        with gpx_lock:
            gpx_points.append((lat, lon, d.get('altitude'), d.get('speed'),
                               d.get('bearing'), d.get('satellites'), fmt_ts(ts)))
        if len(gpx_points) % 10 == 0:
            write_gpx()

def open_logs():
    os.startfile(LOG_DIR)

class GPSHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/gps':
            self.send_response(404); self.end_headers(); return
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        d['received_at'] = datetime.now().strftime('%H:%M:%S')
        with request_lock:
            global request_count, last_contact
            request_count += 1
            last_contact = _time_mod.time()
        with data_lock:
            latest_data.clear(); latest_data.update(d)
        write_log(d)
        with rssi_lock:
            r = d.get('wifi_rssi')
            if r is not None: rssi_history.append(r)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True}).encode())

    def do_GET(self):
        if self.path == '/api/latest':
            with data_lock: resp = json.dumps({'data': latest_data})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(resp.encode())
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, *args): pass


def card(parent, title=None):
    f = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill='x', pady=4)
    if title:
        tk.Label(f, text=title, font=('Segoe UI', 9, 'bold'), fg=SECONDARY, bg=CARD,
                 anchor='w').pack(fill='x', padx=14, pady=(8, 2))
    body = tk.Frame(f, bg=CARD)
    body.pack(fill='x', padx=14, pady=(2, 8))
    return body


class GPSMonitor:
    def __init__(self, root):
        self.root = root
        root.title('GPS 实时监测 — 轨迹导出: ' + os.path.basename(GPX_LOG))
        root.geometry('900x750+150+30')
        root.configure(bg=BG)
        root.minsize(720, 540)
        root.protocol('WM_DELETE_WINDOW', self._on_close)

        self._last_sat_key = ''
        self._last_chart_len = 0
        self.labels = {}

        bar = tk.Frame(root, bg=BG)
        bar.pack(fill='x', padx=16, pady=(10, 4))
        tk.Label(bar, text='GPS 实时监测', font=('Segoe UI', 20, 'bold'),
                 fg=ACCENT, bg=BG).pack(side='left')

        self.dot = tk.Canvas(bar, width=14, height=14, bg=BG, highlightthickness=0)
        self.dot.pack(side='right', padx=(8, 0))
        self.dot_oval = self.dot.create_oval(1, 1, 13, 13, fill='#bbb', outline='')
        self.update_time_lb = tk.Label(bar, text='--:--:--', font=('Segoe UI', 10),
                                        fg=SECONDARY, bg=BG)
        self.update_time_lb.pack(side='right')

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=16)

        # Top row: left + right (shrink to content)
        top_row = tk.Frame(body, bg=BG)
        top_row.pack(fill='x')

        left = tk.Frame(top_row, bg=BG)
        left.pack(side='left', fill='x', expand=True, padx=(0, 8))
        right = tk.Frame(top_row, bg=BG)
        right.pack(side='left', fill='x', expand=True, padx=(8, 0))

        # GPS (left)
        c = card(left, 'GPS 状态')
        self.labels['gps'] = tk.Label(c, text='等待数据…', font=('Segoe UI', 28, 'bold'),
                                       fg='#bbb', bg=CARD)
        self.labels['gps'].pack(anchor='w')
        self.labels['provider'] = tk.Label(c, text='', font=('Segoe UI', 9), fg=SECONDARY, bg=CARD)
        self.labels['provider'].pack(anchor='w')

        # Accuracy (left)
        c = card(left, '定位精度')
        self.labels['acc_val'] = tk.Label(c, text='-', font=('Segoe UI', 22, 'bold'),
                                           fg=TEXT, bg=CARD)
        self.labels['acc_val'].pack(anchor='w')
        self.labels['acc_desc'] = tk.Label(c, text='', font=('Segoe UI', 9),
                                            fg=SECONDARY, bg=CARD)
        self.labels['acc_desc'].pack(anchor='w')
        # Accuracy bar
        self.acc_bar = tk.Canvas(c, height=6, bg='#e0e0e0', highlightthickness=0)
        self.acc_bar.pack(fill='x', pady=(4, 0))
        self.acc_bar_fill = self.acc_bar.create_rectangle(0, 0, 0, 6, width=0)

        # Coordinates (left)
        c = card(left, '坐标')
        for key, name in [('lat', '纬度'), ('lon', '经度'), ('alt', '海拔')]:
            r = tk.Frame(c, bg=CARD)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=name, font=('Segoe UI', 9), fg=SECONDARY, bg=CARD,
                     width=5, anchor='w').pack(side='left')
            self.labels[key] = tk.Label(r, text='-', font=('Consolas', 12, 'bold'), fg=TEXT, bg=CARD)
            self.labels[key].pack(side='left')

        # WiFi (right)
        c = card(right, 'WiFi 信号')
        self.labels['wifi_ssid'] = tk.Label(c, text='-', font=('Consolas', 12, 'bold'), fg=TEXT, bg=CARD)
        self.labels['wifi_ssid'].pack(anchor='w')
        self.labels['wifi_rssi'] = tk.Label(c, text='-', font=('Segoe UI', 12), fg=SECONDARY, bg=CARD)
        self.labels['wifi_rssi'].pack(anchor='w')
        self.wbar = tk.Canvas(c, height=8, bg='#e0e0e0', highlightthickness=0)
        self.wbar.pack(fill='x', pady=(4, 0))
        self.wbar_fill = self.wbar.create_rectangle(0, 0, 0, 8, fill=ACCENT, width=0)

        # Speed & Bearing (right)
        c = card(right, '运动')
        fr = tk.Frame(c, bg=CARD)
        fr.pack(fill='x')
        for key, name in [('speed', '速度'), ('bearing', '方向')]:
            sub = tk.Frame(fr, bg=CARD)
            sub.pack(side='left', fill='x', expand=True)
            tk.Label(sub, text=name, font=('Segoe UI', 9), fg=SECONDARY, bg=CARD,
                     anchor='w').pack(anchor='w')
            self.labels[key] = tk.Label(sub, text='-', font=('Segoe UI', 20, 'bold'),
                                         fg=TEXT, bg=CARD, anchor='w')
            self.labels[key].pack(anchor='w')
        self.labels['bearing_dir'] = tk.Label(c, text='', font=('Segoe UI', 9),
                                               fg=SECONDARY, bg=CARD)
        self.labels['bearing_dir'].pack(anchor='w')

        # Connection & Export (right)
        c = card(right, '连接')
        self.labels['phone_ip'] = tk.Label(c, text='-', font=('Consolas', 10), fg=TEXT, bg=CARD)
        self.labels['phone_ip'].pack(anchor='w')
        self.labels['sats'] = tk.Label(c, text='-', font=('Segoe UI', 10), fg=TEXT, bg=CARD)
        self.labels['sats'].pack(anchor='w', pady=(2, 0))

        # Connection indicator
        conn_status = tk.Frame(c, bg=CARD)
        conn_status.pack(fill='x', pady=(4, 0))
        self.conn_dot = tk.Canvas(conn_status, width=10, height=10, bg=CARD, highlightthickness=0)
        self.conn_dot.pack(side='left', padx=(0, 6))
        self.conn_dot_oval = self.conn_dot.create_oval(1, 1, 9, 9, fill='#bbb', outline='')
        self.conn_label = tk.Label(conn_status, text='等待手机连接…', font=('Segoe UI', 9),
                                    fg=SECONDARY, bg=CARD)
        self.conn_label.pack(side='left')

        self.data_status = tk.Label(c, text='', font=('Segoe UI', 9), fg=SECONDARY, bg=CARD)
        self.data_status.pack(anchor='w')

        btn_row = tk.Frame(c, bg=CARD)
        btn_row.pack(fill='x', pady=(6, 0))
        tk.Button(btn_row, text='📂 打开日志目录', command=open_logs,
                  font=('Segoe UI', 9), bg='#f0f2f5', fg=TEXT, bd=1,
                  relief='solid', cursor='hand2').pack(side='left', padx=(0, 6))
        tk.Button(btn_row, text='⬇ 导出 GPX', command=self._export_gpx,
                  font=('Segoe UI', 9), bg=ACCENT, fg='white', bd=0,
                  cursor='hand2').pack(side='left')

        # Satellite table (full)
        sat_outer = tk.Frame(body, bg=BG)
        sat_outer.pack(fill='both', expand=True, pady=(4, 0))
        hdr = tk.Frame(sat_outer, bg=BG)
        hdr.pack(fill='x')
        tk.Label(hdr, text='卫星 SNR', font=('Segoe UI', 9, 'bold'),
                 fg=SECONDARY, bg=BG).pack(side='left')
        self.sat_count_lb = tk.Label(hdr, text='', font=('Segoe UI', 9),
                                      fg=SECONDARY, bg=BG)
        self.sat_count_lb.pack(side='right')

        cols = ('PRN', '星座', 'SNR (dB-Hz)', '信号强度', '使用')
        self.tree = ttk.Treeview(sat_outer, columns=cols, show='headings',
                                  height=7, selectmode='none')
        for c in cols:
            self.tree.heading(c, text=c)
        self.tree.column('PRN', width=55, anchor='center')
        self.tree.column('星座', width=60, anchor='center')
        self.tree.column('SNR (dB-Hz)', width=90, anchor='e')
        self.tree.column('信号强度', width=260)
        self.tree.column('使用', width=55, anchor='center')
        for tag, color in CONST_COLORS.items():
            self.tree.tag_configure(tag, foreground=color)
        self.tree.pack(fill='both', expand=True)

        # Chart
        chart_frame = tk.Frame(body, bg=BG)
        chart_frame.pack(fill='x', pady=(6, 0))
        tk.Label(chart_frame, text='WiFi 信号强度历史', font=('Segoe UI', 9, 'bold'),
                 fg=SECONDARY, bg=BG).pack(anchor='w')
        self.chart = tk.Canvas(chart_frame, height=60, bg=CARD,
                                highlightbackground=BORDER, highlightthickness=1)
        self.chart.pack(fill='x')

        # Status bar
        status = tk.Frame(root, bg='#e8e8e8')
        status.pack(fill='x', padx=16, pady=(6, 8))
        self.status_lb = tk.Label(status, text='监听 0.0.0.0:3000', font=('Segoe UI', 8),
                                   fg='#999', bg='#e8e8e8')
        self.status_lb.pack()

    def _export_gpx(self):
        write_gpx()
        self.status_lb.configure(text=f'GPX 已导出: {GPX_LOG}')
        self.root.after(3000, lambda: self.status_lb.configure(
            text='监听 0.0.0.0:3000'))

    def _on_close(self):
        write_gpx()
        self.root.destroy()

    def update(self):
        try:
            self._refresh()
        except Exception as e:
            print(f'Update: {e}')
        finally:
            self.root.after(500, self.update)

    def _refresh(self):
        # Connection status (always show, even without GPS data)
        with request_lock:
            rc = request_count
            lc = last_contact
        if rc > 0:
            elapsed = _time_mod.time() - lc
            if elapsed < 5:
                self.conn_dot.itemconfig(self.conn_dot_oval, fill='#4caf50')
                self.conn_label.configure(text=f'已连接 ({rc} 次请求)')
            else:
                self.conn_dot.itemconfig(self.conn_dot_oval, fill='#ff9800')
                self.conn_label.configure(text=f'上次连接 {elapsed:.0f}s 前 ({rc} 次)')
        else:
            self.conn_dot.itemconfig(self.conn_dot_oval, fill='#bbb')
            self.conn_label.configure(text='等待手机连接…')

        with data_lock:
            d = dict(latest_data)
        if not d:
            self.dot.itemconfig(self.dot_oval, fill='#bbb')
            return

        self.dot.itemconfig(self.dot_oval, fill='#4caf50')
        self.update_time_lb.configure(text=d.get('received_at', ''))

        lat = d.get('latitude'); lon = d.get('longitude')
        alt = d.get('altitude'); acc = d.get('accuracy')
        spd = d.get('speed'); brg = d.get('bearing')
        sats_cnt = d.get('satellites', 0)
        prov = d.get('provider', '')
        rssi = d.get('wifi_rssi'); ssid = d.get('wifi_ssid', '')

        gps_fix = lat is not None and prov == 'gps' and (acc is None or acc < 100)
        if gps_fix:
            self.labels['gps'].configure(text='GPS 已定位 ✓', fg='#2e7d32')
        elif lat:
            self.labels['gps'].configure(text=f'{prov} 定位中… (精度 {acc:.0f}m)' if acc else f'{prov} 定位中…',
                                         fg='#e65100')
        else:
            self.labels['gps'].configure(text='等待数据…', fg='#c62828')
        self.labels['provider'].configure(text=f'来源: {prov}' if prov else '')

        # Accuracy display
        if acc:
            self.labels['acc_val'].configure(
                text=f'{acc:.1f} m',
                fg='#2e7d32' if acc < 10 else '#e65100' if acc < 50 else '#c62828')
            if acc < 3: desc = '极高精度 ✓'
            elif acc < 10: desc = '高精度 ✓'
            elif acc < 30: desc = '中等精度'
            elif acc < 100: desc = '低精度 ⚠'
            else: desc = '不可靠 ✗'
            if sats_cnt: desc += f' | 卫星: {sats_cnt}'
            self.labels['acc_desc'].configure(text=desc)

            err_pct = max(0, min(100, 100 - acc * 2))
            bw = max(self.acc_bar.winfo_width() - 2, 100)
            self.acc_bar.coords(self.acc_bar_fill, 1, 1, 1 + int(bw * err_pct / 100), 5)
            err_color = '#4caf50' if acc < 10 else '#ff9800' if acc < 50 else '#f44336'
            self.acc_bar.itemconfig(self.acc_bar_fill, fill=err_color)
        else:
            self.labels['acc_val'].configure(text='-', fg=TEXT)
            self.labels['acc_desc'].configure(text='')

        for key, val in [('lat', f'{lat:.6f}°' if lat else '-'),
                         ('lon', f'{lon:.6f}°' if lon else '-'),
                         ('alt', f'{alt:.1f} m' if alt else '-')]:
            self.labels[key].configure(text=val)

        self.labels['speed'].configure(text=f'{spd:.1f}' if spd and spd > 0 else '0.0')
        if brg:
            idx = round(brg / 22.5) % 16
            self.labels['bearing'].configure(text=f'{brg:.0f}°')
            self.labels['bearing_dir'].configure(text=BEARING_NAMES[idx])
        else:
            self.labels['bearing'].configure(text='-°')
            self.labels['bearing_dir'].configure(text='')

        self.labels['wifi_ssid'].configure(text=ssid or '未连接')
        if rssi:
            pct = max(0, min(100, (rssi + 100) * 2.5))
            color = '#2e7d32' if rssi >= -67 else '#e65100' if rssi >= -80 else '#c62828'
            self.labels['wifi_rssi'].configure(text=f'{rssi} dBm  ({pct:.0f}%)', fg=color)
            cw = max(self.wbar.winfo_width() - 2, 50)
            self.wbar.coords(self.wbar_fill, 1, 1, 1 + int(cw * pct / 100), 7)
            self.wbar.itemconfig(self.wbar_fill, fill=color)
        else:
            self.labels['wifi_rssi'].configure(text='-', fg=SECONDARY)

        self.labels['phone_ip'].configure(text=f'手机: {d.get("phone_ip", "-")}')
        self.labels['sats'].configure(text=f'卫星: {sats_cnt} 锁定  |  {prov or "?"}')
        self.data_status.configure(text=f'数据: {len(d)} 字段 | 更新: {d.get("received_at", "-")}')

        # Sat table
        raw = d.get('satellites_detail', [])
        if not isinstance(raw, list): raw = []
        sat_key = json.dumps(raw, sort_keys=True)
        if sat_key != self._last_sat_key:
            self._last_sat_key = sat_key
            for row in self.tree.get_children(): self.tree.delete(row)
            if raw:
                used = sum(1 for s in raw if s.get('used'))
                self.sat_count_lb.configure(text=f'{used}/{len(raw)} 锁定')
                for s in sorted(raw, key=lambda x: x.get('cn0', 0), reverse=True):
                    cn0 = s.get('cn0', 0); const = s.get('const', '?')
                    svid = s.get('svid', '?'); used_f = s.get('used', False)
                    bar_n = max(0, min(20, int(cn0 / 5)))
                    bar_s = '█' * bar_n + '▁' * (20 - bar_n)
                    self.tree.insert('', 'end', values=(
                        f'{CONST_TAGS.get(const, "?")}{svid}',
                        const, f'{cn0:.1f}', bar_s, '✓' if used_f else '○'
                    ), tags=(const,))
            else:
                self.sat_count_lb.configure(text='')

        # Chart
        with rssi_lock:
            hist = list(rssi_history)
        if len(hist) != self._last_chart_len:
            self._last_chart_len = len(hist)
            self.chart.delete('all')
            if hist:
                w = max(self.chart.winfo_width(), 100); h = 56
                mn, mx = min(hist), max(hist); rng = max(mx - mn, 1)
                pts = []
                for i, v in enumerate(hist):
                    x = 6 + (i / (len(hist) - 1)) * (w - 12) if len(hist) > 1 else w / 2
                    y = (h - 10) * (1 - (v - mn) / rng) + 5
                    pts.extend([x, y])
                if pts:
                    self.chart.create_line(*pts, fill=ACCENT, width=1.5, smooth=True)
                    area = [6, h - 5] + pts + [w - 6, h - 5]
                    self.chart.create_polygon(*area, fill=ACCENT, stipple='gray25', outline='')


def start_server():
    HTTPServer(('0.0.0.0', 3000), GPSHandler).serve_forever()


if __name__ == '__main__':
    import sys
    import time as _time
    console = '--console' in sys.argv
    test_mode = '--test' in sys.argv

    # Kill old instances on port 3000
    try:
        import subprocess
        out = subprocess.check_output(
            'netstat -ano | findstr ":3000 " | findstr LISTENING',
            shell=True, text=True)
        for line in out.strip().split('\n'):
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[4]
                os.system(f'taskkill /F /PID {pid} >nul 2>&1')
    except: pass

    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    print(f'GPS 服务器运行在 http://0.0.0.0:3000')

    if test_mode:
        print('测试模式: 生成模拟 GPS 数据…')
        def mock_data():
            import random, math
            lat, lon = 31.83, 117.13
            while True:
                lat += random.uniform(-0.0005, 0.0005)
                lon += random.uniform(-0.0005, 0.0005)
                sats = random.randint(8, 18)
                detail = []
                for i in range(sats):
                    detail.append({"svid": i+1, "cn0": random.uniform(15, 48),
                                   "used": random.random() > 0.3,
                                   "const": random.choice(["GPS","GLO","BDS","GAL"])})
                d = {"latitude": lat, "longitude": lon, "altitude": random.uniform(10, 60),
                     "accuracy": random.uniform(3, 12), "speed": random.uniform(0, 3),
                     "bearing": random.uniform(0, 360), "satellites": sats,
                     "satellites_detail": detail,
                     "wifi_ssid": "TestWiFi", "wifi_rssi": random.randint(-85, -30),
                     "wifi_frequency": 2412, "phone_ip": "192.168.137.2",
                     "provider": "gps",
                     "received_at": datetime.now().strftime('%H:%M:%S')}
                with data_lock:
                    latest_data.clear(); latest_data.update(d)
                with rssi_lock:
                    rssi_history.append(d["wifi_rssi"])
                _time.sleep(1)
        threading.Thread(target=mock_data, daemon=True).start()

    if console:
        print('控制台模式，按 Ctrl+C 停止')
        try:
            while True: _time.sleep(1)
        except KeyboardInterrupt: print('已停止')
    else:
        try:
            root = tk.Tk()
            GPSMonitor(root)
            root.mainloop()
        except Exception as e:
            print(f'GUI 启动失败: {e}，已切换控制台模式')
            try:
                while True: _time.sleep(1)
            except KeyboardInterrupt: print('已停止')
