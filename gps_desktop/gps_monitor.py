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
_csv_header_written = False
_csv_header_lock = threading.Lock()

def write_log(d):
    global _csv_header_written
    ts = d.get('received_at', datetime.now().strftime('%H:%M:%S'))
    # JSONL
    with open(JSON_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')
    # CSV
    row = {
        'time': ts, 'lat': d.get('latitude'), 'lon': d.get('longitude'),
        'alt': d.get('altitude'), 'acc': d.get('accuracy'),
        'speed': d.get('speed'), 'bearing': d.get('bearing'),
        'sats': d.get('satellites'), 'provider': d.get('provider'),
        'wifi_ssid': d.get('wifi_ssid'), 'wifi_rssi': d.get('wifi_rssi'),
        'wifi_freq': d.get('wifi_frequency'), 'phone_ip': d.get('phone_ip')
    }
    with _csv_header_lock:
        exists = os.path.exists(CSV_LOG) and os.path.getsize(CSV_LOG) > 0
        mode = 'a' if exists else 'w'
        with open(CSV_LOG, mode, encoding='utf-8', newline='') as f:
            import csv
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not exists:
                w.writeheader()
            w.writerow(row)

CONST_COLORS = {
    'GPS': '#4caf50', 'GLO': '#ff9800', 'BDS': '#f44336',
    'GAL': '#2196f3', 'QZSS': '#9c27b0', 'IRN': '#795548',
    'SBAS': '#607d8b', '?': '#999'
}

class GPSHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/gps':
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        with data_lock:
            d = json.loads(body)
            d['received_at'] = datetime.now().strftime('%H:%M:%S')
            latest_data.clear()
            latest_data.update(d)
        write_log(d)
        with rssi_lock:
            rssi = d.get('wifi_rssi')
            if rssi is not None:
                rssi_history.append(rssi)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True}).encode())

    def do_GET(self):
        if self.path == '/api/latest':
            with data_lock:
                resp = json.dumps({'data': latest_data})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(resp.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class GPSMonitor:
    def __init__(self, root):
        self.root = root
        root.title("GPS 实时监测")
        root.geometry("880x680+100+50")
        root.configure(bg='#f0f2f5')
        root.minsize(720, 500)

        self.sat_tree = None
        self.fix_indicator = None

        style = ttk.Style()
        style.theme_use('clam')
        for c in ['#f0f2f5', '#4caf50', '#f44336', '#ff9800', '#333', '#888', '#1a73e8', 'white']:
            style.configure(c, background=c) if c != 'white' else None

        # === Header ===
        header = tk.Frame(root, bg='#f0f2f5')
        header.pack(fill='x', padx=16, pady=(12, 6))
        tk.Label(header, text='GPS 实时监测', font=('Segoe UI', 18, 'bold'),
                 fg='#1a73e8', bg='#f0f2f5').pack(side='left')

        self.status_dot = tk.Canvas(header, width=16, height=16, bg='#f0f2f5',
                                     highlightthickness=0)
        self.status_dot.pack(side='right', padx=(4, 0))
        self._dot = self.status_dot.create_oval(1, 1, 15, 15, fill='#ccc', outline='')

        # === Scrollable content ===
        canvas = tk.Canvas(root, bg='#f0f2f5', highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient='vertical', command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg='#f0f2f5')

        scroll_frame.bind('<Configure>',
                          lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set, width=880)

        canvas.pack(side='left', fill='both', expand=True, padx=(16, 0))
        scrollbar.pack(side='right', fill='y', padx=(0, 16))

        # === Top row: two columns ===
        top = tk.Frame(scroll_frame, bg='#f0f2f5')
        top.pack(fill='x')

        # Left: GPS Status card
        gps_card = self._card(top, 'GPS 状态')
        gps_card.pack(side='left', fill='both', expand=True, padx=(0, 6))
        self.gps_text = tk.Label(gps_card, text='等待数据…',
                                  font=('Segoe UI', 22, 'bold'), fg='#ff9800', bg='white')
        self.gps_text.pack(anchor='w', pady=(0, 2))
        self.provider_text = tk.Label(gps_card, text='', font=('Segoe UI', 10),
                                       fg='#888', bg='white')
        self.provider_text.pack(anchor='w')
        self.sat_count_text = tk.Label(gps_card, text='卫星: - / -',
                                        font=('Segoe UI', 10), fg='#555', bg='white')
        self.sat_count_text.pack(anchor='w', pady=(4, 0))

        # Right: Coordinates card
        coord_card = self._card(top, '坐标')
        coord_card.pack(side='left', fill='both', expand=True, padx=(6, 0))
        self.coord_labels = {}
        for label, key in [('纬度', 'latitude'), ('经度', 'longitude'),
                            ('海拔', 'altitude'), ('精度', 'accuracy')]:
            r = tk.Frame(coord_card, bg='white')
            r.pack(fill='x', pady=1)
            tk.Label(r, text=label, font=('Segoe UI', 9), fg='#888', bg='white',
                     width=5, anchor='w').pack(side='left')
            self.coord_labels[key] = tk.Label(r, text='-',
                font=('Consolas', 11, 'bold'), fg='#333', bg='white')
            self.coord_labels[key].pack(side='left')

        # === Speed + Bearing row ===
        mid = tk.Frame(scroll_frame, bg='#f0f2f5')
        mid.pack(fill='x', pady=(6, 0))

        speed_card = self._card(mid, '速度')
        speed_card.pack(side='left', fill='both', expand=True, padx=(0, 6))
        self.speed_text = tk.Label(speed_card, text='0.0',
                                    font=('Segoe UI', 20, 'bold'), fg='#333', bg='white')
        self.speed_text.pack(anchor='w')
        tk.Label(speed_card, text='m/s', font=('Segoe UI', 9),
                 fg='#888', bg='white').pack(anchor='w')

        bear_card = self._card(mid, '方向')
        bear_card.pack(side='left', fill='both', expand=True, padx=(6, 0))
        self.bearing_text = tk.Label(bear_card, text='-',
                                      font=('Segoe UI', 20, 'bold'), fg='#333', bg='white')
        self.bearing_text.pack(anchor='w')
        self.bearing_dir = tk.Label(bear_card, text='',
                                     font=('Segoe UI', 10), fg='#888', bg='white')
        self.bearing_dir.pack(anchor='w')

        # === WiFi card ===
        wifi_card = self._card(scroll_frame, 'WiFi 信号')
        wifi_card.pack(fill='x', pady=(6, 0))
        wifi_grid = tk.Frame(wifi_card, bg='white')
        wifi_grid.pack(fill='x')
        self.wifi_ssid_text = tk.Label(wifi_grid, text='-', font=('Consolas', 11, 'bold'),
                                        fg='#333', bg='white')
        self.wifi_ssid_text.pack(side='left', padx=(0, 20))
        self.wifi_rssi_text = tk.Label(wifi_grid, text='-', font=('Consolas', 11, 'bold'),
                                        fg='#888', bg='white')
        self.wifi_rssi_text.pack(side='left', padx=(0, 20))
        self.wifi_freq_text = tk.Label(wifi_grid, text='-', font=('Segoe UI', 9),
                                        fg='#888', bg='white')
        self.wifi_freq_text.pack(side='left')

        # WiFi signal bar (canvas)
        self.wifi_bar = tk.Canvas(wifi_card, height=14, bg='#eee',
                                   highlightthickness=0)
        self.wifi_bar.pack(fill='x', pady=(6, 0))
        self._wifi_fill = self.wifi_bar.create_rectangle(0, 0, 0, 14,
                                                          fill='#ccc', width=0)

        # === RSSI History chart ===
        chart_card = self._card(scroll_frame, '信号强度历史 (最近 120 秒)')
        chart_card.pack(fill='x', pady=(6, 0))
        self.chart = tk.Canvas(chart_card, height=80, bg='white',
                                highlightthickness=0)
        self.chart.pack(fill='x')

        # === Satellite table ===
        sat_card = self._card(scroll_frame, '卫星 SNR')
        sat_card.pack(fill='x', pady=(6, 0))
        self.sat_count_label = tk.Label(sat_card, text='等待数据…',
                                         font=('Segoe UI', 9), fg='#888', bg='white')
        self.sat_count_label.pack(anchor='w', pady=(0, 4))

        cols = ('PRN', '星座', 'SNR', '信号', '状态')
        self.sat_tree = ttk.Treeview(sat_card, columns=cols, show='headings',
                                      height=8, selectmode='none')
        for c in cols:
            self.sat_tree.heading(c, text=c)
        self.sat_tree.column('PRN', width=50, anchor='center')
        self.sat_tree.column('星座', width=50, anchor='center')
        self.sat_tree.column('SNR', width=80, anchor='e')
        self.sat_tree.column('信号', width=200)
        self.sat_tree.column('状态', width=70, anchor='center')
        self.sat_tree.pack(fill='x')

        # === Connection info ===
        conn_card = self._card(scroll_frame, '连接信息')
        conn_card.pack(fill='x', pady=(6, 16))
        self.phone_ip_text = tk.Label(conn_card, text='-',
                                       font=('Consolas', 10), fg='#333', bg='white')
        self.phone_ip_text.pack(anchor='w')
        self.last_upd_text = tk.Label(conn_card, text='-',
                                       font=('Segoe UI', 9), fg='#888', bg='white')
        self.last_upd_text.pack(anchor='w', pady=(2, 0))
        self.log_text = tk.Label(conn_card, text=f'日志: {CSV_LOG}',
                                  font=('Segoe UI', 8), fg='#aaa', bg='white')
        self.log_text.pack(anchor='w', pady=(2, 0))

    def _card(self, parent, title):
        f = tk.Frame(parent, bg='white', bd=0, highlightthickness=1,
                     highlightcolor='#e0e0e0', highlightbackground='#e0e0e0')
        tk.Label(f, text=title, font=('Segoe UI', 10, 'bold'),
                 fg='#555', bg='white', anchor='w').pack(fill='x', padx=12, pady=(8, 4))
        c = tk.Frame(f, bg='white')
        c.pack(fill='x', padx=12, pady=(0, 10))
        return c

    def _bearing_name(self, deg):
        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        if deg is None: return ''
        idx = round(deg / 22.5) % 16
        return f'({dirs[idx]})'

    def update(self):
        with data_lock:
            d = dict(latest_data)
        if not d:
            self.status_dot.itemconfig(self._dot, fill='#ccc')
            self.root.after(500, self.update)
            return

        self.status_dot.itemconfig(self._dot, fill='#4caf50')

        loc = d.get('latitude') is not None
        gps_ok = loc and (d.get('accuracy') is None or d['accuracy'] < 100)

        if gps_ok:
            self.gps_text.configure(text='已定位 ✓', fg='#4caf50')
        elif loc:
            self.gps_text.configure(text='定位中…', fg='#ff9800')
        else:
            self.gps_text.configure(text='无信号', fg='#f44336')
        self.provider_text.configure(text=f'来源: {d.get("provider", "?")}')

        sats = d.get('satellites_detail', [])
        total_sats = d.get('satellites', 0)
        total_visible = len(sats) if sats else 0
        self.sat_count_text.configure(text=f'卫星: {total_sats} 锁定 / {total_visible} 可见')

        for key, label in self.coord_labels.items():
            v = d.get(key)
            label.configure(text=f'{v:.6f}' if isinstance(v, float) and key in ('latitude', 'longitude')
                            else f'{v:.1f} m' if isinstance(v, float) and key == 'altitude'
                            else f'{v:.1f} m' if isinstance(v, float) and key == 'accuracy'
                            else '-')

        spd = d.get('speed', 0)
        self.speed_text.configure(text=f'{spd:.1f}' if isinstance(spd, (int, float)) else '-')

        brg = d.get('bearing')
        if isinstance(brg, (int, float)):
            self.bearing_text.configure(text=f'{brg:.0f}°')
            self.bearing_dir.configure(text=self._bearing_name(brg))
        else:
            self.bearing_text.configure(text='-')
            self.bearing_dir.configure(text='')

        # WiFi
        ssid = d.get('wifi_ssid', '-')
        self.wifi_ssid_text.configure(text=f'{ssid}')
        rssi = d.get('wifi_rssi')
        if rssi is not None:
            pct = max(0, min(100, (rssi + 100) * 2.5))
            color = '#4caf50' if rssi >= -67 else '#ff9800' if rssi >= -80 else '#f44336'
            self.wifi_rssi_text.configure(text=f'{rssi} dBm  ({pct:.0f}%)', fg=color)
            cw = self.wifi_bar.winfo_width() - 2 or 200
            self.wifi_bar.coords(self._wifi_fill, 1, 1, 1 + int(cw * pct / 100), 13)
            self.wifi_bar.itemconfig(self._wifi_fill, fill=color)
        else:
            self.wifi_rssi_text.configure(text='-', fg='#888')
        self.wifi_freq_text.configure(text=f'{d.get("wifi_frequency", "-")} MHz')

        # RSSI history chart
        with rssi_lock:
            hist = list(rssi_history)
        if hist:
            w = self.chart.winfo_width() or 600
            h = 78
            self.chart.delete('all')
            self.chart.create_line(5, h - 5, w - 5, h - 5, fill='#eee', width=1)
            mn, mx = min(hist), max(hist)
            rng = max(mx - mn, 1)
            pts = []
            for i, v in enumerate(hist):
                x = 5 + (i / max(len(hist) - 1, 1)) * (w - 10)
                y = (h - 10) * (1 - (v - mn) / rng) + 5
                pts.extend([x, y])
            if len(pts) >= 4:
                self.chart.create_line(*pts, fill='#1a73e8', width=1.5, smooth=True)
                # Fill area
                area_pts = [5, h - 5] + pts + [w - 10, h - 5]
                self.chart.create_polygon(*area_pts, fill='#1a73e8', stipple='gray25', outline='')

        # Satellite table
        if self.sat_tree:
            for row in self.sat_tree.get_children():
                self.sat_tree.delete(row)
            if sats and len(sats) > 0:
                used = sum(1 for s in sats if s.get('used'))
                self.sat_count_label.configure(text=f'{used}/{len(sats)} 锁定')
                for s in sorted(sats, key=lambda x: x.get('cn0', 0), reverse=True):
                    cn0 = s.get('cn0', 0)
                    const = s.get('const', '?')
                    svid = s.get('svid', '?')
                    used_f = '✓' if s.get('used', False) else '○'
                    cc = CONST_COLORS.get(const, '#999')

                    # Signal bar
                    bar_pct = max(0, min(100, cn0 * 2.5))
                    bar_color = '#4caf50' if cn0 >= 40 else '#ff9800' if cn0 >= 25 else '#f44336'

                    self.sat_tree.insert('', 'end', values=(
                        svid,
                        f'{const}',
                        f'{cn0:.1f}',
                        f'{"█" * int(bar_pct / 10)}{"▒" * (10 - int(bar_pct / 10))}',
                        used_f
                    ), tags=(const,))
                # Color rows by constellation
                for c in CONST_COLORS:
                    self.sat_tree.tag_configure(c, foreground=CONST_COLORS[c])
            else:
                self.sat_count_label.configure(text='无卫星数据')

        self.phone_ip_text.configure(text=f'手机 IP: {d.get("phone_ip", "-")}')
        self.last_upd_text.configure(text=f'最后更新: {d.get("received_at", "-")}')

        self.root.after(500, self.update)


def start_server():
    server = HTTPServer(('0.0.0.0', 3000), GPSHandler)
    server.serve_forever()


if __name__ == '__main__':
    import sys
    console = '--console' in sys.argv

    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    print(f'GPS 服务器运行在 http://0.0.0.0:3000')

    if console:
        print('控制台模式，按 Ctrl+C 停止')
        try:
            while True:
                import time; time.sleep(1)
        except KeyboardInterrupt:
            print('已停止')
    else:
        try:
            root = tk.Tk()
            app = GPSMonitor(root)
            root.after(500, app.update)
            root.mainloop()
        except tk.TclError:
            print('无法启动 GUI，已切换至控制台模式')
            print('按 Ctrl+C 停止')
            try:
                while True:
                    import time; time.sleep(1)
            except KeyboardInterrupt:
                print('已停止')
