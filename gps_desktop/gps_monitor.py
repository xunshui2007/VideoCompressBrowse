import json
import threading
import tkinter as tk
from tkinter import ttk
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

latest_data = {}
data_lock = threading.Lock()

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
        root.geometry("760x600+100+100")
        root.configure(bg='#f0f2f5')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Card.TFrame', background='white', relief='solid', borderwidth=0)
        style.configure('Title.TLabel', background='white', font=('Segoe UI', 12, 'bold'), foreground='#333')
        style.configure('Label.TLabel', background='white', font=('Segoe UI', 10), foreground='#888')
        style.configure('Value.TLabel', background='white', font=('Segoe UI', 10, 'bold'), foreground='#333')
        style.configure('Mono.TLabel', background='white', font=('Consolas', 10, 'bold'), foreground='#333')
        style.configure('Green.TLabel', background='white', font=('Segoe UI', 14, 'bold'), foreground='#4caf50')
        style.configure('Red.TLabel', background='white', font=('Segoe UI', 14, 'bold'), foreground='#f44336')
        style.configure('Orange.TLabel', background='white', font=('Segoe UI', 14, 'bold'), foreground='#ff9800')
        style.configure('Header.TLabel', font=('Segoe UI', 16, 'bold'), foreground='#1a73e8', background='#f0f2f5')

        # Header
        header = ttk.Label(root, text="GPS 实时监测", style='Header.TLabel')
        header.pack(pady=(12, 8))

        main_frame = ttk.Frame(root, style='Card.TFrame')
        main_frame.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        # Canvas + Scrollbar for scrollable content
        canvas = tk.Canvas(main_frame, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient='vertical', command=canvas.yview)
        scroll_frame = ttk.Frame(canvas, style='Card.TFrame')

        scroll_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # GPS Status
        f1 = ttk.LabelFrame(scroll_frame, text='GPS 状态', padding=10)
        f1.pack(fill='x', padx=10, pady=(10, 4))
        self.gps_status = ttk.Label(f1, text='等待数据…', style='Orange.TLabel')
        self.gps_status.pack(anchor='w')
        self.gps_provider = ttk.Label(f1, text='', style='Label.TLabel')
        self.gps_provider.pack(anchor='w')

        # Coordinates
        f2 = ttk.LabelFrame(scroll_frame, text='坐标', padding=10)
        f2.pack(fill='x', padx=10, pady=4)
        grid2 = ttk.Frame(f2)
        grid2.pack(fill='x')
        self.labels2 = {}
        fields = [('纬度', 'latitude', '°'), ('经度', 'longitude', '°'),
                  ('海拔', 'altitude', ' m'), ('精度', 'accuracy', ' m'),
                  ('速度', 'speed', ' m/s'), ('方向', 'bearing', '°')]
        for i, (label, key, unit) in enumerate(fields):
            r, c = divmod(i, 2)
            frame = ttk.Frame(grid2)
            frame.grid(row=r, column=c, sticky='ew', padx=(0, 20), pady=2)
            grid2.columnconfigure(c, weight=1)
            ttk.Label(frame, text=label + '：', style='Label.TLabel').pack(side='left')
            self.labels2[key] = ttk.Label(frame, text='-', style='Mono.TLabel')
            self.labels2[key].pack(side='left')

        # WiFi
        f3 = ttk.LabelFrame(scroll_frame, text='WiFi 信息', padding=10)
        f3.pack(fill='x', padx=10, pady=4)
        self.wifi_ssid = ttk.Label(f3, text='-', style='Mono.TLabel')
        self.wifi_ssid.pack(anchor='w')
        self.wifi_rssi = ttk.Label(f3, text='-', style='Mono.TLabel')
        self.wifi_rssi.pack(anchor='w')
        self.wifi_freq = ttk.Label(f3, text='-', style='Mono.TLabel')
        self.wifi_freq.pack(anchor='w')

        # Satellite SNR Table
        f4 = ttk.LabelFrame(scroll_frame, text='卫星 SNR', padding=10)
        f4.pack(fill='x', padx=10, pady=4)
        self.sat_frame = ttk.Frame(f4)
        self.sat_frame.pack(fill='x')
        self.sat_header = ttk.Label(self.sat_frame, text='等待数据…', style='Label.TLabel')
        self.sat_header.pack(anchor='w')

        # Connection Info
        f5 = ttk.LabelFrame(scroll_frame, text='连接信息', padding=10)
        f5.pack(fill='x', padx=10, pady=(4, 10))
        self.phone_ip = ttk.Label(f5, text='-', style='Mono.TLabel')
        self.phone_ip.pack(anchor='w')
        self.last_update = ttk.Label(f5, text='-', style='Label.TLabel')
        self.last_update.pack(anchor='w')
        self.server_info = ttk.Label(f5, text='监听 0.0.0.0:3000  ← 手机填此 IP', style='Label.TLabel')
        self.server_info.pack(anchor='w', pady=(4, 0))

    def update(self):
        with data_lock:
            d = dict(latest_data)
        if not d:
            self.root.after(500, self.update)
            return

        loc = d.get('latitude') is not None
        gps_ok = loc and (d.get('accuracy') is None or d['accuracy'] < 100)

        if gps_ok:
            self.gps_status.configure(text='已定位 ✓', style='Green.TLabel')
        elif loc:
            self.gps_status.configure(text='定位中…', style='Orange.TLabel')
        else:
            self.gps_status.configure(text='无信号', style='Red.TLabel')
        self.gps_provider.configure(text=f'来源: {d.get("provider", "?")}')

        for key, label in self.labels2.items():
            val = d.get(key)
            if val is not None:
                label.configure(text=f'{val:.6f}' if isinstance(val, float) and key in ('latitude', 'longitude')
                                else f'{val:.1f}' if isinstance(val, float)
                                else str(val))
            else:
                label.configure(text='-')

        self.wifi_ssid.configure(text=f'SSID: {d.get("wifi_ssid", "-")}')
        rssi = d.get('wifi_rssi')
        if rssi is not None:
            pct = max(0, min(100, (rssi + 100) * 2.5))
            color = '#4caf50' if rssi >= -67 else '#ff9800' if rssi >= -80 else '#f44336'
            self.wifi_rssi.configure(text=f'信号: {rssi} dBm ({pct:.0f}%)', foreground=color)
        else:
            self.wifi_rssi.configure(text='信号: -', foreground='#333')
        self.wifi_freq.configure(text=f'频率: {d.get("wifi_frequency", "-")} MHz')

        # Satellite table
        sats = d.get('satellites_detail', [])
        if sats and len(sats) > 0:
            used = sum(1 for s in sats if s.get('used'))
            for w in self.sat_frame.winfo_children():
                w.destroy()
            ttk.Label(self.sat_frame, text=f'{used}/{len(sats)} 锁定', style='Label.TLabel').pack(anchor='w', pady=(0, 4))
            # Table header
            hdr = ttk.Frame(self.sat_frame)
            hdr.pack(fill='x')
            for text, w in [('PRN', 50), ('星座', 50), ('SNR', 120), ('状态', 60)]:
                ttk.Label(hdr, text=text, style='Label.TLabel', width=w//7).pack(side='left')
            for s in sats:
                row = ttk.Frame(self.sat_frame)
                row.pack(fill='x', pady=1)
                const = s.get('const', '?')
                cn0 = s.get('cn0', 0)
                used_flag = s.get('used', False)
                snr_color = '#4caf50' if cn0 >= 40 else '#ff9800' if cn0 >= 25 else '#f44336'
                ttk.Label(row, text=str(s.get('svid', '?')), style='Mono.TLabel', width=7).pack(side='left')
                ttk.Label(row, text=const, style='Mono.TLabel', width=7).pack(side='left')
                ttk.Label(row, text=f'{cn0:.1f} dB-Hz', foreground=snr_color,
                          font=('Consolas', 9, 'bold'), background='white').pack(side='left')
                ttk.Label(row, text='✓ 使用' if used_flag else '○ 搜索',
                          foreground='#4caf50' if used_flag else '#999',
                          font=('Segoe UI', 9), background='white').pack(side='left')
        else:
            for w in self.sat_frame.winfo_children():
                w.destroy()
            ttk.Label(self.sat_frame, text='无卫星数据', style='Label.TLabel').pack(anchor='w')

        self.phone_ip.configure(text=f'手机 IP: {d.get("phone_ip", "-")}')
        self.last_update.configure(text=f'最后更新: {d.get("received_at", "-")}')

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
