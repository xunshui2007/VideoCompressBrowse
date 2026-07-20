import csv
import json
import os
import threading
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import deque

latest_data = {}
data_lock = threading.Lock()
rssi_history = deque(maxlen=120)
rssi_lock = threading.Lock()

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
SESSION_START = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
CSV_LOG = os.path.join(LOG_DIR, f'gps_{SESSION_START}.csv')
JSON_LOG = os.path.join(LOG_DIR, f'gps_{SESSION_START}.jsonl')
_csv_header_lock = threading.Lock()

CONST_NAMES = {'GPS': 'G', 'GLO': 'R', 'BDS': 'C', 'GAL': 'E', 'QZSS': 'J', 'IRN': 'I', 'SBAS': 'S'}
CONST_COLORS = {'GPS': '#4caf50', 'GLO': '#ff9800', 'BDS': '#f44336', 'GAL': '#2196f3',
                'QZSS': '#9c27b0', 'IRN': '#795548', 'SBAS': '#607d8b'}
BEARING_NAMES = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

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

class GPSHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/gps':
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get('Content-Length', 0))
        d = json.loads(self.rfile.read(length))
        d['received_at'] = datetime.now().strftime('%H:%M:%S')
        with data_lock:
            latest_data.clear(); latest_data.update(d)
        write_log(d)
        with rssi_lock:
            rssi = d.get('wifi_rssi')
            if rssi is not None: rssi_history.append(rssi)
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

class GPSMonitor:
    def __init__(self, root):
        self.root = root
        root.title('GPS 实时监测')
        root.geometry('700x600+150+50')
        root.configure(bg='#1e1e2e')
        self._last_sat_data = ''
        self._last_chart_data = 0

        # Main container
        main = tk.Frame(root, bg='#1e1e2e')
        main.pack(fill='both', expand=True, padx=12, pady=8)

        # Status bar
        sb = tk.Frame(main, bg='#1e1e2e')
        sb.pack(fill='x', pady=(0, 6))
        tk.Label(sb, text='GPS 实时监测', font=('Segoe UI', 16, 'bold'),
                 fg='#89b4fa', bg='#1e1e2e').pack(side='left')
        self.stat_dot = tk.Canvas(sb, width=12, height=12, bg='#1e1e2e', highlightthickness=0)
        self.stat_dot.pack(side='right')
        self._dot = self.stat_dot.create_oval(1, 1, 11, 11, fill='#585b70', outline='')

        # Info grid
        self.lb = {}
        g = tk.Frame(main, bg='#1e1e2e')
        g.pack(fill='x')
        row_defs = [
            [('gps', 'GPS', 0), ('sats', '卫星', 0)],
            [('lat', '纬度', 6), ('lon', '经度', 6)],
            [('alt', '海拔', 6), ('acc', '精度', 6)],
            [('speed', '速度', 6), ('bearing', '方向', 6)],
            [('wifi', 'WiFi', 6)],
        ]
        for ri, defs in enumerate(row_defs):
            r = tk.Frame(g, bg='#1e1e2e')
            r.pack(fill='x', pady=1)
            for label, name, pad in defs:
                f = tk.Frame(r, bg='#313244', bd=0)
                f.pack(side='left', fill='both', expand=True, padx=(0, pad))
                tk.Label(f, text=name, font=('Segoe UI', 9), fg='#a6adc8',
                         bg='#313244', anchor='w').pack(fill='x', padx=10, pady=(6, 0))
                v = tk.Label(f, text='-', font=('Consolas', 13, 'bold'),
                             fg='#cdd6f4', bg='#313244', anchor='w')
                v.pack(fill='x', padx=10, pady=(0, 6))
                self.lb[label] = v

        # Satellite frame (scrollable)
        sat_frame = tk.Frame(main, bg='#1e1e2e')
        sat_frame.pack(fill='both', expand=True, pady=(6, 0))
        tk.Label(sat_frame, text='卫星 SNR', font=('Segoe UI', 10, 'bold'),
                 fg='#89b4fa', bg='#1e1e2e').pack(anchor='w')
        self.sat_container = tk.Frame(sat_frame, bg='#313244')
        self.sat_container.pack(fill='both', expand=True)
        self.sat_empty = tk.Label(self.sat_container, text='等待数据…',
                                   font=('Segoe UI', 9), fg='#6c7086', bg='#313244')
        self.sat_empty.pack(expand=True)

        # WiFi signal chart
        chart_frame = tk.Frame(main, bg='#1e1e2e')
        chart_frame.pack(fill='x', pady=(6, 0))
        tk.Label(chart_frame, text='WiFi 信号历史 (120s)', font=('Segoe UI', 9, 'bold'),
                 fg='#89b4fa', bg='#1e1e2e').pack(anchor='w')
        self.chart = tk.Canvas(chart_frame, height=50, bg='#313244', highlightthickness=0)
        self.chart.pack(fill='x')

        # Bottom bar
        bb = tk.Frame(main, bg='#1e1e2e')
        bb.pack(fill='x', pady=(4, 0))
        self.phone_ip_lb = tk.Label(bb, text='等待连接…', font=('Segoe UI', 9),
                                     fg='#6c7086', bg='#1e1e2e')
        self.phone_ip_lb.pack(side='left')
        self.log_lb = tk.Label(bb, text=os.path.basename(CSV_LOG), font=('Segoe UI', 8),
                                fg='#585b70', bg='#1e1e2e')
        self.log_lb.pack(side='right')

    def update(self):
        try:
            self._refresh()
        except Exception as e:
            print(f'Update: {e}')
        finally:
            self.root.after(500, self.update)

    def _refresh(self):
        with data_lock:
            d = dict(latest_data)
        if not d:
            self.stat_dot.itemconfig(self._dot, fill='#585b70')
            return

        self.stat_dot.itemconfig(self._dot, fill='#a6e3a1')

        lat = d.get('latitude'); lon = d.get('longitude')
        alt = d.get('altitude'); acc = d.get('accuracy')
        spd = d.get('speed'); brg = d.get('bearing')
        sats = d.get('satellites', 0)
        prov = d.get('provider', '')
        rssi = d.get('wifi_rssi')
        ssid = d.get('wifi_ssid', '')
        freq = d.get('wifi_frequency', '')

        gps_ok = lat is not None and (acc is None or acc < 100)
        gps_txt = '已定位' if gps_ok else (f'{prov}…' if lat else '搜索中')
        gps_clr = '#a6e3a1' if gps_ok else ('#f9e2af' if lat else '#f38ba8')
        self.lb['gps'].configure(text=gps_txt, fg=gps_clr)

        self.lb['sats'].configure(text=f'{sats}' if sats else '-')
        self.lb['lat'].configure(text=f'{lat:.6f}°' if lat else '-')
        self.lb['lon'].configure(text=f'{lon:.6f}°' if lon else '-')
        self.lb['alt'].configure(text=f'{alt:.0f} m' if alt else '-')
        self.lb['acc'].configure(text=f'{acc:.0f} m' if acc else '-')
        self.lb['speed'].configure(text=f'{spd:.1f} m/s' if spd else '-')
        if brg:
            idx = round(brg / 22.5) % 16
            self.lb['bearing'].configure(text=f'{brg:.0f}° {BEARING_NAMES[idx]}')
        else:
            self.lb['bearing'].configure(text='-')

        wifi_parts = []
        if ssid: wifi_parts.append(ssid)
        if rssi: wifi_parts.append(f'{rssi} dBm')
        if freq: wifi_parts.append(f'{freq} MHz')
        rssi_color = '#a6e3a1'
        if rssi:
            if rssi < -80: rssi_color = '#f38ba8'
            elif rssi < -67: rssi_color = '#f9e2af'
        self.lb['wifi'].configure(text='  '.join(wifi_parts) if wifi_parts else '-', fg=rssi_color)

        # Satellites
        raw = d.get('satellites_detail', [])
        if not isinstance(raw, list): raw = []
        sat_key = json.dumps(raw, sort_keys=True)
        if sat_key != self._last_sat_data:
            self._last_sat_data = sat_key
            for w in self.sat_container.winfo_children(): w.destroy()
            if raw:
                used = sum(1 for s in raw if s.get('used'))
                lines = []
                for s in sorted(raw, key=lambda x: x.get('cn0', 0), reverse=True):
                    cn0 = s.get('cn0', 0)
                    const = s.get('const', '?')
                    svid = s.get('svid', '?')
                    used_f = s.get('used', False)
                    cn = CONST_NAMES.get(const, '?')
                    bar_w = max(0, min(20, int(cn0 / 5)))
                    bar = '█' * bar_w + '░' * (20 - bar_w)
                    lines.append(f'{cn}{svid:>3d}  {cn0:5.1f}  {bar}')
                text = '\n'.join(lines)
                tk.Label(self.sat_container, text=text,
                         font=('Consolas', 10), fg='#cdd6f4', bg='#313244',
                         justify='left', anchor='nw').pack(fill='both', expand=True, padx=8, pady=6)
                self.sat_container.pack_propagate(False)
            else:
                tk.Label(self.sat_container, text='无卫星数据',
                         font=('Segoe UI', 9), fg='#6c7086', bg='#313244').pack(expand=True)

        # Chart
        with rssi_lock:
            hist = list(rssi_history)
        if len(hist) != self._last_chart_data:
            self._last_chart_data = len(hist)
            self.chart.delete('all')
            if hist:
                w = self.chart.winfo_width() or 600; h = 48
                mn, mx = min(hist), max(hist); rng = max(mx - mn, 1)
                pts = []
                for i, v in enumerate(hist):
                    x = 4 + (i / (len(hist) - 1)) * (w - 8) if len(hist) > 1 else w / 2
                    y = (h - 8) * (1 - (v - mn) / rng) + 4
                    pts.extend([x, y])
                if pts:
                    self.chart.create_line(*pts, fill='#89b4fa', width=1.5, smooth=True)
                    area = [4, h - 4] + pts + [w - 4, h - 4]
                    self.chart.create_polygon(*area, fill='#89b4fa', stipple='gray25', outline='')

        self.phone_ip_lb.configure(text=f'手机: {d.get("phone_ip", "-")}')
        self.log_lb.configure(text=d.get('received_at', ''))

def start_server():
    HTTPServer(('0.0.0.0', 3000), GPSHandler).serve_forever()

if __name__ == '__main__':
    import sys
    console = '--console' in sys.argv
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    print(f'GPS 服务器运行在 http://0.0.0.0:3000')
    if console:
        print('控制台模式，按 Ctrl+C 停止')
        try:
            while True: import time; time.sleep(1)
        except KeyboardInterrupt: print('已停止')
    else:
        try:
            root = tk.Tk()
            GPSMonitor(root)
            root.mainloop()
        except Exception as e:
            print(f'GUI 启动失败: {e}，已切换控制台模式')
            try:
                while True: import time; time.sleep(1)
            except KeyboardInterrupt: print('已停止')
