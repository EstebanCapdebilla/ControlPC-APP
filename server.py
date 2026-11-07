#!/usr/bin/env python3
"""
Control Remoto PC - servidor para Windows.

Convierte tu celular Android en mouse, teclado y control multimedia del PC.
Solo usa la librería estándar de Python (no hay que instalar nada con pip).

Uso:
    python server.py               -> inicia y abre la página de vinculación (QR)
    python server.py --no-browser  -> inicia sin abrir el navegador
    python server.py --new-token   -> genera un código de acceso nuevo (desvincula celulares)
    python server.py --port 9000   -> usa otro puerto
    pythonw server.py --tray       -> sin ventana, con ícono junto al reloj (lo usa el instalador)

La configuración y el registro se guardan en %APPDATA%\\ControlPC.
"""
import asyncio
import base64
import ctypes
import hashlib
import hmac
import html
import ipaddress
import json
import mimetypes
import os
import secrets
import shutil
import socket
import struct
import sys
import threading
import time
import urllib.parse
import webbrowser
from ctypes import wintypes
from pathlib import Path

if sys.platform != "win32":
    sys.exit("Este servidor está hecho para Windows.")

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
# Datos de este usuario de Windows (el programa puede estar en "Archivos de programa", que es de solo lectura).
DATA = Path(os.environ.get("APPDATA") or BASE) / "ControlPC"
CONFIG_FILE = DATA / "config.json"
LOG_FILE = DATA / "server.log"
IDLE_TIMEOUT = 10      # s sin mensajes del celular (manda un ping cada 2 s) = conexión muerta
PIN_MAX_FAILS = 30     # fallos de PIN en total (de cualquier IP) antes de cambiar el PIN
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DISCOVERY_PORT = 8766  # UDP, la app Android busca PCs aquí


# ----------------------------------------------------------------------------
# Configuración (token de acceso persistente)
# ----------------------------------------------------------------------------
def load_config(new_token=False):
    DATA.mkdir(parents=True, exist_ok=True)
    old = BASE / "config.json"  # versiones anteriores lo guardaban junto a server.py
    if not CONFIG_FILE.exists() and old.exists():
        try:
            shutil.copyfile(old, CONFIG_FILE)
        except OSError:
            pass
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            cfg = {}
    if new_token or not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(9)
    cfg.setdefault("id", secrets.token_hex(6))  # identifica a este PC en la app Android
    cfg.setdefault("port", 8765)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), "utf-8")
    return cfg


# ----------------------------------------------------------------------------
# Entrada de Windows (SendInput vía ctypes)
# ----------------------------------------------------------------------------
user32 = ctypes.WinDLL("user32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
user32.VkKeyScanW.restype = ctypes.c_short
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

BUTTONS = {  # botón: (down, up)
    "l": (0x0002, 0x0004),
    "r": (0x0008, 0x0010),
    "m": (0x0020, 0x0040),
}

VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "pause": 0x13, "capslock": 0x14, "esc": 0x1B, "space": 0x20, "pageup": 0x21,
    "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27,
    "down": 0x28, "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "win": 0x5B,
    "menu": 0x5D, "volmute": 0xAD, "voldown": 0xAE, "volup": 0xAF, "next": 0xB0,
    "prev": 0xB1, "stop": 0xB2, "playpause": 0xB3,
}
for _i in range(1, 13):
    VK[f"f{_i}"] = 0x6F + _i
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5D,
            0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


def _send(inputs):
    n = len(inputs)
    if n:
        arr = (INPUT * n)(*inputs)
        user32.SendInput(n, arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    return i


def _key(vk, up=False):
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, user32.MapVirtualKeyW(vk, 0) & 0xFFFF, flags, 0, 0)
    return i


def _unicode(unit, up=False):
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(0, unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    return i


def vk_of(name):
    """Nombre de tecla o carácter -> código virtual de Windows."""
    if not isinstance(name, str) or not name:
        return None
    low = name.lower()
    if low in VK:
        return VK[low]
    if len(name) == 1:
        r = user32.VkKeyScanW(name)
        if r != -1:
            return r & 0xFF
    return None


class Input:
    @staticmethod
    def move(dx, dy):
        _send([_mouse(MOUSEEVENTF_MOVE, dx, dy)])

    @staticmethod
    def scroll(vertical, horizontal):
        ev = []
        if vertical:
            ev.append(_mouse(MOUSEEVENTF_WHEEL, data=vertical))
        if horizontal:
            ev.append(_mouse(MOUSEEVENTF_HWHEEL, data=horizontal))
        _send(ev)

    @staticmethod
    def button(btn, down=None):
        """down=None -> clic completo, True -> presionar, False -> soltar."""
        if btn not in BUTTONS:
            return
        d, u = BUTTONS[btn]
        if down is None:
            _send([_mouse(d), _mouse(u)])
        else:
            _send([_mouse(d if down else u)])

    @staticmethod
    def combo(keys):
        vks = [v for v in (vk_of(k) for k in keys) if v is not None]
        if not vks:
            return
        _send([_key(v) for v in vks] + [_key(v, True) for v in reversed(vks)])

    @staticmethod
    def key(name, down):
        v = vk_of(name)
        if v is not None:
            _send([_key(v, not down)])

    @staticmethod
    def repeat(name, times):
        v = vk_of(name)
        if v is None:
            return
        ev = []
        for _ in range(max(0, min(times, 500))):
            ev += [_key(v), _key(v, True)]
        _send(ev)

    @staticmethod
    def text(s):
        ev = []
        for ch in s.replace("\r\n", "\n"):
            if ch == "\n":
                ev += [_key(VK["enter"]), _key(VK["enter"], True)]
                continue
            if ch == "\t":
                ev += [_key(VK["tab"]), _key(VK["tab"], True)]
                continue
            data = ch.encode("utf-16-le")
            for j in range(0, len(data), 2):
                unit = data[j] | (data[j + 1] << 8)
                ev += [_unicode(unit), _unicode(unit, True)]
        _send(ev)


# ---------------------------------------------------------------- portapapeles
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
CF_UNICODETEXT = 13
user32.OpenClipboard.argtypes = (wintypes.HWND,)
user32.GetClipboardData.argtypes = (wintypes.UINT,)
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = (wintypes.UINT, wintypes.HANDLE)
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = (wintypes.HGLOBAL,)
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)


def _open_clipboard():
    for _ in range(10):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.01)
    return False


def clipboard_get():
    if not _open_clipboard():
        return ""
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set(text):
    data = text.encode("utf-16-le") + b"\0\0"
    if not _open_clipboard():
        return
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)  # Windows pasa a ser dueño de la memoria
    finally:
        user32.CloseClipboard()


def system_action(name):
    if name == "lock":
        user32.LockWorkStation()
    elif name == "monitor":
        # HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2 = apagar
        user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)
    elif name == "sleep":
        ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)


class AltTab:
    """Mantiene Alt presionado mientras se pulsa 'Alt+Tab' varias veces seguidas."""

    def __init__(self):
        self.held = False
        self.timer = None

    def step(self, loop, back=False):
        ev = []
        if not self.held:
            ev.append(_key(VK["alt"]))
            self.held = True
        if back:
            ev += [_key(VK["shift"]), _key(VK["tab"]), _key(VK["tab"], True), _key(VK["shift"], True)]
        else:
            ev += [_key(VK["tab"]), _key(VK["tab"], True)]
        _send(ev)
        if self.timer:
            self.timer.cancel()
        self.timer = loop.call_later(1.1, self.release)

    def release(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.held:
            _send([_key(VK["alt"], True)])
            self.held = False


ALT_TAB = AltTab()


class Smoother:
    """
    Suaviza el movimiento del puntero.

    Por Wi-Fi los paquetes llegan en ráfagas irregulares (el celular agrupa envíos
    para ahorrar batería). Si cada paquete se aplicara de golpe, el cursor daría
    saltos aunque el celular mande 60-120 movimientos por segundo.
    Aquí cada movimiento recibido se reparte en pasos pequeños a ~500 Hz durante el
    tiempo típico entre paquetes, así el cursor avanza a velocidad continua.
    El retraso añadido es como máximo `max_spread` (unos pocos milisegundos).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.px = self.py = 0.0      # movimiento pendiente (con decimales)
        self.remaining = 0.0          # segundos en los que repartir lo pendiente
        self.interval = 0.012         # tiempo medio entre paquetes (se adapta solo)
        self.last_arrival = 0.0
        self.max_spread = 0.016       # 0 = sin suavizado
        threading.Thread(target=self._run, name="suavizado", daemon=True).start()

    def stop(self):
        """Descarta el movimiento pendiente (el celular se desconectó)."""
        with self.lock:
            self.px = self.py = 0.0
            self.remaining = 0.0

    def set_level(self, ms):
        self.max_spread = max(0.0, min(float(ms), 50.0)) / 1000

    def add(self, dx, dy):
        if self.max_spread <= 0:
            Input.move(dx, dy)
            return
        now = time.perf_counter()
        with self.lock:
            gap = now - self.last_arrival
            if gap >= 0.0025:  # paquetes pegados (<2.5 ms) cuentan como una sola ráfaga
                self.last_arrival = now
                if gap < 0.08:  # dentro del mismo gesto: aprender el ritmo de llegada
                    self.interval += (gap - self.interval) * 0.2
            self.px += dx
            self.py += dy
            self.remaining = min(max(self.interval * 1.25, 0.004), self.max_spread)
        self.wake.set()

    def _run(self):
        while True:
            self.wake.wait()
            last = time.perf_counter()
            while True:
                time.sleep(0.002)  # Python 3.11+ en Windows usa temporizador de alta resolución
                now = time.perf_counter()
                dt, last = now - last, now
                with self.lock:
                    f = 1.0 if self.remaining <= dt else dt / self.remaining
                    self.remaining = max(0.0, self.remaining - dt)
                    ix, iy = int(self.px * f), int(self.py * f)
                    if f >= 1.0:
                        ix, iy = int(self.px), int(self.py)
                    self.px -= ix
                    self.py -= iy
                    done = self.remaining == 0 and abs(self.px) < 1 and abs(self.py) < 1
                    if done:
                        self.wake.clear()
                if ix or iy:
                    Input.move(ix, iy)
                if done:
                    break


SMOOTH = Smoother()


# ----------------------------------------------------------------------------
# WebSocket mínimo (RFC 6455) sobre asyncio
# ----------------------------------------------------------------------------
def _unmask(data, mask):
    n = len(data)
    m = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(m, "little")).to_bytes(n, "little")


class WebSocket:
    def __init__(self, reader, writer):
        self.r, self.w = reader, writer
        self.closed = False

    def send_frame(self, opcode, payload=b""):
        if self.closed:
            return
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
        self.w.write(head + payload)

    def send(self, obj):
        self.send_frame(1, json.dumps(obj, separators=(",", ":")).encode())

    async def recv(self):
        buf, kind = bytearray(), None
        while True:
            h = await self.r.readexactly(2)
            fin, op = h[0] & 0x80, h[0] & 0x0F
            masked, n = h[1] & 0x80, h[1] & 0x7F
            if n == 126:
                n = struct.unpack("!H", await self.r.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", await self.r.readexactly(8))[0]
            if n > 4 << 20:
                raise ConnectionError("mensaje demasiado grande")
            mask = await self.r.readexactly(4) if masked else b""
            data = await self.r.readexactly(n) if n else b""
            if masked and n:
                data = _unmask(data, mask)
            if op == 8:  # close
                self.close(1000)
                return None
            if op == 9:  # ping
                self.send_frame(10, data)
                continue
            if op == 10:  # pong
                continue
            if op in (1, 2):
                kind, buf = op, bytearray(data)
            elif op == 0:
                buf += data
            if fin:
                return buf.decode("utf-8", "replace") if kind == 1 else bytes(buf)

    def close(self, code=1000, reason=""):
        if not self.closed:
            self.send_frame(8, struct.pack("!H", code) + reason.encode()[:100])
            self.closed = True
        try:
            self.w.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Servidor HTTP + WebSocket
# ----------------------------------------------------------------------------
class Server:
    def __init__(self, token, port, server_id):
        self.token = token
        self.port = port
        self.id = server_id
        self.name = socket.gethostname()
        self.pin = self.new_pin()  # PIN de vinculación (cambia en cada inicio)
        self.pin_fails = {}  # ip -> (intentos fallidos, bloqueado_hasta)
        self.pin_fails_total = 0
        self.on_pin_change = None  # el ícono de la bandeja actualiza su texto
        self.on_clients_change = None
        self.clients = 0
        self.phones = set()       # celulares conectados
        self.exts = []            # extensiones de YouTube Music conectadas
        self.ytm_state = None     # última canción/estado informado por la extensión
        self.ytm_pending = {}     # id interno -> (celular, id del celular)
        self.ytm_seq = 0

    @staticmethod
    def new_pin():
        return f"{secrets.randbelow(10 ** 6):06d}"

    def info(self):
        return {"app": "rcpc", "name": self.name, "id": self.id, "port": self.port}

    def proof(self, nonce, peer):
        """
        Demuestra que este PC conoce el código de acceso sin enviarlo.
        Incluye la IP de quien pregunta: si otro equipo reenvía la pregunta para
        hacerse pasar por este PC, la prueba no le sirve al celular.
        """
        msg = f"rcpc1|{nonce}|{self._norm_ip(peer)}".encode()
        return hmac.new(self.token.encode(), msg, hashlib.sha256).hexdigest()

    @staticmethod
    def _norm_ip(ip):
        try:
            a = ipaddress.ip_address(ip)
            if a.version == 6 and a.ipv4_mapped:
                a = a.ipv4_mapped
            return str(a)
        except ValueError:
            return ip

    @staticmethod
    def _host_ok(host):
        """
        Solo se aceptan pedidos dirigidos a una IP o a localhost. Así una página web
        con un dominio propio que apunte a este PC (DNS rebinding) no puede leer nada.
        """
        h = host.strip().lower()
        if h.startswith("["):
            h = h[1:h.find("]")] if "]" in h else ""
        elif h.count(":") == 1:
            h = h.split(":", 1)[0]
        if h == "localhost":
            return True
        try:
            ipaddress.ip_address(h)
            return True
        except ValueError:
            return False

    @staticmethod
    def _allowed(ip):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if a.version == 6 and a.ipv4_mapped:
            a = a.ipv4_mapped
        return a.is_private or a.is_loopback or a.is_link_local

    async def handle(self, reader, writer):
        peer = (writer.get_extra_info("peername") or ("?",))[0]
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:  # menor latencia: no esperar a juntar paquetes (Nagle off)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        if not self._allowed(peer):  # solo red local
            writer.close()
            return
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            url = urllib.parse.urlsplit(target)
            if not self._host_ok(headers.get("host", "")):
                return self._respond(writer, 403, b"Host no permitido")
            if url.path in ("/ws", "/ext") and headers.get("upgrade", "").lower() == "websocket":
                await self.websocket(reader, writer, headers, url, peer)
            else:
                await self.http(writer, method, url, peer)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError,
                asyncio.LimitOverrunError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- HTTP
    async def http(self, writer, method, url, peer):
        path = url.path
        if method not in ("GET", "HEAD"):
            return self._respond(writer, 405, b"Metodo no permitido")
        if path == "/api/info":
            return self._json(writer, 200, self.info())
        if path == "/api/prove":
            nonce = urllib.parse.parse_qs(url.query).get("n", [""])[0][:64]
            if not nonce:
                return self._respond(writer, 400, b"Falta n")
            return self._json(writer, 200, {**self.info(), "proof": self.proof(nonce, peer)})
        if path == "/api/pair":
            return self._json(writer, *self.try_pin(peer, urllib.parse.parse_qs(url.query).get("pin", [""])[0]))
        if path == "/pair":
            if not ipaddress.ip_address(peer).is_loopback:
                return self._respond(writer, 403, b"Solo desde el propio PC")
            return self._respond(writer, 200, self.pair_page().encode(), "text/html; charset=utf-8")
        if path in ("", "/"):
            path = "/index.html"
        file = (WEB / path.lstrip("/")).resolve()
        if WEB.resolve() not in file.parents or not file.is_file():
            return self._respond(writer, 404, b"No encontrado")
        ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        if file.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        body = file.read_bytes() if method == "GET" else b""
        self._respond(writer, 200, body, ctype)
        await writer.drain()

    def try_pin(self, peer, pin):
        """Cambia el PIN de 6 dígitos por el código de acceso. Bloquea tras 5 fallos."""
        now = time.monotonic()
        if len(self.pin_fails) > 500:  # limpiar bloqueos vencidos
            self.pin_fails = {k: v for k, v in self.pin_fails.items() if v[0] or v[1] > now}
        fails, until = self.pin_fails.get(peer, (0, 0))
        if now < until:
            return 429, {"error": f"Demasiados intentos. Espera {int(until - now) + 1} s."}
        if pin and secrets.compare_digest(pin.strip().encode(), self.pin.encode()):
            self.pin_fails.pop(peer, None)
            log(f"Celular vinculado con PIN: {peer}")
            return 200, {**self.info(), "token": self.token}
        fails += 1
        self.pin_fails[peer] = (0, now + 60) if fails >= 5 else (fails, 0)
        self.pin_fails_total += 1
        if self.pin_fails_total >= PIN_MAX_FAILS:  # alguien prueba PINs desde muchas IPs
            self.pin, self.pin_fails_total = self.new_pin(), 0
            log("Demasiados PIN incorrectos: se generó un PIN nuevo.")
            if self.on_pin_change:
                self.on_pin_change()
        return 403, {"error": "PIN incorrecto"}

    def _json(self, writer, status, obj):
        self._respond(writer, status, json.dumps(obj).encode(), "application/json")

    @staticmethod
    def _respond(writer, status, body, ctype="text/plain; charset=utf-8"):
        reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
                  429: "Too Many Requests"}[status]
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
            f"Cache-Control: no-cache\r\nConnection: close\r\n\r\n".encode() + body
        )

    def pair_page(self):
        ips = local_ips()
        urls = [f"http://{ip}:{self.port}/?t={self.token}" for ip in ips]
        main = urls[0] if urls else ""
        others = "".join(f"<li><code>{html.escape(u)}</code></li>" for u in urls[1:])
        return PAIR_HTML.replace("{{URL}}", html.escape(main)).replace("{{OTHERS}}", others) \
            .replace("{{URLJS}}", json.dumps(main)).replace("{{PIN}}", f"{self.pin[:3]} {self.pin[3:]}") \
            .replace("{{NAME}}", html.escape(self.name))

    # ----------------------------------------------------------- WebSocket
    async def websocket(self, reader, writer, headers, url, peer):
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
        )
        ws = WebSocket(reader, writer)
        if url.path == "/ext":
            # Extensión de YouTube Music: solo desde este PC y solo desde una extensión
            # (las páginas web no pueden poner un Origin chrome-extension://).
            origin = headers.get("origin", "")
            if not ipaddress.ip_address(peer).is_loopback or not origin.startswith(("chrome-extension://", "extension://")):
                ws.close(4003, "solo extension local")
                return
            return await self.extension(ws)
        origin = headers.get("origin", "")
        if origin and urllib.parse.urlsplit(origin).netloc.lower() != headers.get("host", "").lower():
            log(f"Conexión rechazada (origen {origin!r}) desde {peer}")
            ws.close(4003, "origen")
            return
        token = urllib.parse.parse_qs(url.query).get("t", [""])[0]
        if not secrets.compare_digest(token.encode(), self.token.encode()):
            log(f"Conexión rechazada (código incorrecto) desde {peer}")
            ws.close(4001, "token")
            return

        self.clients += 1
        self.phones.add(ws)
        log(f"Celular conectado: {peer}  (conectados: {self.clients})")
        if self.on_clients_change:
            self.on_clients_change()
        ws.send(["hello", self.name, self.id])
        ws.send(["ytm", "ext", bool(self.exts)])
        if self.ytm_state is not None:
            ws.send(["ytm", "state", self.ytm_state])
        held = set()  # botones presionados por este cliente
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:  # si el Wi-Fi se corta, Windows tardaría minutos en notarlo
                    msg = await asyncio.wait_for(ws.recv(), IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    log(f"Sin respuesta del celular {peer}: se cierra la conexión")
                    break
                if msg is None:
                    break
                if isinstance(msg, str):
                    try:
                        a = json.loads(msg)
                        if a[0] == "ytm":
                            self.ytm_from_phone(ws, a[1])
                        else:
                            self.dispatch(ws, a, held, loop)
                    except (ValueError, TypeError, IndexError, KeyError, AttributeError) as e:
                        log(f"Mensaje inválido: {e}")
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            SMOOTH.stop()
            for b in held:  # nunca dejar un botón "pegado"
                Input.button(b, False)
            ALT_TAB.release()
            self.clients -= 1
            self.phones.discard(ws)
            log(f"Celular desconectado: {peer}  (conectados: {self.clients})")
            if self.on_clients_change:
                self.on_clients_change()
            ws.close()

    # ------------------------------------------------------ YouTube Music
    def _to_phones(self, msg):
        for p in list(self.phones):
            try:
                p.send(msg)
            except Exception:
                pass

    def ytm_from_phone(self, phone, req):
        """El celular pide algo a YouTube Music: se reenvía a la extensión."""
        if not self.exts:
            phone.send(["ytm", "res", {"id": req.get("id"), "error": "noext"}])
            return
        self.ytm_seq += 1
        key = str(self.ytm_seq)
        self.ytm_pending[key] = (phone, req.get("id"))
        if len(self.ytm_pending) > 200:  # no acumular respuestas perdidas
            self.ytm_pending.pop(next(iter(self.ytm_pending)))
        self.exts[-1].send(["cmd", {"id": key, "cmd": str(req.get("cmd", "")), "args": req.get("args") or {}}])

    async def extension(self, ws):
        self.exts.append(ws)
        log("Extensión de YouTube Music conectada")
        self._to_phones(["ytm", "ext", True])
        try:
            while True:
                msg = await ws.recv()
                if msg is None:
                    break
                try:
                    a = json.loads(msg)
                except ValueError:
                    continue
                if a[0] == "state":
                    self.ytm_state = a[1]
                    self._to_phones(["ytm", "state", a[1]])
                elif a[0] == "res" and isinstance(a[1], dict):
                    phone, pid = self.ytm_pending.pop(str(a[1].get("id")), (None, None))
                    if phone is not None and phone in self.phones:
                        phone.send(["ytm", "res", {**a[1], "id": pid}])
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            if ws in self.exts:
                self.exts.remove(ws)
            log("Extensión de YouTube Music desconectada")
            if not self.exts:
                self.ytm_state = None
                self._to_phones(["ytm", "ext", False])
            ws.close()

    @staticmethod
    def dispatch(ws, a, held, loop):
        t = a[0]
        if t == "m":
            SMOOTH.add(int(a[1]), int(a[2]))
        elif t == "s":
            Input.scroll(int(a[1]), int(a[2]) if len(a) > 2 else 0)
        elif t == "c":
            Input.button(a[1])
        elif t == "d":
            held.add(a[1])
            Input.button(a[1], True)
        elif t == "u":
            held.discard(a[1])
            Input.button(a[1], False)
        elif t == "k":
            Input.combo(a[1])
        elif t == "kd":
            Input.key(a[1], True)
        elif t == "ku":
            Input.key(a[1], False)
        elif t == "r":
            Input.repeat(a[1], int(a[2]))
        elif t == "t":
            Input.text(str(a[1])[:5000])
        elif t == "at":
            ALT_TAB.step(loop, back=bool(a[1]) if len(a) > 1 else False)
        elif t == "atx":
            ALT_TAB.release()
        elif t == "p":
            ws.send(["p", a[1]])
        elif t == "sys":
            system_action(a[1])
        elif t == "cfg":
            if "smooth" in a[1]:
                SMOOTH.set_level(a[1]["smooth"])
        elif t == "cs":  # en otro hilo: el portapapeles puede estar ocupado por otro programa
            loop.run_in_executor(None, clipboard_set, str(a[1])[:200000])
        elif t == "cg":
            fut = loop.run_in_executor(None, clipboard_get)
            fut.add_done_callback(lambda f: f.exception() or ws.send(["clip", (f.result() or "")[:200000]]))


class Discovery(asyncio.DatagramProtocol):
    """Responde a la app Android cuando busca PCs en la red (broadcast UDP)."""

    def __init__(self, srv):
        self.srv = srv
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        parts = data.strip().split()
        if not parts or parts[0] != b"RCPC_DISCOVER" or not Server._allowed(addr[0]):
            return
        info = self.srv.info()
        if len(parts) > 1:  # la app manda un número al azar: se responde con la prueba
            info["proof"] = self.srv.proof(parts[1][:64].decode("ascii", "replace"), addr[0])
        self.transport.sendto(json.dumps(info).encode(), addr)


def local_ips():
    ips = []
    try:  # IP de la interfaz con salida a la red (normalmente el Wi-Fi)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127.") and ipaddress.ip_address(ip).is_private:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]


_log_file = None


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)  # con pythonw no hay consola y print no hace nada
    if _log_file:
        try:
            _log_file.write(time.strftime("%Y-%m-%d ") + line + "\n")
            _log_file.flush()
        except OSError:
            pass


def open_log():
    global _log_file
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512 * 1024:  # no crecer sin límite
            LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
        _log_file = open(LOG_FILE, "a", encoding="utf-8")
    except OSError:
        _log_file = None


PAIR_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vincular celular</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e8eaf0;
font:16px system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.card{background:#181b22;border:1px solid #262a34;border-radius:20px;padding:32px;max-width:440px;text-align:center}
h1{margin:0 0 6px;font-size:22px} p{color:#9aa1b2;line-height:1.5}
#qr{background:#fff;padding:16px;border-radius:14px;display:inline-block;margin:18px 0}
code{background:#0f1115;padding:6px 10px;border-radius:8px;display:inline-block;word-break:break-all;color:#7cc4ff}
ul{list-style:none;padding:0;font-size:13px}
.pin{font:700 44px/1 ui-monospace,Consolas,monospace;letter-spacing:.12em;color:#4f9dff;margin:14px 0}
</style></head><body><div class="card">
<h1>Vincular tu celular</h1>
<p>Conecta el celular a la <b>misma red Wi-Fi</b> que este PC.</p>
<h2 style="margin:22px 0 4px;font-size:16px">App Android</h2>
<p style="margin:0">Abre la app, elige <b>{{NAME}}</b> e ingresa este PIN:</p>
<div class="pin">{{PIN}}</div>
<h2 style="margin:22px 0 4px;font-size:16px">O desde el navegador</h2>
<p style="margin:0">Escanea el código con la cámara y ábrelo en Chrome:</p>
<div id="qr"></div><br><code>{{URL}}</code>
<p style="font-size:13px">¿No funciona? Prueba otra dirección:</p><ul>{{OTHERS}}</ul>
</div>
<script src="/vendor/qrcode.min.js"></script><!-- qrcodejs 1.0.0 (MIT), incluido: funciona sin internet -->
<script>
try{new QRCode(document.getElementById('qr'),{text:{{URLJS}},width:240,height:240,correctLevel:QRCode.CorrectLevel.M});}
catch(e){document.getElementById('qr').outerHTML='<p>(No se pudo dibujar el QR: escribe la dirección en el celular)</p>';}
</script></body></html>"""


async def main(args, tray_mode):
    cfg = load_config(new_token="--new-token" in args)
    port = int(args[args.index("--port") + 1]) if "--port" in args else int(cfg["port"])
    srv = Server(cfg["token"], port, cfg["id"])
    pair_url = f"http://localhost:{port}/pair"
    try:
        # Sin reuse_address: en Windows permitiría que dos servidores compartan el puerto en silencio.
        server = await asyncio.start_server(srv.handle, "0.0.0.0", port, reuse_address=False)
    except OSError as e:
        if tray_mode:  # probablemente ya está abierto: mostrar su página
            import tray
            if "--no-browser" not in args:
                webbrowser.open(pair_url)
            else:
                tray.message_box(f"No se pudo abrir el puerto {port}.\n¿Control PC ya está abierto?", warn=True)
            log(f"No se pudo abrir el puerto {port}: {e}")
            return
        sys.exit(f"No se pudo abrir el puerto {port}: {e}\n¿Ya hay otro servidor abierto?")
    try:  # descubrimiento automático para la app Android (puerto UDP fijo)
        await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: Discovery(srv), local_addr=("0.0.0.0", DISCOVERY_PORT))
    except OSError as e:
        log(f"Aviso: descubrimiento automático desactivado ({e})")

    ips = local_ips()
    log(f"Servidor activo en el puerto {port} ({', '.join(ips)}). Datos en {DATA}")
    print("=" * 62)
    print("  CONTROL REMOTO PC  -  servidor activo")
    print("=" * 62)
    print("  Abre esto en el celular (misma red Wi-Fi):")
    for ip in ips:
        print(f"    http://{ip}:{port}/?t={cfg['token']}")
    print(f"\n  PIN para la app Android:  {srv.pin[:3]} {srv.pin[3:]}")
    print(f"  Código QR:   {pair_url}")
    print("  Cerrar:      Ctrl + C")
    print("=" * 62, flush=True)
    if "--no-browser" not in args:
        webbrowser.open(pair_url)

    async with server:
        if not tray_mode:
            await server.serve_forever()
            return
        import tray
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        last_open = [0.0]

        def show_pair():  # un doble clic no debe abrir dos pestañas
            if time.monotonic() - last_open[0] > 1.5:
                last_open[0] = time.monotonic()
                webbrowser.open(pair_url)

        def tooltip():
            phones = f" · {srv.clients} celular(es)" if srv.clients else ""
            return f"Control PC · PIN {srv.pin[:3]} {srv.pin[3:]}{phones}"

        icon = BASE / "icon.ico"
        t = tray.Tray(tooltip, show_pair, lambda: loop.call_soon_threadsafe(stop.set),
                      icon_path=str(icon), script=str(Path(__file__).resolve()),
                      log_path=str(LOG_FILE), data_dir=str(DATA))
        t.start()
        srv.on_pin_change = t.refresh
        srv.on_clients_change = t.refresh
        if "--no-browser" in args:  # inicio automático con Windows: solo un aviso discreto
            t.notify("Control PC está activo", f"PIN para vincular: {srv.pin[:3]} {srv.pin[3:]}")
        await stop.wait()
        log("Servidor detenido desde la bandeja.")


if __name__ == "__main__":
    _args = sys.argv[1:]
    _tray = "--tray" in _args
    if _tray or sys.stdout is None:
        open_log()
    try:
        asyncio.run(main(_args, _tray))
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    except Exception as _e:  # sin consola: que el error no pase desapercibido
        log(f"Error fatal: {_e!r}")
        if _tray:
            import tray
            tray.message_box(f"Control PC se cerró por un error:\n{_e}\n\nRegistro: {LOG_FILE}", warn=True)
        raise
