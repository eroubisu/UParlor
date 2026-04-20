"""聊天对话列表面板 — 世界频道 + 私聊标签"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ...config import COLOR_FG_PRIMARY, COLOR_FG_TERTIARY, COLOR_HINT_TAB_DIM, ICON_INDENT
from ...widgets.panel import Panel


class ConversationSelected(Message):
    """用户选中某个对话"""
    def __init__(self, tab: str) -> None:
        super().__init__()
        self.tab = tab


class DMAction(Message):
    """DM 操作请求（清空记录 / 关闭对话）"""
    def __init__(self, peer: str, action: str) -> None:
        super().__init__()
        self.peer = peer
        self.action = action  # 'clear' | 'close'


class ChatListPanel(Panel):
    """左侧对话列表：世界频道 + 私聊标签"""

    icon_align = True
    title = "对话"

    _DM_ACTIONS = [
        {"label": "清空记录", "action": "clear"},
        {"label": "关闭对话", "action": "close"},
    ]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._items: list[str] = ["world"]  # tab keys
        self._chat_state = None
        self._menu_open: bool = False
        self._menu_cursor: int = 0
        self._confirming: str = ''  # 'clear' | ''
    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", classes="content", markup=True)

    def bind_state(self, st) -> None:
        self._chat_state = st.chat
        st.chat.add_listener(self._on_chat_event)
        self._refresh_list()

    def _on_chat_event(self, event: str, *args):
        if event in ('open_private_tab', 'close_private_tab',
                      'update_dm_history', 'add_private_message'):
            self._refresh_list()

    def _refresh_list(self) -> None:
        cs = self._chat_state
        if not cs:
            return
        self._items = ["world"] + list(cs.dm_tabs)
        self._cursor = min(self._cursor, max(0, len(self._items) - 1))
        self._update_display()

    def _update_display(self) -> None:
        cs = self._chat_state
        # 确认状态
        if self._confirming:
            peer = self._items[self._cursor] if self._items else ""
            self.update(self._render_confirm(
                f"确认清空与 {peer} 的聊天记录?", COLOR_HINT_TAB_DIM))
            return
        lines = []
        for i, tab in enumerate(self._items):
            if tab == "world":
                label = "世界"
                suffix = ""
            else:
                label = tab
                unread = cs.dm_unread.get(tab, 0) if cs else 0
                suffix = f" [{COLOR_FG_PRIMARY}]{unread}[/]" if unread else ""
            if i == self._cursor:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {label}{suffix}[/]")
            else:
                lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{label}{suffix}[/]")
        if self._menu_open:
            lines.append("")
            cur_tab = self._items[self._cursor] if self._items else ""
            lines.append(f"[{COLOR_FG_TERTIARY}]── {cur_tab} ──[/]")
            for i, act in enumerate(self._DM_ACTIONS):
                if i == self._menu_cursor:
                    lines.append(f"[bold {COLOR_FG_PRIMARY}]> {act['label']}[/]")
                else:
                    lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{act['label']}[/]")
        self._focus_line = self._cursor
        self.update("\n".join(lines))

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def _emit_selected(self) -> None:
        if self._items and 0 <= self._cursor < len(self._items):
            self.post_message(ConversationSelected(self._items[self._cursor]))

    def nav(self, action: str) -> None:
        # 确认状态处理
        if self._confirming:
            def _on_yes():
                peer = self._items[self._cursor]
                self.post_message(DMAction(peer, "clear"))
                self._confirming = ''
                self._refresh_list()
            def _on_dismiss():
                self._confirming = ''
                self._update_display()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._update_display()
            return
        if self._menu_open:
            if action == "up":
                if self._menu_cursor > 0:
                    self._menu_cursor -= 1
                    self._update_display()
            elif action == "down":
                if self._menu_cursor < len(self._DM_ACTIONS) - 1:
                    self._menu_cursor += 1
                    self._update_display()
            elif action == "enter":
                act = self._DM_ACTIONS[self._menu_cursor]
                peer = self._items[self._cursor]
                self._menu_open = False
                self._menu_cursor = 0
                if act["action"] == "clear":
                    self._confirming = 'clear'
                    self._confirm_cursor = 0
                    self._update_display()
                else:
                    self.post_message(DMAction(peer, act["action"]))
                    self._refresh_list()
            elif action in ("delete", "tab_prev", "tab_next"):
                self._menu_open = False
                self._menu_cursor = 0
                self._update_display()
            return
        if action == "up":
            if self._move_cursor(-1, len(self._items)):
                self._update_display()
                self._emit_selected()
        elif action == "down":
            if self._move_cursor(1, len(self._items)):
                self._update_display()
                self._emit_selected()
        elif action == "enter":
            if self._items:
                tab = self._items[self._cursor]
                self.post_message(ConversationSelected(tab))
        elif action == "delete":
            if self._items and self._cursor < len(self._items):
                tab = self._items[self._cursor]
                if tab != "world":
                    self._menu_open = True
                    self._menu_cursor = 0
                    self._update_display()
