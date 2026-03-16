"""IME 自动切换 — vim 模式切换时自动调整输入法状态 (Windows)

NORMAL 模式：切英文键盘（确保 hjkl 等键直接生效）
INSERT 模式：切中文键盘（允许中文输入）

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


def on_enter_normal():
    """进入 NORMAL — 切换到英文键盘"""
    if not _available:
        return
    try:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_INPUTLANGCHANGEREQUEST, 0, _EN_US)
    except Exception:
        pass


def on_enter_insert():
    """进入 INSERT — 切换到中文键盘"""
    if not _available:
        return
    try:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_INPUTLANGCHANGEREQUEST, 0, _ZH_CN)
    except Exception:
        pass


def on_app_blur():
    """应用失去焦点 — 恢复中文键盘，避免切出后系统输入法停留在英文"""
    if not _available:
        return
    try:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_INPUTLANGCHANGEREQUEST, 0, _ZH_CN)
    except Exception:
        pass


def on_app_focus(normal_mode: bool):
    """应用恢复焦点 — 根据当前模式恢复 IME 状态"""
    if normal_mode:
        on_enter_normal()
    else:
        on_enter_insert()
