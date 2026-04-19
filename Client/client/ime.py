"""IME 自动切换 — 窗口焦点变化时自动调整输入法状态 (Windows)

使用 PostMessage WM_INPUTLANGCHANGEREQUEST 切换输入法语言，
经测试在 Textual TUI (ConPTY) 环境下有效。
"""

import sys

_available = False
_EN_US = 0x04090409
_ZH_CN = 0x08040804
_WM_INPUTLANGCHANGEREQUEST = 0x0050

if sys.platform == 'win32':
    try:
        import ctypes
        _user32 = ctypes.windll.user32
        _available = True
    except Exception:
        pass


def _switch_to(locale: int):
    if not _available:
        return
    try:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_INPUTLANGCHANGEREQUEST, 0, locale)
    except Exception:
        pass


def on_app_blur():
    """应用失去焦点 — 恢复中文键盘，避免切出后系统输入法停留在英文"""
    _switch_to(_ZH_CN)


def on_app_focus(normal_mode: bool = True):
    """应用恢复焦点 — 切换到英文键盘"""
    _switch_to(_EN_US)


def on_insert_enter():
    """进入 INSERT 模式 — 切换到中文输入法"""
    _switch_to(_ZH_CN)


def on_insert_leave():
    """退出 INSERT 模式 — 切换到英文键盘"""
    _switch_to(_EN_US)
