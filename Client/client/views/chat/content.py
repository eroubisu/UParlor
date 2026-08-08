"""聊天内容面板 — 显示消息、输入框和会话设置。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, Input

from ...chat_style import render_chat_groups
from ...config import COLOR_HINT_TAB_DIM
from ...widgets.panel import Panel
from ...window_engine import InputSpec, Option
from .list import DMAction


_DM_SETTINGS = [
    {"label": "消息通知", "action": "toggle_notify"},
    {"label": "清空记录", "action": "clear"},
    {"label": "关闭对话", "action": "close"},
]
_WORLD_SETTINGS = [
    {"label": "清空聊天记录", "action": "clear_world"},
]


class ChatContentPanel(Panel):
    """右侧聊天内容：消息流、底部输入和会话设置标签页。"""

    has_input = True
    placeholder = "输入消息……"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._current_tab: str = "world"
        self._chat_state = None
        self._showing_doc: bool = False
        self._saved_tab: str = ""
        self._confirming: str = ''  # 'clear' | ''
        self._world_history_armed = False

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
            if tab == "world":
                self._chat_state.reset_world_projection()
                self._chat_state.set_viewing_dm('')
            elif tab != "room":
                self._chat_state.clear_dm_unread(tab)
                self._chat_state.set_viewing_dm(tab)
                # 每个 State 会话至多加载一次；UI 清空后本会话不再回填旧记录。
                if self._chat_state.should_request_dm_history(tab):
                    self.app.network.send({
                        "type": "get_dm_history", "target": tab,
                    })
            else:
                self._chat_state.set_viewing_dm('')
        if tab == "world" or tab not in ("world", "room"):
            self.tabs = ["聊天", "设置"]
            self._confirming = ''
        else:
            self.tabs = []
        self._world_history_armed = False
        # 始终切回聊天 tab
        if self._active != 0:
            self.switch_tab(0)
        self._update_title()
        self.activate_input_context()
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
        self.activate_input_context()
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
        if event in (
                'add_world_message', 'set_world_history',
                'prepend_world_history', 'clear_world_messages') and (
                self._current_tab == "world"):
            if event == 'prepend_world_history':
                added = args[0] if args else 0
                if added:
                    self._world_history_armed = False
            elif event != 'set_world_history':
                self._world_history_armed = False
            self._render_current()
        elif event in ('add_room_message', 'clear_room_messages') and (
                self._current_tab == "room"):
            self._render_current()
        elif event == 'add_private_message':
            peer = args[0] if args else ""
            if peer == self._current_tab and self._active == 0:
                self._render_current()
        elif event == 'sender_updated':
            self._render_current()

    def _render_current(self) -> None:
        if self._active != 0:
            return
        cs = self._chat_state
        if not cs:
            return
        if self._current_tab == "world":
            entries = cs.world_messages
        elif self._current_tab == "room":
            entries = cs.room_messages
        else:
            entries = cs.dm_entries.get(self._current_tab, [])
        content = render_chat_groups(
            entries, cs.senders, self._content_width(0))
        if self._current_tab == "world" and self._world_history_armed:
            if cs.world_history_loading:
                prompt = "（正在加载历史消息）"
            elif cs.world_has_more:
                prompt = "（向上加载历史消息）"
            else:
                prompt = "（没有更早的历史消息）"
            prefix = f"[{COLOR_HINT_TAB_DIM}]{prompt}[/]"
            content = f"{prefix}\n\n{content}" if content else prefix
        self.update(content, tab=0)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._update_title()
        self._render_current()

    def reflow_content(self) -> None:
        if self._showing_doc:
            return
        if self._active == 0:
            self._render_current()
        else:
            self._render_settings()

    def input_spec(self) -> InputSpec:
        return InputSpec(
            context_id=f"chat:{self._current_tab}",
            placeholder=self.placeholder,
            visible=self._active == 0 and not self._showing_doc,
            enabled=self._active == 0 and not self._showing_doc,
            focus=True,
        )

    # ── 设置标签页 ──

    def _render_settings(self) -> None:
        """渲染当前会话的设置列表到 #t1。"""
        is_world = self._current_tab == "world"
        peer = self._current_tab
        if self._confirming:
            target = (
                "世界聊天的显示记录"
                if is_world
                else f"与 {peer} 的聊天记录"
            )
            self.update(self._render_confirm(
                f"确认清空{target}?", COLOR_HINT_TAB_DIM), tab=1)
            return
        notify_on = (
            peer not in self._chat_state.dm_muted
            if self._chat_state else True
        )
        options = []
        for item in _WORLD_SETTINGS if is_world else _DM_SETTINGS:
            label = item["label"]
            if item["action"] == "toggle_notify":
                status = "开启" if notify_on else "关闭"
                label = f"{label}: {status}"
            options.append(Option(item["action"], label, data=item))
        context = "world-settings" if is_world else f"dm-settings:{peer}"
        self.set_options(options, context)
        self.update(self.render_options(), tab=1)

    def switch_tab(self, index: int) -> None:
        super().switch_tab(index)
        if self._active == 1:
            self._confirming = ''
            self._render_settings()
        else:
            self.call_after_refresh(self._render_current)

    # ── 导航 ──

    def nav(self, action: str) -> None:
        if self._active == 1:
            self._nav_settings(action)
            return
        # 聊天 tab：世界聊天和 DM 均可切换到设置。
        if action in ("tab_prev", "tab_next") and self.tabs:
            super().nav(action)
            return
        if (
                action == "up"
                and self._current_tab == "world"
                and self.query_one("#t0", VerticalScroll).scroll_offset.y <= 0):
            if self._world_history_armed:
                self._request_world_history()
            else:
                self._world_history_armed = True
                self._render_current()
                self.call_after_refresh(
                    self.query_one("#t0", VerticalScroll).scroll_home,
                    animate=False,
                )
            return
        if action == "down" and self._world_history_armed:
            self._world_history_armed = False
            self._render_current()
        if action in ("up", "down"):
            super().nav(action)

    def _request_world_history(self) -> None:
        cs = self._chat_state
        if not cs or not cs.begin_world_history_request():
            self._render_current()
            return
        sent = self.app.network.send({
            "type": "get_chat_history",
            "before_id": cs.oldest_world_message_id,
            "after_id": "",
        })
        if not sent:
            cs.world_history_loading = False
            self.app.notify("历史消息请求发送失败。", severity="error")
        self._render_current()

    def _nav_settings(self, action: str) -> None:
        if self._confirming:
            if action in ("tab_prev", "tab_next"):
                self._confirming = ''
                super().nav(action)
                return
            def _on_yes():
                if self._current_tab == "world":
                    if self._chat_state:
                        self._chat_state.clear_world_messages()
                else:
                    self.post_message(DMAction(self._current_tab, "clear"))
                self._confirming = ''
            def _on_dismiss():
                self._confirming = ''
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._render_settings()
            return
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._render_settings()
        elif selected is not None:
            act = selected.id
            if act == "toggle_notify":
                self.post_message(DMAction(self._current_tab, "toggle_notify"))
                self._render_settings()
            elif act == "clear":
                self._confirming = 'clear'

                self._render_settings()
            elif act == "clear_world":
                self._confirming = 'clear'
                self._render_settings()
            elif act == "close":
                self.post_message(DMAction(self._current_tab, "close"))
        elif action in ("tab_prev", "tab_next"):
            super().nav(action)

    # ── 输入提交 ──

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._active != 0 or self._showing_doc:
            return
        text = self.submit_input(event, clear=True).strip()
        if not text:
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
        # 不调用 event.stop()：让事件冒泡到 screen_modes.on_input_submitted，
        # 以便非粘滞 INSERT (i) 能在提交后退出到 NORMAL。
