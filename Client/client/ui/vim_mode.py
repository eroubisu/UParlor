"""
Vim 模式状态机
支持 Normal / Insert 两种模式
"""

from enum import Enum, auto


class Mode(Enum):
    NORMAL = auto()
    INSERT = auto()


class VimMode:
    """Vim 风格键位状态机"""

    def __init__(self):
        self.mode = Mode.NORMAL
        self.pending_key = ""         # Normal 模式下的前缀键（如 g）
        self._on_mode_change = None

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
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def enter_insert(self):
        self.mode = Mode.INSERT
        self.pending_key = ""
        if self._on_mode_change:
            self._on_mode_change(self.mode)
