"""
Vim 模式状态机
支持 Normal / Insert 两种模式
"""

from enum import Enum, auto

from . import ime


class Mode(Enum):
    NORMAL = auto()
    INSERT = auto()


class VimMode:
    """Vim 风格键位状态机"""

    def __init__(self):
        self.mode = Mode.NORMAL
        self.pending_key = ""         # Normal 模式下的前缀键（如 g）
        self._count_buffer = ""       # 数字前缀缓冲（如 5j 中的 "5"）
        self._on_mode_change = None
        self.sticky = False           # True=I(保持输入框), False=i(执行后关闭)

    def consume_count(self) -> int:
        """返回累积的数字前缀（默认1），并重置缓冲。"""
        count = int(self._count_buffer) if self._count_buffer else 1
        self._count_buffer = ""
        return min(count, 99)

    @property
    def mode_label(self) -> str:
        if self.mode == Mode.NORMAL:
            return "NORMAL"
        elif self.mode == Mode.INSERT:
            return "INSERT"
        return ""

    def set_mode_change_callback(self, cb):
        self._on_mode_change = cb

    def enter_normal(self):
        self.mode = Mode.NORMAL
        self.pending_key = ""
        self._count_buffer = ""
        ime.on_enter_normal()
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def enter_insert(self):
        self.mode = Mode.INSERT
        self.pending_key = ""
        self._count_buffer = ""
        ime.on_enter_insert()
        if self._on_mode_change:
            self._on_mode_change(self.mode)
