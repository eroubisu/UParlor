"""IME 自动切换 — 窗口焦点/输入模式变化时自动调整输入法状态

输入框里用哪种输入法由玩家自己决定：离开输入框时记住当前是中文还是英文，下次进入输入框
恢复它（还没有记录时用中文）；登录这类声明了英文输入法的输入框固定英文，也不改写记录。
NORMAL 模式一律是英文。

按客户端所在系统选择后端：
- Windows: PostMessage WM_INPUTLANGCHANGEREQUEST，经测试在 Textual TUI (ConPTY) 环境下有效。
- macOS: Text Input Source Services。切英文时记住当前中文输入源，切中文时恢复它；
  从未使用过中文输入源时，改选已启用的第一个中文输入源。
- 其他系统不做任何切换。
"""

import ctypes

from . import hostplatform

_EN_US = 0x04090409
_ZH_CN = 0x08040804
_WM_INPUTLANGCHANGEREQUEST = 0x0050

_CF_UTF8 = 0x08000100
_CF_PATH = '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
_CARBON_PATH = '/System/Library/Frameworks/Carbon.framework/Carbon'


class _WindowsSwitcher:
    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32

    def _switch_to(self, locale: int) -> None:
        try:
            hwnd = self._user32.GetForegroundWindow()
            if hwnd:
                self._user32.PostMessageW(hwnd, _WM_INPUTLANGCHANGEREQUEST, 0, locale)
        except Exception:
            pass

    def to_english(self) -> None:
        self._switch_to(_EN_US)

    def to_chinese(self) -> None:
        self._switch_to(_ZH_CN)

    def is_chinese(self) -> bool | None:
        """前台窗口当前的键盘布局是不是中文（主语言 ID 0x04）；问不到返回 None。"""
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return None
            thread = self._user32.GetWindowThreadProcessId(hwnd, None)
            layout = self._user32.GetKeyboardLayout(thread) & 0xFFFF
            return (layout & 0x3FF) == 0x04
        except Exception:
            return None


def _is_chinese_language(code: str | None) -> bool:
    return code is not None and (code == 'zh' or code.startswith('zh-'))


class _MacInputSources:
    """Text Input Source Services 的 ctypes 封装。current/ascii_capable/enabled_chinese
    返回的引用归调用方所有，用完必须 release。"""

    def __init__(self) -> None:
        self._cf = ctypes.CDLL(_CF_PATH)
        self._tis = ctypes.CDLL(_CARBON_PATH)
        vp = ctypes.c_void_p
        cf, tis = self._cf, self._tis
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [vp]
        cf.CFArrayGetValueAtIndex.restype = vp
        cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [vp]
        cf.CFRetain.restype = vp
        cf.CFRetain.argtypes = [vp]
        cf.CFRelease.argtypes = [vp]
        tis.TISCopyCurrentKeyboardInputSource.restype = vp
        tis.TISCopyCurrentASCIICapableKeyboardInputSource.restype = vp
        tis.TISCreateInputSourceList.restype = vp
        tis.TISCreateInputSourceList.argtypes = [vp, ctypes.c_bool]
        tis.TISGetInputSourceProperty.restype = vp
        tis.TISGetInputSourceProperty.argtypes = [vp, vp]
        tis.TISSelectInputSource.restype = ctypes.c_int32
        tis.TISSelectInputSource.argtypes = [vp]
        self._ascii_key = vp.in_dll(tis, 'kTISPropertyInputSourceIsASCIICapable')
        self._select_key = vp.in_dll(tis, 'kTISPropertyInputSourceIsSelectCapable')
        self._languages_key = vp.in_dll(tis, 'kTISPropertyInputSourceLanguages')

    def current(self):
        return self._tis.TISCopyCurrentKeyboardInputSource()

    def ascii_capable(self):
        return self._tis.TISCopyCurrentASCIICapableKeyboardInputSource()

    def retain(self, source):
        return self._cf.CFRetain(source)

    def release(self, source) -> None:
        self._cf.CFRelease(source)

    def select(self, source) -> None:
        self._tis.TISSelectInputSource(source)

    def _flag(self, source, key) -> bool:
        return self._cf.CFBooleanGetValue(self._tis.TISGetInputSourceProperty(source, key))

    def _string(self, ref) -> str | None:
        buffer = ctypes.create_string_buffer(128)
        if self._cf.CFStringGetCString(ref, buffer, len(buffer), _CF_UTF8):
            return buffer.value.decode('utf-8')
        return None

    def _languages(self, source) -> list[str | None]:
        array = self._tis.TISGetInputSourceProperty(source, self._languages_key)
        if not array:
            return []
        return [
            self._string(self._cf.CFArrayGetValueAtIndex(array, index))
            for index in range(self._cf.CFArrayGetCount(array))
        ]

    def is_chinese(self, source) -> bool:
        return not self._flag(source, self._ascii_key) and any(
            _is_chinese_language(code) for code in self._languages(source)
        )

    def enabled_chinese(self):
        """已启用且可选择的第一个中文输入源，没有则返回 None。"""
        sources = self._tis.TISCreateInputSourceList(None, False)
        if not sources:
            return None
        try:
            for index in range(self._cf.CFArrayGetCount(sources)):
                candidate = self._cf.CFArrayGetValueAtIndex(sources, index)
                if self._flag(candidate, self._select_key) and self.is_chinese(candidate):
                    return self._cf.CFRetain(candidate)
        finally:
            self._cf.CFRelease(sources)
        return None


class _MacSwitcher:
    def __init__(self, sources) -> None:
        self._sources = sources
        self._chinese = None

    def _remember(self, source) -> None:
        retained = self._sources.retain(source)
        if self._chinese is not None:
            self._sources.release(self._chinese)
        self._chinese = retained

    def to_english(self) -> None:
        sources = self._sources
        current = sources.current()
        target = sources.ascii_capable()
        try:
            if sources.is_chinese(current):
                self._remember(current)
            sources.select(target)
        finally:
            sources.release(current)
            sources.release(target)

    def to_chinese(self) -> None:
        if self._chinese is None:
            self._chinese = self._sources.enabled_chinese()
        if self._chinese is not None:
            self._sources.select(self._chinese)

    def is_chinese(self) -> bool | None:
        current = self._sources.current()
        try:
            return self._sources.is_chinese(current)
        finally:
            self._sources.release(current)


def _create_switcher():
    system = hostplatform.current()
    if system == hostplatform.WINDOWS:
        return _WindowsSwitcher()
    if system == hostplatform.MACOS:
        try:
            return _MacSwitcher(_MacInputSources())
        except (OSError, ValueError):
            return None
    return None


_switcher = _create_switcher()


def _to_english() -> None:
    if _switcher is not None:
        _switcher.to_english()


def _to_chinese() -> None:
    if _switcher is not None:
        _switcher.to_chinese()


_chinese_preferred = True   # 上一次在输入框里用的是不是中文（还没记录过：中文）


def _remember_current() -> None:
    """把此刻的输入法记成"输入框里用的那个"；问不到就保持原记录。"""
    global _chinese_preferred
    if _switcher is None:
        return
    chinese = _switcher.is_chinese()
    if chinese is not None:
        _chinese_preferred = chinese


def _enter_input_method(english_ime: bool) -> None:
    if english_ime or not _chinese_preferred:
        _to_english()
    else:
        _to_chinese()


def on_app_blur(in_insert: bool = False, english_ime: bool = False):
    """应用失去焦点 — 恢复中文键盘，避免切出后系统输入法停留在英文。
    正在输入框里时，先把当前的中英文记下来（回来时恢复）。"""
    if in_insert and not english_ime:
        _remember_current()
    _to_chinese()


def on_app_focus(normal_mode: bool = True, english_ime: bool = False):
    """应用恢复焦点 — NORMAL 模式切英文；正在输入框里就恢复输入框该用的输入法
    （不能无条件切英文：那会打断正在输入的中文）"""
    if normal_mode:
        _to_english()
    else:
        _enter_input_method(english_ime)


def on_insert_enter(english_ime: bool = False):
    """进入 INSERT 模式 — 恢复上次在输入框里用的输入法；声明了英文输入法的输入框保持英文"""
    _enter_input_method(english_ime)


def on_insert_leave(english_ime: bool = False):
    """退出 INSERT 模式 — 记住这次用的中英文，然后切回英文键盘"""
    if not english_ime:
        _remember_current()
    _to_english()
