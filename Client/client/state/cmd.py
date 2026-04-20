"""指令面板状态"""

from __future__ import annotations

from ..config import MAX_LINES_CMD, M_DIM, M_END
from .base import BaseState


class CmdState(BaseState):
    """指令面板的全部状态"""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self.max_lines: int = MAX_LINES_CMD

    def add_line(self, text: str, **kw):
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M')
        stamped = f'{M_DIM}{ts}{M_END} {text}'
        if kw.get('update_last') and self.lines:
            self.lines[-1] = stamped
        else:
            self.lines.append(stamped)
            if len(self.lines) > self.max_lines:
                self.lines = self.lines[-self.max_lines:]
        self._notify('add_line', stamped, kw)

    def clear(self):
        self.lines.clear()
        self._notify('clear')
