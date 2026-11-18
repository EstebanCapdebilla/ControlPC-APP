"""
Pantalla del PC en el celular.

Dos formas de enviar la imagen:
  * Video (WebRTC): un navegador Chromium (Brave, Chrome o Edge) en una ventana aparte
    y escondida captura la pantalla con getDisplayMedia y la manda como video al
    celular. La compresión la hace la tarjeta de video: fluido y con poca CPU.
    Con la opción --auto-select-desktop-capture-source elige la pantalla sola, sin clics.
  * Imágenes (respaldo): captura con GDI y la envía como PNG unas pocas veces por segundo.
    Se usa mientras arranca el video, o si el video no se puede usar (por ejemplo, si el
    navegador mostrara su ventana de "¿Qué quieres compartir?": se ve en la imagen y se
    puede tocar desde el celular).

Todo con la librería estándar de Python y la API de Windows (sin instalar nada).
"""
import ctypes
import os
import struct
import subprocess
import zlib
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


def set_dpi_aware():
    """Coordenadas y capturas en píxeles reales aunque Windows tenga escala (125 %, 150 %...)."""
    try:
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
    except AttributeError:
        pass
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass


def primary_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ------------------------------------------------------------------ captura con GDI
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HANDLE),
                ("ptScreenPos", wintypes.POINT)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


user32.GetDC.argtypes = (wintypes.HWND,)
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
user32.GetCursorInfo.argtypes = (ctypes.POINTER(CURSORINFO),)
user32.GetIconInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(ICONINFO))
user32.DrawIconEx.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT, wintypes.HBRUSH, wintypes.UINT)
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.SetStretchBltMode.argtypes = (wintypes.HDC, ctypes.c_int)
gdi32.SetBrushOrgEx.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPVOID)
gdi32.StretchBlt.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
gdi32.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, wintypes.LPVOID,
                            ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT)

SRCCOPY, CAPTUREBLT, HALFTONE = 0x00CC0020, 0x40000000, 4


def _draw_cursor(memdc, sw, sh, w, h):
    ci = CURSORINFO(cbSize=ctypes.sizeof(CURSORINFO))
    if not user32.GetCursorInfo(ctypes.byref(ci)) or not (ci.flags & 1) or not ci.hCursor:
        return
    ii = ICONINFO()
    hx = hy = 0
    if user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
        hx, hy = ii.xHotspot, ii.yHotspot
        for b in (ii.hbmMask, ii.hbmColor):
            if b:
                gdi32.DeleteObject(b)
    k = w / sw
    size = max(12, int(32 * k * 1.3))  # un poco más grande para que se vea en el celular
    x = int((ci.ptScreenPos.x - hx) * k)
    y = int((ci.ptScreenPos.y - hy) * k)
    user32.DrawIconEx(memdc, x, y, ci.hCursor, size, size, 0, None, 3)


def capture_rgb(max_w=960):
    """Captura la pantalla principal reducida a max_w de ancho. Devuelve (rgb, ancho, alto)."""
    sw, sh = primary_size()
    w = min(max_w, sw)
    h = max(1, round(sh * w / sw))
    src = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(src)
    bmp = gdi32.CreateCompatibleBitmap(src, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        gdi32.SetStretchBltMode(mem, HALFTONE)
        gdi32.SetBrushOrgEx(mem, 0, 0, None)
        gdi32.StretchBlt(mem, 0, 0, w, h, src, 0, 0, sw, sh, SRCCOPY | CAPTUREBLT)
        _draw_cursor(mem, sw, sh, w, h)
        bi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                              biPlanes=1, biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, src)
    bgra = buf.raw
    rgb = bytearray(w * h * 3)  # BGRA -> RGB (operaciones en C, rápidas)
    rgb[0::3] = bgra[2::4]
    rgb[1::3] = bgra[1::4]
    rgb[2::3] = bgra[0::4]
    return bytes(rgb), w, h


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def to_png(rgb, w, h):
    stride = w * 3
    raw = b"".join(b"\x00" + rgb[i:i + stride] for i in range(0, len(rgb), stride))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 1)) + _chunk(b"IEND", b""))


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)


def hide_capture_windows(port):
    """
    Oculta la ventana escondida del navegador (para que no aparezca en la barra de tareas) y
    la barra "localhost is sharing your screen" que el navegador pone abajo del escritorio.
    La captura sigue funcionando. El aviso de que se comparte la pantalla queda en el ícono
    de Control PC junto al reloj. Devuelve cuántas ventanas ocultó.
    """
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value != "Chrome_WidgetWin_1":
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        t = buf.value
        if (f"localhost:{port} is sharing your screen" in t) or ("compartiendo pantalla" in t and "Control PC" in t):
            found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    for h in found:
        user32.ShowWindow(h, 0)  # SW_HIDE
    return len(found)


# ------------------------------------------------------------------ navegador que comparte el video
def find_browser():
    """Brave, Chrome o Edge (todos Chromium: aceptan la selección automática de pantalla)."""
    pf = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    rel = [r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Google\Chrome\Application\chrome.exe",
           r"Microsoft\Edge\Application\msedge.exe"]
    for r in rel:
        for base in pf:
            if base:
                p = Path(base) / r
                if p.exists():
                    return str(p)
    return None


class CaptureBrowser:
    """Abre (y cierra) la ventana escondida del navegador que comparte la pantalla."""

    def __init__(self, profile_dir):
        self.profile = Path(profile_dir)
        self.proc = None
        self.exe = None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, url):
        if self.running():
            return True
        self.exe = find_browser()
        if not self.exe:
            return False
        self.profile.mkdir(parents=True, exist_ok=True)
        args = [
            self.exe,
            f"--user-data-dir={self.profile}",       # perfil propio: no toca tu navegador normal
            "--lang=en-US",                           # así el nombre de la pantalla es siempre "Entire screen"
            "--auto-select-desktop-capture-source=Entire screen",
            "--window-position=-32000,-32000", "--window-size=480,320",
            "--no-first-run", "--no-default-browser-check", "--disable-default-apps",
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=Translate,CalculateNativeWinOcclusion",
            f"--app={url}",
        ]
        self.proc = subprocess.Popen(args, creationflags=0x08000000)  # CREATE_NO_WINDOW
        return True

    def stop(self):
        if self.proc is None:
            return
        pid = self.proc.pid
        self.proc = None
        try:  # el navegador abre varios procesos: se cierra el árbol completo
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                           creationflags=0x08000000, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
