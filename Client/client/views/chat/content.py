"""聊天内容面板 — 显示消息 + 输入框 + DM 设置标签页"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Input

from ...config import (
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM,
    ICON_INDENT, M_DIM, M_END,
)
from ...widgets.panel import Panel
from .list import DMAction


_DM_SETTINGS = [
    {"label": "消息通知", "action": "toggle_notify"},
    {"label": "清空记录", "action": "clear"},
    {"label": "关闭对话", "action": "close"},
]


class ChatContentPanel(Panel):
    """右侧聊天内容：消息流 + 底部输入，DM 模式有设置标签页"""

    has_input = True
    placeholder = "输入消息……"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._current_tab: str = "world"
        self._chat_state = None
        self._showing_doc: bool = False
        self._saved_tab: str = ""
        # DM 设置标签页状态
        self._settings_cursor: int = 0
        self._confirming: str = ''  # 'clear' | ''

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t1"):
            yield Static("", classes="content icon-align", markup=True)

    def bind_state(self, st) -> None:
        self._chat_state = st.chat
        st.chat.add_listener(self._on_chat_event)
        self._render_current()

    def show_conversation(self, tab: str) -> None:
        """切换到指定对话"""
        if self._showing_doc:
            self.close_doc()
        self._current_tab = tab
        if self._chat_state:
            if tab not in ("world", "room"):
                self._chat_state.clear_dm_unread(tab)
                self._chat_state.set_viewing_dm(tab)
                # 按需加载：首次打开时向服务器请求历史
                if not self._chat_state.dm_entries.get(tab):
                    self.app.network.send({
                        "type": "get_dm_history", "target": tab,
                    })
            else:
                self._chat_state.set_viewing_dm('')
        # DM 模式启用标签页
        if tab not in ("world", "room"):
            self.tabs = ["聊天", "设置"]
            self._settings_cursor = 0
            self._confirming = ''
        else:
            self.tabs = []
        # 始终切回聊天 tab
        if self._active != 0:
            self.switch_tab(0)
        self._update_title()
        self._render_current()

    def _update_title(self) -> None:
        tab = self._current_tab
        if self.tabs:
            self.border_title = self._render_tabs()
        elif tab == "world":
            self.border_title = "世界"
        elif tab == "room":
            self.border_title = "房间"
        else:
            self.border_title = tab

    def show_doc(self, renderable) -> None:
        if not self._showing_doc:
            self._saved_tab = self._current_tab
        self._showing_doc = True
        self.border_title = "帮助"
        self.query_one("#t0 .content", Static).update(renderable)
        vs = self.query_one("#t0", VerticalScroll)
        self.call_after_refresh(vs.scroll_home, animate=False)

    def close_doc(self) -> None:
        if not self._showing_doc:
            return
        self._showing_doc = False
        self._current_tab = self._saved_tab or "room"
        self.show_conversation(self._current_tab)

    def _on_chat_event(self, event: str, *args):
        if event == 'add_world_message' and self._current_tab == "world":
            name, text, time = args
            self._append_line(self._format_world(name, text, time))
        elif event == 'set_world_history' and self._current_tab == "world":
            self._render_current()
        elif event == 'add_room_message' and self._current_tab == "room":
            name, text, time = args
            self._append_line(self._format_world(name, text, time))
        elif event == 'clear_room_messages' and self._current_tab == "room":
            self._render_current()
        elif event == 'add_private_message':
            peer = args[0]
            if peer == self._current_tab and self._active == 0:
                from_name, text, time = args[1], args[2], args[3]
                is_self = (from_name == self._chat_state._player_name)
                self._append_line(self._format_dm(text, time, is_self))

    def _render_current(self) -> None:
        cs = self._chat_state
        if not cs:
            return
        if self._current_tab == "world":
            lines = [self._format_world(n, t, ts) for n, t, ts in cs.world_messages]
        elif self._current_tab == "room":
            lines = [self._format_world(n, t, ts) for n, t, ts in cs.room_messages]
        else:
            entries = cs.dm_entries.get(self._current_tab, [])
            me = cs._player_name
            lines = [self._format_dm(t, ts, f == me) for f, t, ts in entries]
        self.query_one("#t0 .content", Static).update("\n".join(lines))
        vs = self.query_one("#t0", VerticalScroll)
        vs.scroll_end(animate=False)

    def _append_line(self, line: str) -> None:
        vs = self.query_one("#t0", VerticalScroll)
        at_bottom = vs.scroll_offset.y >= vs.max_scroll_y - 1
        content = self.query_one("#t0 .content", Static)
        old = content.content
        content.update(f"{old}\n{line}" if old else line)
        if at_bottom:
            vs.scroll_end(animate=False)

    @staticmethod
    def _format_world(name: str, text: str, time: str) -> str:
        t = time[:5] if len(time) > 5 else time
        return f"{M_DIM}{t}{M_END} {name}: {text}"

    @staticmethod
    def _format_dm(text: str, time: str, is_self: bool) -> str:
        t = time[:5] if len(time) > 5 else time
        if is_self:
            return f"{M_DIM}{t} {text}{M_END}"
        return f"{M_DIM}{t}{M_END} [{COLOR_FG_PRIMARY}]{text}[/]"

    # ── 设置标签页 ──

    def _render_settings(self) -> None:
        """渲染 DM 设置列表到 #t1"""
        peer = self._current_tab
        if self._confirming:
            self.update(self._render_confirm(
                f"确认清空与 {peer} 的聊天记录?", COLOR_HINT_TAB_DIM), tab=1)
            return
        notify_on = peer not in self._chat_state.dm_muted if self._chat_state else True
        lines = []
        for i, item in enumerate(_DM_SETTINGS):
            label = item["label"]
            if item["action"] == "toggle_notify":
                status = "开启" if notify_on else "关闭"
                label = f"{label}: {status}"
            if i == self._settings_cursor:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {label}[/]")
            else:
                lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{label}[/]")
        self.update("\n".join(lines), tab=1)

    def switch_tab(self, index: int) -> None:
        super().switch_tab(index)
        if self._active == 1:
            self._settings_cursor = 0
            self._confirming = ''
            self._render_settings()

    # ── 导航 ──

    def nav(self, action: str) -> None:
        if self._active == 1:
            self._nav_settings(action)
            return
        # 聊天 tab：只在 DM 模式允许切标签
        if action in ("tab_prev", "tab_next") and self.tabs:
            super().nav(action)
            return
        # 默认滚动
        if action in ("up", "down"):
            super().nav(action)

    def _nav_settings(self, action: str) -> None:
        if self._confirming:
            if action in ("tab_prev", "tab_next"):
                self._confirming = ''
                super().nav(action)
                return
            def _on_yes():
                self.post_message(DMAction(self._current_tab, "clear"))
                self._confirming = ''
            def _on_dismiss():
                self._confirming = ''
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._render_settings()
            return
        if action == "up" and self._settings_cursor > 0:
            self._settings_cursor -= 1
            self._render_settings()
        elif action == "down" and self._settings_cursor < len(_DM_SETTINGS) - 1:
            self._settings_cursor += 1
            self._render_settings()
        elif action == "enter":
            item = _DM_SETTINGS[self._settings_cursor]
            act = item["action"]
            if act == "toggle_notify":
                self.post_message(DMAction(self._current_tab, "toggle_notify"))
                self._render_settings()
            elif act == "clear":
                self._confirming = 'clear'
                self._confirm_cursor = 0
                self._render_settings()
            elif act == "close":
                self.post_message(DMAction(self._current_tab, "close"))
        elif action in ("tab_prev", "tab_next"):
            super().nav(action)

    # ── 输入提交 ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            event.stop()
            return
        if self._current_tab == "world":
            self.app.network.send({"type": "chat", "text": text, "channel": 1})
        elif self._current_tab == "room":
            self.app.network.send({"type": "room_chat", "text": text})
        else:
            self.app.network.send({
                "type": "private_chat",
                "target": self._current_tab,
                "text": text,
            })
        event.stop()
