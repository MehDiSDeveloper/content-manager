"""System-wide hotkey via Win32 RegisterHotKey (works while any other program has focus).

WM_HOTKEY is posted to the window whose HWND we register with; a native event filter picks it
up from Qt's message loop. Virtual-key codes make it independent of the keyboard layout.
"""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication, QObject, Signal

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_I = 0x49

IDEA_HOTKEY_LABEL = "Ctrl+Alt+I"
IDEA_HOTKEY = (MOD_CONTROL | MOD_ALT, VK_I)


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey") -> None:
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type: QByteArray | bytes, message: int) -> tuple[bool, int]:
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._owner.hotkey_id:
                self._owner.activated.emit()
                return True, 0
        return False, 0


class GlobalHotkey(QObject):
    activated = Signal()

    def __init__(self, hotkey_id: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.hotkey_id = hotkey_id
        self._hwnd: int | None = None
        self._filter = _Filter(self)
        self.registered = False

    def register(self, hwnd: int, modifiers: int, vk: int) -> bool:
        """False if another program already owns the combination (or not on Windows)."""
        if sys.platform != "win32":
            return False
        self.unregister()
        user32 = ctypes.windll.user32
        ok = bool(
            user32.RegisterHotKey(wintypes.HWND(hwnd), self.hotkey_id, modifiers | MOD_NOREPEAT, vk)
        )
        if ok:
            self._hwnd = hwnd
            app = QCoreApplication.instance()
            assert app is not None
            app.installNativeEventFilter(self._filter)
        self.registered = ok
        return ok

    def unregister(self) -> None:
        if self._hwnd is None or sys.platform != "win32":
            return
        ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(self._hwnd), self.hotkey_id)
        app = QCoreApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self._filter)
        self._hwnd = None
        self.registered = False


def force_foreground(hwnd: int) -> None:
    """A hotkey press grants foreground rights; make sure the popup actually takes focus."""
    if sys.platform == "win32":
        ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(hwnd))
