"""聊天浮动窗口 — overlay 层，左侧对话列表 + 右侧聊天内容"""

from __future__ import annotations

from textual.app import ComposeResult

from ..widgets.window import Window
from .chat_list import ChatListPanel, ConversationSelected, DMAction
from .chat_content import ChatContentPanel


class ChatWindow(Window):
    """浮动聊天窗口"""

    DEFAULT_CSS = """
    ChatWindow {
        layer: floating;
        width: 62%;
        height: 62%;
    }
    ChatWindow > #chat-list {
        width: 20;
        height: 1fr;
    }
    ChatWindow > #chat-content {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["chat-list", "chat-content"]]
    primary_panel = "chat-list"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._bound = False

    def compose(self) -> ComposeResult:
        yield ChatListPanel(id="chat-list")
        yield ChatContentPanel(id="chat-content")

    def bind_state(self, st) -> None:
        if self._bound:
            return
        self._bound = True
        self.query_one("#chat-list", ChatListPanel).bind_state(st)
        cp = self.query_one("#chat-content", ChatContentPanel)
        cp.bind_state(st)
        cp.show_conversation("world")

    def show(self) -> None:
        super().show()

    def open_dm(self, peer: str) -> None:
        """打开与指定玩家的私聊"""
        cs = self.query_one("#chat-content", ChatContentPanel)
        cl = self.query_one("#chat-list", ChatListPanel)
        # 确保 DM 标签存在
        if cl._chat_state and peer not in cl._chat_state.dm_tabs:
            cl._chat_state.dm_tabs.append(peer)
            cl._chat_state.dm_entries.setdefault(peer, [])
            cl._refresh_list()
        # 同步左侧光标
        if peer in cl._items:
            cl._cursor = cl._items.index(peer)
            cl._update_display()
        # 右侧显示对话
        cs.show_conversation(peer)
        # 清除未读
        self._clear_dm_unread(peer)
        # 聚焦右侧
        self.focus_move('l')

    def hide(self) -> None:
        cp = self.query_one("#chat-content", ChatContentPanel)
        if cp._chat_state:
            cp._chat_state.viewing_dm = ''
        super().hide()

    def nav(self, action: str) -> None:
        super().nav(action)
        if action == "enter" and self._focus_pos == (0, 0):
            tab = self._current_dm_tab()
            self.focus_move('l')
            if tab:
                self._clear_dm_unread(tab)

    def on_conversation_selected(self, event: ConversationSelected) -> None:
        """左侧选中对话 → 右侧切换"""
        event.stop()
        tab = event.tab
        self.query_one("#chat-content", ChatContentPanel).show_conversation(tab)
        self._clear_dm_unread(tab)

    def on_dm_action(self, event: DMAction) -> None:
        """处理 DM 操作（清空记录 / 关闭对话）"""
        event.stop()
        peer = event.peer
        cs = self.query_one("#chat-list", ChatListPanel)._chat_state
        if not cs:
            return
        cp = self.query_one("#chat-content", ChatContentPanel)
        if event.action == "clear":
            cs.clear_dm_entries(peer)
            self.app.network.send({"type": "clear_dm_history", "target": peer})
            if cp._current_tab == peer:
                cp._render_current()
        elif event.action == "close":
            cp.show_conversation("world")
            cs.close_dm_tab(peer)
            # 聚焦回左侧列表
            self.focus_move('h')
        elif event.action == "toggle_notify":
            if peer in cs.dm_muted:
                cs.dm_muted.discard(peer)
            else:
                cs.dm_muted.add(peer)

    def _current_dm_tab(self) -> str:
        """当前左侧光标指向的私聊 tab（world 返回空串）"""
        cl = self.query_one("#chat-list", ChatListPanel)
        if cl._items and 0 <= cl._cursor < len(cl._items):
            tab = cl._items[cl._cursor]
            return tab if tab != "world" else ""
        return ""

    def _clear_dm_unread(self, tab: str) -> None:
        """清除指定对话的未读计数"""
        if not tab or tab == "world":
            return
        cl = self.query_one("#chat-list", ChatListPanel)
        cs = cl._chat_state
        if cs and cs.dm_unread.get(tab, 0) > 0:
            cs.dm_unread[tab] = 0
            cl._update_display()
            self.screen.update_badges()
