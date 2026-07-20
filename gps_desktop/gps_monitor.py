import json, os, sys, threading, tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import deque

def icon_path():
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
    return os.path.join(base, 'gps_icon.ico')

latest = {}; lock = threading.Lock(); count = 0; start_t = datetime.now()
rssi_hist = deque(maxlen=120); gpx_pts = []
BEARING = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
CONST_C = {'GPS':'#267f4e','GLO':'#e8590c','BDS':'#e03131','GAL':'#1971c2','QZSS':'#9c36b5','IRN':'#6f4e37','SBAS':'#495057'}
CONST_E = {'GPS':'🟢GPS','GLO':'🟠GLO','BDS':'🔴BDS','GAL':'🔵GAL','QZSS':'🟣QZ','IRN':'🟤IR','SBAS':'⚪SB'}

def snr_color(v):
    if v >= 40: return '#099268'  # excellent
    if v >= 30: return '#2f9e44'  # good
    if v >= 20: return '#f08c00'  # fair
    if v >= 10: return '#e8590c'  # weak
    return '#e03131'              # poor

def rssi_color(v):
    if v is None: return '#6c7086'
    if v >= -50: return '#099268'
    if v >= -67: return '#2f9e44'
    if v >= -80: return '#f08c00'
    return '#e03131'
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG, exist_ok=True)
S = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
CSV = os.path.join(LOG, f'gps_{S}.csv'); GPX = os.path.join(LOG, f'gps_{S}.gpx'); JSONL = os.path.join(LOG, f'gps_{S}.jsonl')

def write_gpx():
    if not gpx_pts: return
    l = ['<?xml version="1.0"?><gpx version="1.1" creator="GPSMonitor"><trk><name>Track</name><trkseg>']
    for p in gpx_pts:
        l.append(f'<trkpt lat="{p[0]}" lon="{p[1]}">{"<ele>%.1f</ele>"%p[2] if p[2] else ""}<time>{p[3]}</time></trkpt>')
    l.append('</trkseg></trk></gpx>')
    with open(GPX, 'w') as f: f.write('\n'.join(l))

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        global count
        if self.path != '/api/gps': self.send_response(404); self.end_headers(); return
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        d['ts'] = datetime.now().strftime('%H:%M:%S')
        count += 1
        with lock: latest.clear(); latest.update(d)
        if d.get('wifi_rssi'): rssi_hist.append(d['wifi_rssi'])
        lat, lon = d.get('latitude'), d.get('longitude')
        if lat and lon:
            gpx_pts.append((lat, lon, d.get('altitude'), d['ts']))
            if len(gpx_pts) % 10 == 0: write_gpx()
        with open(JSONL, 'a') as f: f.write(json.dumps(d)+'\n')
        with open(CSV, 'a') as f:
            if os.path.getsize(CSV) == 0: f.write('time,lat,lon,alt,acc,prov,sats,wifi\n')
            f.write(f'{d["ts"]},{lat},{lon},{d.get("altitude")},{d.get("accuracy")},{d.get("provider")},{d.get("satellites")},{d.get("wifi_rssi")}\n')
        print(f'[{count}] lat={lat} prov={d.get("provider")}')
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'ok':True,'n':count}).encode())
    def do_GET(self):
        with lock: resp = json.dumps({'data': latest, 'n': count})
        self.send_response(200); self.end_headers(); self.wfile.write(resp.encode())
    def log_message(self, *a): pass

class App:
    def __init__(self, root):
        self.root = root
        root.title(f'GPS 信号监测 — {os.path.basename(GPX)}')
        try: root.iconbitmap(icon_path())
        except: pass
        root.geometry('860x700+80+10')
        root.configure(bg='#1a1d23'); root.minsize(700, 540)
        self._sat_key = ''; self._chart_n = 0; self.lb = {}

        # === Top bar (dark) ===
        bar = tk.Frame(root, bg='#1a1d23')
        bar.pack(fill='x', padx=16, pady=(10, 4))
        tk.Label(bar, text='🛰️  GPS 信号监测', font=('Segoe UI', 16, 'bold'), fg='#89b4fa', bg='#1a1d23').pack(side='left')

        self.srv_dot = tk.Canvas(bar, width=12, height=12, bg='#1a1d23', highlightthickness=0)
        self.srv_dot.pack(side='right', padx=(6,0))
        self._dot = self.srv_dot.create_oval(1, 1, 11, 11, fill='#585b70', outline='')
        self.srv_lb = tk.Label(bar, text='检测中', font=('Segoe UI', 9), fg='#6c7086', bg='#1a1d23')
        self.srv_lb.pack(side='right')
        self.elapsed_lb = tk.Label(bar, text='', font=('Segoe UI', 9), fg='#585b70', bg='#1a1d23')
        self.elapsed_lb.pack(side='right', padx=(0, 12))

        # === Main body ===
        body = tk.Frame(root, bg='#1a1d23')
        body.pack(fill='both', expand=True, padx=12, pady=(0, 10))

        # === INFO BAR (compact, always visible) ===
        info = tk.Frame(body, bg='#1a1d23')
        info.pack(fill='x', pady=(0, 6))
        info_cards = [
            ('GPS', 'gps_stat', '🔍 等待'),
            ('卫星', 'sat_stat', '—'),
            ('精度', 'acc_stat', '—'),
            ('坐标', 'pos_stat', '—'),
            ('WiFi', 'wifi_stat', '—'),
        ]
        self.stat_lb = {}
        for i, (label, key, default) in enumerate(info_cards):
            f = tk.Frame(info, bg='#313244', highlightbackground='#45475a', highlightthickness=1)
            f.pack(side='left', fill='x', expand=True, padx=(0 if i==0 else 2, 2))
            tk.Label(f, text=label, font=('Segoe UI', 8), fg='#6c7086', bg='#313244', anchor='w').pack(fill='x', padx=8, pady=(4,0))
            self.stat_lb[key] = tk.Label(f, text=default, font=('Consolas', 10, 'bold'), fg='#cdd6f4', bg='#313244', anchor='w')
            self.stat_lb[key].pack(fill='x', padx=8, pady=(0, 4))

        # === SATELLITE TABLE (MAIN FOCUS) ===
        sat_frame = tk.Frame(body, bg='#1a1d23')
        sat_frame.pack(fill='both', expand=True)

        hdr = tk.Frame(sat_frame, bg='#1a1d23')
        hdr.pack(fill='x')
        tk.Label(hdr, text='🛰️  卫星信号 — SNR (dB-Hz)', font=('Segoe UI', 11, 'bold'), fg='#89b4fa', bg='#1a1d23').pack(side='left')
        self.sat_cnt = tk.Label(hdr, text='', font=('Segoe UI', 9), fg='#6c7086', bg='#1a1d23')
        self.sat_cnt.pack(side='right')
        self.sat_cons = tk.Label(hdr, text='', font=('Segoe UI', 9), fg='#6c7086', bg='#1a1d23')
        self.sat_cons.pack(side='right', padx=(0, 8))

        # Filter bar
        fb = tk.Frame(sat_frame, bg='#1a1d23')
        fb.pack(fill='x', pady=1)
        tk.Label(fb, text='筛:', font=('Segoe UI', 8), fg='#585b70', bg='#1a1d23').pack(side='left', padx=(0,2))
        self.filt = {}
        self.afilt = set(CONST_C.keys())
        for c in ['GPS','GLO','BDS','GAL','QZSS']:
            cl = CONST_C.get(c,'#999')
            lb = tk.Label(fb, text=f'●{c}', font=('Segoe UI', 8, 'bold'), fg=cl,
                          bg='#45475a', cursor='hand2', padx=5, pady=1)
            lb.pack(side='left', padx=1)
            lb.bind('<Button-1>', lambda e, cc=c: self._tgl(cc))
            self.filt[c] = lb

        cols = ('#', '星座', 'SV', 'SNR', '信号条', '状态')
        self.sat_tree = ttk.Treeview(sat_frame, columns=cols, show='headings', height=14, selectmode='none')
        widths = [30, 55, 40, 55, 250, 50]
        for c, w in zip(cols, widths):
            self.sat_tree.heading(c, text=c)
            self.sat_tree.column(c, width=w, anchor='center' if c != '信号条' else 'w')
        # SNR color tags
        self.sat_tree.tag_configure('ex', foreground='#099268')
        self.sat_tree.tag_configure('gd', foreground='#2f9e44')
        self.sat_tree.tag_configure('fa', foreground='#f08c00')
        self.sat_tree.tag_configure('wk', foreground='#e8590c')
        self.sat_tree.tag_configure('po', foreground='#e03131')
        # Constellation color tags
        for tag, color in CONST_C.items():
            self.sat_tree.tag_configure(tag, foreground=color)
        self.sat_tree.pack(fill='both', expand=True, pady=(2, 0))

        # === Bottom row ===
        bottom = tk.Frame(body, bg='#1a1d23')
        bottom.pack(fill='x', pady=(6, 0))

        # WiFi + Chart (left)
        b_left = tk.Frame(bottom, bg='#313244', highlightbackground='#45475a', highlightthickness=1)
        b_left.pack(side='left', fill='both', expand=True, padx=(0, 3))

        tk.Label(b_left, text='📶 WiFi 信号', font=('Segoe UI', 9, 'bold'), fg='#a6adc8', bg='#313244',
                 anchor='w').pack(fill='x', padx=10, pady=(5, 2))
        self.wifi_lb = tk.Label(b_left, text='等待数据…', font=('Consolas', 10), fg='#cdd6f4', bg='#313244')
        self.wifi_lb.pack(fill='x', padx=10)
        self.wbar = tk.Canvas(b_left, height=6, bg='#45475a', highlightthickness=0)
        self.wbar.pack(fill='x', padx=10, pady=(2, 4))
        self._wf = self.wbar.create_rectangle(0, 0, 0, 6, width=0, fill='#a6e3a1')

        self.chart = tk.Canvas(b_left, height=40, bg='#313244', highlightthickness=0)
        self.chart.pack(fill='x', padx=10, pady=(0, 6))

        # Connection (right)
        b_right = tk.Frame(bottom, bg='#313244', highlightbackground='#45475a', highlightthickness=1)
        b_right.pack(side='left', fill='x', padx=(3, 0))

        tk.Label(b_right, text='🔗 连接', font=('Segoe UI', 9, 'bold'), fg='#a6adc8', bg='#313244',
                 anchor='w').pack(fill='x', padx=10, pady=(5, 2))
        self.conn_lb = tk.Label(b_right, text='等待手机…', font=('Consolas', 10), fg='#6c7086', bg='#313244')
        self.conn_lb.pack(fill='x', padx=10)
        self.count_lb = tk.Label(b_right, text='', font=('Consolas', 9), fg='#585b70', bg='#313244')
        self.count_lb.pack(fill='x', padx=10, pady=(0, 2))

        self.ip_lb = tk.Label(b_right, text='', font=('Consolas', 9), fg='#585b70', bg='#313244')
        self.ip_lb.pack(fill='x', padx=10, pady=(0, 2))
        self._show_ip()

        btn_f = tk.Frame(b_right, bg='#313244')
        btn_f.pack(fill='x', padx=10, pady=(2, 6))
        for t, c in [('📂日志', lambda: os.startfile(LOG)), ('⬇GPX', write_gpx)]:
            tk.Button(btn_f, text=t, command=c, font=('Segoe UI', 8), bd=0, cursor='hand2',
                      bg='#45475a', fg='#cdd6f4', padx=6).pack(side='left', padx=1)

        root.after(1500, self._srv_check)
        self._ela()

    def _ela(self):
        e = (datetime.now() - start_t).seconds
        h, m, s = e // 3600, e % 3600 // 60, e % 60
        self.elapsed_lb.configure(text=f'⏱ {h:02d}:{m:02d}:{s:02d}')
        self.root.after(1000, self._ela)

    def _srv_check(self):
        try:
            import urllib.request
            d = json.loads(urllib.request.urlopen('http://localhost:3000/api/gps', data=b'{}', timeout=1).read())
            self.srv_lb.configure(text=f'✓ {d["n"]}次', fg='#a6e3a1')
            self.srv_dot.itemconfig(self._dot, fill='#a6e3a1')
        except:
            self.srv_lb.configure(text='✗ 离线', fg='#f38ba8')
            self.srv_dot.itemconfig(self._dot, fill='#f38ba8')

    def _show_ip(self):
        ips = []
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ips.append(s.getsockname()[0])
            s.close()
        except: pass
        try:
            import subprocess
            out = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=5).stdout
            for line in out.split('\n'):
                if 'IPv4' in line and ':' in line:
                    ip = line.split(':')[-1].strip()
                    if ip and ip not in ips:
                        ips.append(ip)
        except: pass
        if ips:
            self.ip_lb.configure(text='🖥 ' + ' | '.join(ips))

    def _tgl(self, c):
        if c in self.afilt: self.afilt.discard(c)
        else: self.afilt.add(c)
        self._sat_key = ''  # force refresh
        for k, lb in self.filt.items():
            lb.configure(bg='#45475a' if k in self.afilt else '#1a1d23')

    def _refresh(self):
        with lock:
            d = dict(latest); n = count
        sec = (datetime.now() - start_t).seconds
        if n > 0:
            self.conn_lb.configure(text=f'✅ 已连接 ({n}次)', fg='#a6e3a1')
            rate = n / max(sec, 1)
            self.count_lb.configure(text=f'{rate:.1f}次/秒 | {len(gpx_pts)}点')
        else:
            self.conn_lb.configure(text='⏳ 等待手机…', fg='#6c7086')
        if not d: return

        lat, lon = d.get('latitude'), d.get('longitude')
        prov = d.get('provider', ''); acc = d.get('accuracy')
        spd = d.get('speed'); brg = d.get('bearing')
        sats = d.get('satellites', 0)
        ssid = d.get('wifi_ssid', ''); rssi = d.get('wifi_rssi')

        # Info bar updates
        gps_ok = lat and prov == 'gps'
        gps_txt = '✅定位' if gps_ok else (f'{prov[:4]}…' if lat else '🔍搜索')
        gps_c = '#a6e3a1' if gps_ok else ('#f9e2af' if lat else '#6c7086')
        self.stat_lb['gps_stat'].configure(text=gps_txt, fg=gps_c)
        self.stat_lb['sat_stat'].configure(text=f'{sats}颗' if sats else '0颗',
                                           fg='#a6e3a1' if sats > 5 else '#f9e2af')
        self.stat_lb['acc_stat'].configure(text=f'{acc:.0f}m' if acc else '—',
                                           fg='#a6e3a1' if acc and acc < 10 else '#f9e2af' if acc and acc < 50 else '#6c7086')
        self.stat_lb['pos_stat'].configure(text=f'{lat:.4f},{lon:.4f}' if lat else '—')
        if rssi:
            self.stat_lb['wifi_stat'].configure(text=f'{rssi}dBm', fg=rssi_color(rssi))
        elif ssid:
            self.stat_lb['wifi_stat'].configure(text=ssid[:10])
        else:
            self.stat_lb['wifi_stat'].configure(text='—')

        # WiFi bar
        if rssi:
            pct = max(0, min(100, (rssi+100)*2.5))
            w = max(self.wbar.winfo_width()-2, 50)
            self.wbar.coords(self._wf, 1, 1, 1+int(w*pct/100), 5)
            self.wbar.itemconfig(self._wf, fill=rssi_color(rssi))
        self.wifi_lb.configure(text=f'{ssid}  {rssi} dBm' if rssi else ssid or '无数据')

        # === SATELLITE TABLE (main feature) ===
        raw = d.get('satellites_detail')
        if raw and isinstance(raw, list):
            sk = json.dumps([(x.get('svid'),x.get('cn0'),x.get('const'),x.get('used')) for x in raw])
            if sk != self._sat_key:
                self._sat_key = sk
                for r in self.sat_tree.get_children(): self.sat_tree.delete(r)
                used = sum(1 for s in raw if s.get('used'))
                total = len(raw)
                # Constellation breakdown
                cons = {}
                for s in raw:
                    c = s.get('const', '?')
                    cons[c] = cons.get(c, 0) + 1
                cons_txt = '  '.join([f'{k}={v}' for k, v in sorted(cons.items()) if k in self.afilt])
                self.sat_cnt.configure(text=f'{used}/{total} 锁定')
                self.sat_cons.configure(text=cons_txt)

                filtered = [s for s in raw if s.get('const','?') in self.afilt]
                for i, s in enumerate(sorted(filtered, key=lambda x: x.get('cn0', 0), reverse=True), 1):
                    cn0 = s.get('cn0', 0); const = s.get('const', '?')
                    svid = s.get('svid', '?'); used_f = s.get('used', False)
                    bar_n = max(0, min(40, int(cn0 * 0.8)))
                    bar = '█' * bar_n + '░' * (40 - bar_n)
                    used_t = '✓' if used_f else '○'
                    snr_tag = 'ex' if cn0 >= 40 else 'gd' if cn0 >= 30 else 'fa' if cn0 >= 20 else 'wk' if cn0 >= 10 else 'po'
                    self.sat_tree.insert('', 'end',
                        values=(i, CONST_E.get(const, const), svid,
                                f'{cn0:.1f}', bar, used_t),
                        tags=(snr_tag, const))
                # Update count to reflect filter
                used_f = sum(1 for s in filtered if s.get('used'))
                self.sat_cnt.configure(text=f'{used_f}/{len(filtered)} 锁定')

        # Chart
        if len(rssi_hist) != self._chart_n:
            self._chart_n = len(rssi_hist)
            self.chart.delete('all')
            h = list(rssi_hist)
            if h:
                w = max(self.chart.winfo_width(), 150); mn, mx = min(h), max(h); rg = max(mx-mn, 1)
                pts = []
                for i, v in enumerate(h):
                    x = 4 + (i/(len(h)-1))*(w-8) if len(h) > 1 else w/2
                    y = 34*(1-(v-mn)/rg)+3
                    pts.extend([x, y])
                if pts:
                    self.chart.create_line(*pts, fill='#89b4fa', width=1.5, smooth=True)
                    self.chart.create_polygon(4, 37, *pts, w-4, 37, fill='#89b4fa', stipple='gray25', outline='')

    def update(self):
        try: self._refresh()
        except Exception as e: print(f'ERR: {e}')
        finally: self.root.after(500, self.update)

if __name__ == '__main__':
    import sys, subprocess as sp
    try:
        out = sp.run(['netstat','-ano'], capture_output=True, text=True, timeout=5).stdout
        for line in out.split('\n'):
            if ':3000 ' in line and 'LISTENING' in line:
                pid = line.strip().split()[-1]
                if pid.isdigit(): sp.run(['taskkill','/F','/PID',pid], capture_output=True, timeout=5)
    except: pass
    srv = HTTPServer(('0.0.0.0', 3000), Handler); srv.allow_reuse_address = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print('Server on http://0.0.0.0:3000')
    if '--console' in sys.argv:
        while True: import time; time.sleep(1)
    else:
        root = tk.Tk(); App(root).update(); root.mainloop()
    write_gpx()
