"""聊天对话列表面板 — 世界频道 + 私聊标签"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static
from rich.markup import escape

from ...config import COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM
from ...widgets.panel import Panel
from ...window_engine import Divider, Option


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
    follow_focus = True
    title = "对话"

    _DM_ACTIONS = [
        {"label": "清空记录", "action": "clear"},
        {"label": "关闭对话", "action": "close"},
        {"label": "返回", "action": "return"},
    ]

    def __init__(self, **kw):
        super().__init__(**kw)
        self._items: list[str] = ["world"]  # tab keys
        self._chat_state = None
        self._menu_open: bool = False
        self._menu_peer: str = ""
        self._confirming: str = ''  # 'clear' | ''
    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            with Vertical(id="chat-list-rows"):
                yield Static("", classes="content", markup=True)
                yield Divider(id="chat-list-divider")
                yield Static("", id="chat-list-menu", markup=True)

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
        self._update_display()

    def _update_display(self) -> None:
        cs = self._chat_state
        # 确认状态
        if self._confirming:
            peer = self._menu_peer
            self.update(self._render_confirm(
                f"确认清空与 {peer} 的聊天记录?", COLOR_HINT_TAB_DIM))
            self.query_one("#chat-list-divider", Divider).display = False
            self.query_one("#chat-list-menu", Static).display = False
            return
        options = []
        for tab in self._items:
            if tab == "world":
                label = "世界"
                suffix = ""
            else:
                label = tab
                unread = cs.dm_unread.get(tab, 0) if cs else 0
                suffix = f" [{COLOR_FG_PRIMARY}]{unread}[/]" if unread else ""
            options.append(Option(
                tab, f"{escape(label)}{suffix}", markup=True,
            ))
        self.set_options(options, "chat-conversations")
        conversation_text = self.render_options()
        conversation_line = self.selected_line()
        divider = self.query_one("#chat-list-divider", Divider)
        menu_widget = self.query_one("#chat-list-menu", Static)
        divider.display = self._menu_open
        menu_widget.display = self._menu_open
        if self._menu_open:
            self.set_options(
                (Option(act["action"], act["label"], data=act)
                 for act in self._DM_ACTIONS),
                f"chat-actions:{self._menu_peer}",
            )
            menu_text = self.render_options()
            self._focus_line = (
                len(conversation_text.splitlines()) + 1 + self.selected_line()
            )
            menu_widget.update(menu_text)
        else:
            self._focus_line = conversation_line
        self.update(conversation_text)

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._refresh_list()

    def reflow_content(self) -> None:
        self._update_display()

    def _emit_selected(self) -> None:
        self.set_options(
            (Option(tab, "世界" if tab == "world" else tab)
             for tab in self._items),
            "chat-conversations",
        )
        selected = self.selected_option
        if selected is not None:
            self.post_message(ConversationSelected(selected.id))

    def nav(self, action: str) -> None:
        # 确认状态处理
        if self._confirming:
            def _on_yes():
                self.post_message(DMAction(self._menu_peer, "clear"))
                self._confirming = ''
                self._refresh_list()
            def _on_dismiss():
                self._confirming = ''
                self._update_display()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._update_display()
            return
        if self._menu_open:
            selected = self.selection.handle(action)
            if action in ("up", "down"):
                self._update_display()
            elif selected is not None:
                act = selected.data
                peer = self._menu_peer
                if act["action"] == "return":
                    self._menu_open = False
                    self._update_display()
                elif act["action"] == "clear":
                    self._menu_open = False
                    self._confirming = 'clear'
                    self._update_display()
                else:
                    self._menu_open = False
                    self.post_message(DMAction(peer, act["action"]))
                    self._refresh_list()
            return
        self.set_options(
            (Option(tab, "世界" if tab == "world" else tab)
             for tab in self._items),
            "chat-conversations",
        )
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._update_display()
            self._emit_selected()
        elif action == "enter" and selected is not None:
            self.post_message(ConversationSelected(selected.id))
            if selected.id != "world":
                self._menu_open = True
                self._menu_peer = selected.id
                self._update_display()
