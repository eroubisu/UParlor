"""ChatPanel — 聊天面板"""

from __future__ import annotations

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..widgets import InputBar, _set_pane_subtitle
from ..config import MAX_LINES_CHAT, CHANNEL_NAMES, M_DIM, M_BOLD, M_END
from ..state import ModuleStateManager, MSG, SYS, HISTORY


def _chat_text(markup: str) -> RichText:
    """创建 overflow=fold 的 Rich Text，确保长文本在任意字符处断行。"""
    return RichText.from_markup(markup, overflow="fold")


class ChatPanel(Widget):
    """聊天面板：频道标签 + 消息日志 + 输入框"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.current_channel = 1

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_CHAT)
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

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        """State 变更回调 — 将数据变更映射为 RichLog 渲染"""
        try:
            log: RichLog = self.query_one("#chat-log", RichLog)
        except Exception:
            return
        if event == 'add_message':
            name, text, channel, time_str = args
            if channel != self.current_channel:
                return
            log.write(_chat_text(f"{name}> {text}"))
        elif event == 'add_system_message':
            (text,) = args
            log.write(_chat_text(f"{M_DIM}>>> {text}{M_END}"))
        elif event == 'set_history':
            messages, channel = args
            if channel != self.current_channel:
                return
            log.clear()
            for m in messages:
                log.write(_chat_text(f"{m.get('name', '???')}> {m.get('text', '')}"))
        elif event == 'switch_channel':
            (channel_id,) = args
            self.current_channel = channel_id
            labels = []
            for cid, cname in CHANNEL_NAMES.items():
                if cid == channel_id:
                    labels.append(f"{M_BOLD}{cname}{M_END}")
                else:
                    labels.append(f"{M_DIM}{cname}{M_END}")
            self.border_title = " │ ".join(labels)
        elif event == 'update_online_count':
            (users,) = args
            if not users:
                _set_pane_subtitle(self, "")
                return
            _set_pane_subtitle(self, f"在线({len(users)})")

    def restore(self, state: ModuleStateManager):
        st = state.chat
        # 注册为 listener
        st.set_listener(self._on_state_event)
        # 同步频道
        self.current_channel = st.current_channel
        self._on_state_event('switch_channel', st.current_channel)
        # 恢复历史消息
        log: RichLog = self.query_one("#chat-log", RichLog)
        for entry in st.entries:
            if entry[0] == MSG:
                _, name, text, channel, time_str = entry
                if channel == st.current_channel:
                    log.write(_chat_text(f"{name}> {text}"))
            elif entry[0] == SYS:
                log.write(_chat_text(f"{M_DIM}>>> {entry[1]}{M_END}"))
            elif entry[0] == HISTORY:
                _, messages, channel = entry
                if channel == st.current_channel:
                    log.clear()
                    for m in messages:
                        log.write(_chat_text(f"{m.get('name', '???')}> {m.get('text', '')}"))
        if st.online_count:
            _set_pane_subtitle(self, f"在线({st.online_count})")
