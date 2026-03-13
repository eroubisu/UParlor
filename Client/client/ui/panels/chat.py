"""ChatPanel — 聊天面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..widgets import InputBar, _set_pane_subtitle
from ...state import ModuleStateManager, MSG, SYS, HISTORY


class ChatPanel(Widget):
    """聊天面板：频道标签 + 消息日志 + 输入框"""

    CHANNEL_NAMES = {1: "世界", 2: "房间"}

    def __init__(self, **kw):
        super().__init__(**kw)
        self.current_channel = 1

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True, max_lines=500)
        yield InputBar(prompt_id="chat-prompt", id="chat-input-bar")

    def show_prompt(self, text: str = ""):
        try:
            self.query_one("#chat-input-bar", InputBar).show_prompt(text)
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            self.query_one("#chat-input-bar", InputBar).update_prompt(text)
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one("#chat-input-bar", InputBar).hide_prompt()
        except Exception:
            pass

    def show_input_bar(self):
        try:
            self.query_one("#chat-input-bar", InputBar).add_class("visible")
        except Exception:
            pass
        try:
            self.query_one("#chat-log", RichLog).scroll_end(animate=False)
        except Exception:
            pass

    def hide_input_bar(self):
        try:
            self.query_one("#chat-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    def add_message(self, name: str, text: str, channel: int = 1, time_str: str = ""):
        if channel != self.current_channel:
            return
        log: RichLog = self.query_one("#chat-log", RichLog)
        log.write(f"{name}> {text}")

    def add_system_message(self, text: str):
        log: RichLog = self.query_one("#chat-log", RichLog)
        log.write(f"[dim]>>> {text}[/]")

    def show_history(self, messages: list, channel: int):
        if channel != self.current_channel:
            return
        log: RichLog = self.query_one("#chat-log", RichLog)
        log.clear()
        for m in messages:
            name = m.get("name", "???")
            text = m.get("text", "")
            log.write(f"{name}> {text}")

    def switch_channel(self, channel_id: int):
        self.current_channel = channel_id
        labels = []
        for cid, cname in self.CHANNEL_NAMES.items():
            if cid == channel_id:
                labels.append(f"[b]{cname}[/b]")
            else:
                labels.append(f"[dim]{cname}[/]")
        self.border_title = " │ ".join(labels)

    def update_online_users(self, users: list):
        if not users:
            _set_pane_subtitle(self, "")
            return
        _set_pane_subtitle(self, f"在线({len(users)})")

    def restore(self, state: ModuleStateManager):
        st = state.chat
        self.switch_channel(st.current_channel)
        log: RichLog = self.query_one("#chat-log", RichLog)
        for entry in st.entries:
            if entry[0] == MSG:
                _, name, text, channel, time_str = entry
                if channel == st.current_channel:
                    log.write(f"{name}> {text}")
            elif entry[0] == SYS:
                log.write(f"[dim]>>> {entry[1]}[/]")
            elif entry[0] == HISTORY:
                _, messages, channel = entry
                if channel == st.current_channel:
                    log.clear()
                    for m in messages:
                        log.write(f"{m.get('name', '???')}> {m.get('text', '')}")
        if st.online_count:
            _set_pane_subtitle(self, f"在线({st.online_count})")
