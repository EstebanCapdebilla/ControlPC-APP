"""
Ícono de Control PC en la bandeja del sistema (junto al reloj de Windows).

Solo usa ctypes (API de Windows), así funciona con el Python embebido del instalador.
Corre en su propio hilo con su bucle de mensajes; el servidor sigue en asyncio.
"""
import ctypes
import os
import sys
import threading
import winreg
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL = 0x0002, 0x0010, 0x0111, 0x0000
WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0202, 0x0205, 0x0203
WM_APP = 0x8000
WM_TRAY = WM_APP + 1      # mensajes del ícono
WM_REFRESH = WM_APP + 2   # actualizar el texto (cambió el PIN, se conectó un celular...)
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED = 0x0, 0x800, 0x8, 0x1
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
MB_OK, MB_ICONINFO, MB_ICONWARN = 0x0, 0x40, 0x30

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ControlPC"


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.LoadImageW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT)
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPVOID)
user32.LoadIconW.restype = wintypes.HICON
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
user32.TrackPopupMenu.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.LPVOID)
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = (wintypes.HMENU,)
user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.MessageBoxW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
shell32.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def message_box(text, title="Control PC", warn=False):
    user32.MessageBoxW(None, text, title, MB_OK | (MB_ICONWARN if warn else MB_ICONINFO))


# ------------------------------------------------------------- iniciar con Windows
def autostart_command(script):
    exe = sys.executable
    if exe.lower().endswith("python.exe"):  # sin ventana negra
        w = exe[:-10] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    return f'"{exe}" "{script}" --tray --no-browser'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on, script):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command(script))
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


# ---------------------------------------------------------------------- ícono
class Tray:
    ID_PAIR, ID_AUTOSTART, ID_LOG, ID_FOLDER, ID_QUIT = 1, 2, 3, 4, 5

    def __init__(self, tooltip, on_pair, on_quit, icon_path=None, script=None, log_path=None, data_dir=None):
        """
        tooltip: función que devuelve el texto al pasar el mouse.
        on_pair / on_quit: se llaman desde el hilo del ícono.
        """
        self.tooltip = tooltip
        self.on_pair = on_pair
        self.on_quit = on_quit
        self.icon_path = icon_path
        self.script = script
        self.log_path = log_path
        self.data_dir = data_dir
        self.hwnd = None
        self.hicon = None
        self.ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # guardar referencia: si se libera, Windows llamaría a basura
        self._taskbar_created = 0

    # -- API (cualquier hilo)
    def start(self):
        threading.Thread(target=self._run, name="bandeja", daemon=True).start()
        self.ready.wait(5)

    def refresh(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)

    def notify(self, title, text, warn=False):
        if not self.hwnd:
            return
        nid = self._nid(NIF_INFO)
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_WARNING if warn else NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # -- interno (hilo del ícono)
    def _nid(self, flags):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = flags
        return nid

    def _add(self):
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip()[:127]
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _update_tip(self):
        nid = self._nid(NIF_TIP)
        nid.szTip = self.tooltip()[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "ControlPCTray"
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "Control PC", 0, 0, 0, 0, 0,
                                           None, None, hinst, None)
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        if self.icon_path and os.path.exists(self.icon_path):
            self.hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self.hicon:
            self.hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        self._add()
        self.ready.set()
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _menu(self):
        auto = autostart_enabled()
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, MF_STRING, self.ID_PAIR, "Mostrar PIN y código QR")
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if auto else 0) | (0 if self.script else MF_GRAYED),
                           self.ID_AUTOSTART, "Iniciar con Windows")
        user32.AppendMenuW(m, MF_STRING, self.ID_LOG, "Ver registro de conexiones")
        user32.AppendMenuW(m, MF_STRING, self.ID_FOLDER, "Abrir carpeta del programa")
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, self.ID_QUIT, "Salir")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # sin esto el menú no se cierra al hacer clic afuera
        cmd = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(m)
        self._command(cmd, auto)

    def _command(self, cmd, auto):
        try:
            if cmd == self.ID_PAIR:
                self.on_pair()
            elif cmd == self.ID_AUTOSTART:
                set_autostart(not auto, self.script)
            elif cmd == self.ID_LOG and self.log_path:
                os.startfile(self.log_path)
            elif cmd == self.ID_FOLDER:
                os.startfile(os.path.dirname(self.script) if self.script else self.data_dir)
            elif cmd == self.ID_QUIT:
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        except OSError as e:
            message_box(f"No se pudo completar la acción:\n{e}", warn=True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            ev = lparam & 0xFFFF
            if ev == WM_RBUTTONUP:
                self._menu()
            elif ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.on_pair()
            return 0
        if msg == WM_REFRESH:
            self._update_tip()
            return 0
        if msg == self._taskbar_created and msg:  # el Explorador se reinició: volver a poner el ícono
            self._add()
            return 0
        if msg == WM_CLOSE:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid(0)))
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.hwnd = None
            user32.PostQuitMessage(0)
            self.on_quit()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
