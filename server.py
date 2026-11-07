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
"""
import asyncio
import base64
import ctypes
import hashlib
import html
import ipaddress
import json
import mimetypes
import os
import secrets
import socket
import struct
import sys
import time
import urllib.parse
import webbrowser
from ctypes import wintypes
from pathlib import Path

if sys.platform != "win32":
    sys.exit("Este servidor está hecho para Windows.")

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
CONFIG_FILE = BASE / "config.json"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ----------------------------------------------------------------------------
# Configuración (token de acceso persistente)
# ----------------------------------------------------------------------------
def load_config(new_token=False):
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
        except (OSError, ValueError):
            cfg = {}
    if new_token or not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(9)
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
            if n > 1 << 20:
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
    def __init__(self, token, port):
        self.token = token
        self.port = port
        self.clients = 0

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
            if url.path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
                await self.websocket(reader, writer, headers, url, peer)
            else:
                await self.http(writer, method, url.path, peer)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError,
                asyncio.LimitOverrunError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- HTTP
    async def http(self, writer, method, path, peer):
        if method not in ("GET", "HEAD"):
            return self._respond(writer, 405, b"Metodo no permitido")
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

    @staticmethod
    def _respond(writer, status, body, ctype="text/plain; charset=utf-8"):
        reason = {200: "OK", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed"}[status]
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
            .replace("{{URLJS}}", json.dumps(main))

    # ----------------------------------------------------------- WebSocket
    async def websocket(self, reader, writer, headers, url, peer):
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode()
        )
        ws = WebSocket(reader, writer)
        token = urllib.parse.parse_qs(url.query).get("t", [""])[0]
        if not secrets.compare_digest(token.encode(), self.token.encode()):
            log(f"Conexión rechazada (código incorrecto) desde {peer}")
            ws.close(4001, "token")
            return

        self.clients += 1
        log(f"Celular conectado: {peer}  (conectados: {self.clients})")
        ws.send(["hello", socket.gethostname()])
        held = set()  # botones presionados por este cliente
        loop = asyncio.get_running_loop()
        try:
            while True:
                msg = await ws.recv()
                if msg is None:
                    break
                if isinstance(msg, str):
                    try:
                        self.dispatch(ws, json.loads(msg), held, loop)
                    except (ValueError, TypeError, IndexError, KeyError) as e:
                        log(f"Mensaje inválido: {e}")
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            for b in held:  # nunca dejar un botón "pegado"
                Input.button(b, False)
            ALT_TAB.release()
            self.clients -= 1
            log(f"Celular desconectado: {peer}  (conectados: {self.clients})")
            ws.close()

    @staticmethod
    def dispatch(ws, a, held, loop):
        t = a[0]
        if t == "m":
            Input.move(int(a[1]), int(a[2]))
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


def log(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


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
ul{list-style:none;padding:0;font-size:13px} ol{text-align:left;color:#9aa1b2;line-height:1.7}
</style></head><body><div class="card">
<h1>Vincular tu celular</h1>
<p>Conecta el celular a la <b>misma red Wi-Fi</b> que este PC y escanea el código con la cámara.</p>
<div id="qr"></div><br><code>{{URL}}</code>
<ol><li>Abre el enlace en Chrome.</li><li>Menú ⋮ → <b>Agregar a pantalla principal</b> para tenerla como app.</li></ol>
<p style="font-size:13px">¿No funciona? Prueba otra dirección:</p><ul>{{OTHERS}}</ul>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>
try{new QRCode(document.getElementById('qr'),{text:{{URLJS}},width:240,height:240,correctLevel:QRCode.CorrectLevel.M});}
catch(e){document.getElementById('qr').outerHTML='<p>(Sin internet para dibujar el QR: escribe la dirección en el celular)</p>';}
</script></body></html>"""


async def main():
    args = sys.argv[1:]
    cfg = load_config(new_token="--new-token" in args)
    port = int(args[args.index("--port") + 1]) if "--port" in args else int(cfg["port"])
    srv = Server(cfg["token"], port)
    try:
        server = await asyncio.start_server(srv.handle, "0.0.0.0", port, reuse_address=True)
    except OSError as e:
        sys.exit(f"No se pudo abrir el puerto {port}: {e}\n¿Ya hay otro servidor abierto?")

    ips = local_ips()
    print("=" * 62)
    print("  CONTROL REMOTO PC  -  servidor activo")
    print("=" * 62)
    print("  Abre esto en el celular (misma red Wi-Fi):")
    for ip in ips:
        print(f"    http://{ip}:{port}/?t={cfg['token']}")
    print(f"\n  Código QR:   http://localhost:{port}/pair")
    print("  Cerrar:      Ctrl + C")
    print("=" * 62, flush=True)
    if "--no-browser" not in args:
        webbrowser.open(f"http://localhost:{port}/pair")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServidor detenido.")
