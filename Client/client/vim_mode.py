"""
Vim 模式状态机
支持 Normal / Insert / Command 三种模式
"""

from enum import Enum, auto


class Mode(Enum):
    NORMAL = auto()
    INSERT = auto()
    COMMAND = auto()


class VimMode:
    """Vim 风格键位状态机"""

    def __init__(self):
        self.mode = Mode.NORMAL
        self.command_buffer = ""      # Command 模式下的输入缓冲
        self.pending_key = ""         # Normal 模式下的前缀键（如 g, d）
        self._on_mode_change = None

    @property
    def mode_label(self) -> str:
        if self.mode == Mode.NORMAL:
            return "NORMAL"
        elif self.mode == Mode.INSERT:
            return "INSERT"
        elif self.mode == Mode.COMMAND:
            return f":{self.command_buffer}"
        return ""

    def set_mode_change_callback(self, cb):
        self._on_mode_change = cb

    def enter_normal(self):
        self.mode = Mode.NORMAL
        self.pending_key = ""
        self.command_buffer = ""
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def enter_insert(self):
        self.mode = Mode.INSERT
        self.pending_key = ""
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def enter_command(self):
        self.mode = Mode.COMMAND
        self.command_buffer = ""
        self.pending_key = ""
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def command_append(self, ch: str):
        self.command_buffer += ch
        if self._on_mode_change:
            self._on_mode_change(self.mode)

    def command_backspace(self):
        if self.command_buffer:
            self.command_buffer = self.command_buffer[:-1]
            if self._on_mode_change:
                self._on_mode_change(self.mode)
        else:
            self.enter_normal()

    def command_submit(self) -> str:
        """提交 Command 模式缓冲，返回完整命令字符串，自动回到 Normal"""
        cmd = self.command_buffer
        self.enter_normal()
        return cmd
