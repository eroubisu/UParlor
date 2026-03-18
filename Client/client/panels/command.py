"""CommandPanel — 记录面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..config import MAX_LINES_CMD
from ..state import ModuleStateManager
from ..widgets import InputBar
from ..widgets.prompt import InputBarMixin


def _translate_command(text: str) -> str:
    """将 /cmd args 翻译为中文标签（如有）"""
    from ..protocol.commands import filter_commands
    raw = text.lstrip('/')
    parts = raw.split(None, 1)
    if not parts:
        return text
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ''
    matches = filter_commands('/' + name)
    for m in matches:
        if m.command == '/' + name and m.label:
            return f"{m.label} {args}".rstrip() if args else m.label
    return text


def format_command_echo(text: str) -> str:
    """格式化指令回显 markup"""
    from ..config import COLOR_HINT_TAB_ACTIVE, COLOR_FG_SECONDARY
    display = _translate_command(text)
    return f"[{COLOR_HINT_TAB_ACTIVE}]>[/] [{COLOR_FG_SECONDARY}]{display}[/]"


class CommandPanel(InputBarMixin, Widget):
    """记录面板：只读交互历史 + 指令输入"""

    _state_mgr = None
    _input_bar_id = "cmd-input-bar"
    _scroll_target_id = "cmd-log"

    def compose(self) -> ComposeResult:
        yield RichLog(id="cmd-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_CMD)
        yield InputBar(prompt_id="cmd-prompt", id="cmd-input-bar", submit_on_enter=True)

    # ── 消息 ──

    def on_input_submit(self, text: str):
        if not text:
            return
        if not text.startswith("/"):
            text = "/" + text
        self.app.send_command(text)

    def echo_command(self, text: str) -> str:
        return format_command_echo(text)

    def add_message(self, text: str, update_last: bool = False):
        log: RichLog = self.query_one("#cmd-log", RichLog)
        log.write(text)

    def clear(self):
        log: RichLog = self.query_one("#cmd-log", RichLog)
        log.clear()

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        try:
            log: RichLog = self.query_one("#cmd-log", RichLog)
        except Exception:
            return
        if event == 'add_line':
            text, kw = args
            log.write(text)
        elif event == 'clear':
            log.clear()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.cmd
        st.add_listener(self._on_state_event)
        log: RichLog = self.query_one("#cmd-log", RichLog)
        for line in st.lines:
            log.write(line)

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.cmd.remove_listener(self._on_state_event)
