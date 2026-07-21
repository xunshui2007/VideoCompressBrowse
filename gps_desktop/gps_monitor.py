import json, os, sys, threading, tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import deque
from dataclasses import dataclass, field

BG = '#1a1d23'; CARD = '#313244'; BORDER = '#45475a'
TEXT = '#cdd6f4'; DIM = '#6c7086'; DARK = '#585b70'
ACCENT = '#89b4fa'; GREEN = '#a6e3a1'; YELLOW = '#f9e2af'; RED = '#f38ba8'
BEARING = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
CONST_E = {'GPS':'🟢GPS','GLO':'🟠GLO','BDS':'🔴BDS','GAL':'🔵GAL','QZSS':'🟣QZ'}
LOG = os.path.join(os.path.dirname(__file__), 'logs')

def init_log(log_dir=None):
    global LOG
    if log_dir: LOG = log_dir
    os.makedirs(LOG, exist_ok=True)
init_log()

@dataclass
class Device:
    ip: str
    data: dict = field(default_factory=dict)
    rssi: deque = field(default_factory=lambda: deque(maxlen=120))
    gpx: list = field(default_factory=list)
    count: int = 0
    seen: float = 0.0
    csv: str = ''
    jsonl: str = ''
    gpx_path: str = ''

devices: dict[str, Device] = {}
dev_lock = threading.Lock()

def _band(const, mhz):
    if const == 'GPS':
        if abs(mhz-1575.42)<1.5: return f'L1 {mhz:.1f}'
        if abs(mhz-1227.60)<1.5: return f'L2 {mhz:.1f}'
        if abs(mhz-1176.45)<1.5: return f'L5 {mhz:.1f}'
    if const == 'BDS':
        if abs(mhz-1575.42)<1.5: return f'B1C {mhz:.1f}'
        if abs(mhz-1561.10)<1.5: return f'B1I {mhz:.1f}'
        if abs(mhz-1268.52)<2: return f'B3 {mhz:.1f}'
        if abs(mhz-1207.14)<1.5: return f'B2b {mhz:.1f}'
        if abs(mhz-1176.45)<1.5: return f'B2a {mhz:.1f}'
    if const == 'GAL':
        if abs(mhz-1575.42)<1.5: return f'E1 {mhz:.1f}'
        if abs(mhz-1176.45)<1.5: return f'E5a {mhz:.1f}'
        if abs(mhz-1207.14)<1.5: return f'E5b {mhz:.1f}'
    if const == 'GLO':
        if 1598<=mhz<=1610: return f'G1 {mhz:.1f}'
        if 1242<=mhz<=1254: return f'G2 {mhz:.1f}'
    return f'{mhz:.1f}'

def write_gpx(dev):
    if not dev.gpx: return
    l = ['<?xml version="1.0"?><gpx version="1.1" creator="GPSMonitor"><trk><name>Track</name><trkseg>']
    for p in dev.gpx:
        l.append(f'<trkpt lat="{p[0]}" lon="{p[1]}">{"<ele>%.1f</ele>"%p[2] if p[2] else ""}<time>{p[3]}</time></trkpt>')
    l.append('</trkseg></trk></gpx>')
    with open(dev.gpx_path, 'w') as f: f.write('\n'.join(l))

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/api/gps': return
        ip = self.client_address[0]
        d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        ts = datetime.now().strftime('%H:%M:%S')
        d['ts'] = ts
        with dev_lock:
            if ip not in devices:
                s = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                dev = devices.setdefault(ip, Device(ip=ip,
                    csv=os.path.join(LOG, f'{ip}_{s}.csv'),
                    jsonl=os.path.join(LOG, f'{ip}_{s}.jsonl'),
                    gpx_path=os.path.join(LOG, f'{ip}_{s}.gpx')))
            dev = devices[ip]
            dev.data = d; dev.count += 1; dev.seen = __import__('time').time()
            if d.get('wifi_rssi'): dev.rssi.append(d['wifi_rssi'])
            lat, lon = d.get('latitude'), d.get('longitude')
            if lat and lon:
                dev.gpx.append((lat, lon, d.get('altitude'), ts))
                if len(dev.gpx) % 10 == 0: write_gpx(dev)
            with open(dev.jsonl, 'a') as f: f.write(json.dumps(d)+'\n')
            with open(dev.csv, 'a') as f:
                if os.path.getsize(dev.csv) == 0:
                    f.write('time,lat,lon,alt,acc,prov,sats\n')
                f.write(f'{ts},{lat},{lon},{d.get("altitude")},{d.get("accuracy")},{d.get("provider")},{d.get("satellites")}\n')
        print(f'[{ip}] #{dev.count} lat={lat}')
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'ok':True,'n':dev.count,'ip':ip}).encode())
    def do_GET(self):
        with dev_lock:
            resp = json.dumps({'devices': {k: {'data':v.data, 'count':v.count, 'last_seen':v.seen,
                'rssi_len':len(v.rssi), 'gpx_len':len(v.gpx)} for k,v in devices.items()}})
        self.send_response(200); self.end_headers(); self.wfile.write(resp.encode())
    def log_message(self, *a): pass

def card(parent, title):
    f = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill='x', pady=2)
    tk.Label(f, text=title, font=('Segoe UI',9,'bold'), fg=ACCENT, bg=CARD, anchor='w').pack(fill='x', padx=10, pady=(5,2))

class DeviceTab:
    def __init__(self, parent):
        self.parent = parent
        self.lb = {}
        self.sat_tree = None
        self._sat_key = ''
        self._chart_n = 0

        # Info bar
        info = tk.Frame(parent, bg=BG)
        info.pack(fill='x', pady=(0, 4))
        for key, name in [('gps','GPS'),('sats','卫星'),('acc','精度'),('pos','坐标'),('wifi','WiFi')]:
            f = tk.Frame(info, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            f.pack(side='left', fill='x', expand=True, padx=1)
            tk.Label(f, text=name, font=('Segoe UI',8), fg=DIM, bg=CARD, anchor='w').pack(fill='x', padx=6, pady=(2,0))
            self.lb[key] = tk.Label(f, text='—', font=('Consolas',10,'bold'), fg=TEXT, bg=CARD, anchor='w')
            self.lb[key].pack(fill='x', padx=6, pady=(0,2))

        # Sat table
        sat_frame = tk.Frame(parent, bg=BG)
        sat_frame.pack(fill='both', expand=True)
        tk.Label(sat_frame, text='🛰️ 卫星信号 (SNR dB-Hz)', font=('Segoe UI',10,'bold'),
                 fg=ACCENT, bg=BG).pack(anchor='w')
        cols = ('#','星座','SV','SNR','频段','信号条','状态')
        self.tree = ttk.Treeview(sat_frame, columns=cols, show='headings', height=10, selectmode='none')
        widths = [28,50,35,50,68,180,45]
        for c,w in zip(cols,widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor='center' if c != '信号条' else 'w')
        for tag, color in [('ex','#099268'),('gd','#2f9e44'),('fa','#f08c00'),('wk','#e8590c'),('po','#e03131'),
                           ('GPS','#2e7d32'),('GLO','#e65100'),('BDS','#c62828'),('GAL','#1565c0'),('QZSS','#6a1b9a')]:
            self.tree.tag_configure(tag, foreground=color)
        self.tree.pack(fill='both', expand=True)

        # Bottom
        bot = tk.Frame(parent, bg=BG)
        bot.pack(fill='x', pady=(4,0))
        left = tk.Frame(bot, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side='left', fill='both', expand=True, padx=(0,2))
        tk.Label(left, text='📶 WiFi', font=('Segoe UI',9,'bold'), fg=ACCENT, bg=CARD).pack(padx=8, pady=(3,0))
        self.wifi_lb = tk.Label(left, text='—', font=('Consolas',9), fg=TEXT, bg=CARD)
        self.wifi_lb.pack(fill='x', padx=8)
        self.wbar = tk.Canvas(left, height=5, bg=BORDER, highlightthickness=0)
        self.wbar.pack(fill='x', padx=8, pady=(2,4))
        self._wf = self.wbar.create_rectangle(0,0,0,5, width=0, fill=GREEN)
        self.chart = tk.Canvas(left, height=35, bg=CARD, highlightthickness=0)
        self.chart.pack(fill='x', padx=8, pady=(0,4))
        right = tk.Frame(bot, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side='left', fill='x', padx=(2,0))
        tk.Label(right, text='🔗 连接', font=('Segoe UI',9,'bold'), fg=ACCENT, bg=CARD).pack(padx=8, pady=(3,0))
        self.conn_lb = tk.Label(right, text='—', font=('Consolas',9), fg=DIM, bg=CARD)
        self.conn_lb.pack(fill='x', padx=8)
        self.ip_lb = tk.Label(right, text='', font=('Consolas',8), fg=DARK, bg=CARD)
        self.ip_lb.pack(fill='x', padx=8)
        btn_f = tk.Frame(right, bg=CARD); btn_f.pack(fill='x', padx=8, pady=(2,5))
        tk.Button(btn_f, text='⬇GPX', font=('Segoe UI',8,'bold'), bd=0, bg=BG, fg=TEXT,
                  cursor='hand2', padx=4, command=lambda: None).pack(side='left', padx=1)

    def update(self, dev: Device):
        d = dev.data
        if not d:
            self.conn_lb.configure(text='等待数据…', fg=DIM); return
        self.conn_lb.configure(text=f'✅ {dev.count}次', fg=GREEN)
        self.ip_lb.configure(text=dev.ip)
        lat, lon = d.get('latitude'), d.get('longitude')
        prov = d.get('provider',''); acc = d.get('accuracy'); sats = d.get('satellites',0)
        rssi = d.get('wifi_rssi'); ssid = d.get('wifi_ssid','')
        gps_ok = lat and prov == 'gps'
        self.lb['gps'].configure(text='✅定位' if gps_ok else (f'{prov[:4]}…' if lat else '🔍搜索'),
                                 fg=GREEN if gps_ok else (YELLOW if lat else DIM))
        self.lb['sats'].configure(text=f'{sats}', fg=GREEN if sats>5 else YELLOW)
        self.lb['acc'].configure(text=f'{acc:.0f}m' if acc else '—',
                                 fg=GREEN if acc and acc<10 else YELLOW if acc and acc<50 else DIM)
        self.lb['pos'].configure(text=f'{lat:.4f},{lon:.4f}' if lat else '—')
        if rssi:
            self.lb['wifi'].configure(text=f'{rssi}dBm', fg=GREEN if rssi>=-67 else YELLOW if rssi>=-80 else RED)
            pct = max(0,min(100,(rssi+100)*2.5))
            w = max(self.wbar.winfo_width()-2,50)
            self.wbar.coords(self._wf,1,1,1+int(w*pct/100),4)
            self.wbar.itemconfig(self._wf, fill=GREEN if rssi>=-67 else YELLOW if rssi>=-80 else RED)
        self.wifi_lb.configure(text=f'{ssid}  {rssi}dBm' if rssi else ssid or '—')

        raw = d.get('satellites_detail')
        if raw and isinstance(raw,list):
            sk = json.dumps([(x.get('svid'),x.get('cn0'),x.get('const')) for x in raw])
            if sk != self._sat_key:
                self._sat_key = sk
                for r in self.tree.get_children(): self.tree.delete(r)
                for i,s in enumerate(sorted(raw, key=lambda x: x.get('cn0',0), reverse=True), 1):
                    cn0=s.get('cn0',0); const=s.get('const','?'); svid=s.get('svid','?')
                    u=s.get('used',False); freq=s.get('freq',0)
                    ft = ''
                    if freq and freq > 1e6:
                        ft = _band(const, freq/1e6)
                    bar_n = max(0,min(40,int(cn0*0.8)))
                    bar = '█'*bar_n + '░'*(40-bar_n)
                    tag = 'ex' if cn0>=40 else 'gd' if cn0>=30 else 'fa' if cn0>=20 else 'wk' if cn0>=10 else 'po'
                    self.tree.insert('','end', values=(i, CONST_E.get(const,const), svid,
                        f'{cn0:.1f}', ft, bar, '✓' if u else '○'), tags=(tag,const))

        # Chart
        if len(dev.rssi) != self._chart_n:
            self._chart_n = len(dev.rssi)
            self.chart.delete('all')
            h = list(dev.rssi)
            if h:
                w = max(self.chart.winfo_width(),100); mn,mx = min(h),max(h); rg = max(mx-mn,1)
                pts = []
                for i,v in enumerate(h):
                    x = 3+(i/(len(h)-1))*(w-6) if len(h)>1 else w/2
                    y = 27*(1-(v-mn)/rg)+3
                    pts.extend([x,y])
                if pts:
                    self.chart.create_line(*pts, fill=ACCENT, width=1.5, smooth=True)

class App:
    def __init__(self, root):
        self.root = root
        root.title(f'GPS 多设备监测 — {os.path.basename(LOG)}')
        root.geometry('860x700+80+10'); root.configure(bg=BG); root.minsize(700,500)

        bar = tk.Frame(root, bg=BG)
        bar.pack(fill='x', padx=14, pady=(8,4))
        tk.Label(bar, text='🛰️ GPS 多设备监测', font=('Segoe UI',16,'bold'), fg=ACCENT, bg=BG).pack(side='left')
        self.setting_btn = tk.Label(bar, text=' ⚙ ', font=('Segoe UI',12,'bold'), fg=DARK, bg=BG,
                                     cursor='hand2')
        self.setting_btn.pack(side='left', padx=(4,0))
        self.setting_btn.bind('<Button-1>', lambda e: self._pick_log_dir())
        self.srv_dot = tk.Canvas(bar, width=12,height=12, bg=BG, highlightthickness=0)
        self.srv_dot.pack(side='right', padx=(6,0))
        self._dot = self.srv_dot.create_oval(1,1,11,11, fill=DARK, outline='')
        self.srv_lb = tk.Label(bar, text='检测中', font=('Segoe UI',9), fg=DIM, bg=BG)
        self.srv_lb.pack(side='right')
        self.ela_lb = tk.Label(bar, text='', font=('Segoe UI',9), fg=DARK, bg=BG)
        self.ela_lb.pack(side='right', padx=(0,10))

        self.local_ip_lb = tk.Label(bar, text='', font=('Segoe UI',9), fg=DARK, bg=BG)
        self.local_ip_lb.pack(side='right', padx=(0,4))
        self._show_local_ip()

        # Notebook
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(0,8))
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=CARD, foreground=TEXT, padding=[8,3])
        style.map('TNotebook.Tab', background=[('selected', ACCENT)], foreground=[('selected', BG)])

        self.tabs = {}  # ip -> DeviceTab
        self.tab_frame = {}  # ip -> frame
        self.device_count = 0

        # Log path display
        log_bar = tk.Frame(root, bg=BG)
        log_bar.pack(fill='x', padx=12, pady=(0,4))
        self.log_path_lb = tk.Label(log_bar, text=f'📁 {LOG}', font=('Segoe UI',8), fg=DARK, bg=BG,
                                     anchor='w', cursor='hand2')
        self.log_path_lb.pack(side='left')
        self.log_path_lb.bind('<Button-1>', lambda e: os.startfile(LOG))

        root.after(1500, self._srv_check)
        self._ela()

    def _ela(self):
        import time as _t
        e = int(_t.time() - getattr(self, '_ela_start', _t.time()))
        if not hasattr(self, '_ela_start'): self._ela_start = _t.time()
        h,m,s = e//3600, e%3600//60, e%60
        self.ela_lb.configure(text=f'⏱ {h:02d}:{m:02d}:{s:02d}')
        self.root.after(1000, self._ela)

    def _show_local_ip(self):
        ips = []
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ips.append(s.getsockname()[0]); s.close()
        except: pass
        try:
            import subprocess
            out = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=5).stdout
            for line in out.split('\n'):
                if 'IPv4' in line and ':' in line:
                    ip = line.split(':')[-1].strip()
                    if ip and ip not in ips: ips.append(ip)
        except: pass
        if ips:
            self.local_ip_lb.configure(text=f'🖥 {" | ".join(ips)}')

    def _pick_log_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title='选择日志保存目录', initialdir=LOG)
        if d:
            init_log(d)
            self.log_path_lb.configure(text=f'📁 {LOG}')
            self.root.title(f'GPS 多设备监测 — {os.path.basename(LOG)}')
            import subprocess, time
            for dev in devices.values():
                s = time.strftime('%Y-%m-%d_%H-%M-%S')
                dev.csv = os.path.join(LOG, f'{dev.ip}_{s}.csv')
                dev.jsonl = os.path.join(LOG, f'{dev.ip}_{s}.jsonl')
                dev.gpx_path = os.path.join(LOG, f'{dev.ip}_{s}.gpx')

    def _srv_check(self):
        try:
            import urllib.request
            r = json.loads(urllib.request.urlopen('http://localhost:3000', data=b'{}', timeout=1).read())
            nd = len(r.get('devices',{}))
            self.srv_lb.configure(text=f'✓ {nd}设备', fg=GREEN)
            self.srv_dot.itemconfig(self._dot, fill=GREEN)
        except:
            self.srv_lb.configure(text='✗ 离线', fg=RED)
            self.srv_dot.itemconfig(self._dot, fill=RED)

    def _ensure_tab(self, ip):
        if ip not in self.tabs:
            self.device_count += 1
            f = tk.Frame(self.notebook, bg=BG)
            self.notebook.add(f, text=f'📱 {ip}')
            self.notebook.select(f)
            dt = DeviceTab(f)
            self.tabs[ip] = dt
            self.tab_frame[ip] = f

    def _refresh(self):
        with dev_lock:
            snapshot = dict(devices)
        for ip, dev in snapshot.items():
            self._ensure_tab(ip)
            self.tabs[ip].update(dev)
        # Update tab text with count
        for ip, tab in self.tabs.items():
            dev = devices.get(ip)
            if dev:
                idx = list(self.tab_frame.keys()).index(ip) + 1  # +1 for overview tab
                # Can't easily update notebook tab text without removing/re-adding
                pass

    def update(self):
        try: self._refresh()
        except Exception as e: print(f'ERR: {e}')
        finally: self.root.after(500, self.update)

if __name__ == '__main__':
    import subprocess as sp
    # Parse --log-dir
    log_dir = None
    for i, a in enumerate(sys.argv):
        if a == '--log-dir' and i+1 < len(sys.argv):
            log_dir = sys.argv[i+1]
            sys.argv[i] = sys.argv[i+1] = ''
    if log_dir: init_log(log_dir)
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
