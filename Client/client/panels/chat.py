"""ChatPanel — 聊天面板（标签页：全局 + 私聊）"""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..widgets import InputBar, _set_pane_subtitle
from ..widgets.helpers import build_tab_overflow, _widget_width
from ..config import (
    MAX_LINES_CHAT, CHANNEL_NAMES, M_DIM, M_BOLD, M_END,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT, COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ..state import ModuleStateManager, MSG, SYS, HISTORY


def _chat_text(markup: str) -> RichText:
    """创建 overflow=fold 的 Rich Text，确保长文本在任意字符处断行。"""
    return RichText.from_markup(markup, overflow="fold")


class ChatPanel(Widget):
    """聊天面板：标签页（全局 + 私聊）+ 消息日志 + 输入框"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.current_channel = 1
        self._active_tab: str = "global"  # "global" | peer_name
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="chat-header", markup=True)
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

    # ── 标签页导航 ──

    def _tab_list(self) -> list[str]:
        """返回当前所有标签: ["global", peer1, peer2, ...]"""
        tabs = ["global"]
        st = self._state_mgr
        if st:
            tabs.extend(st.chat.dm_tabs)
        return tabs

    def nav_tab_next(self):
        tabs = self._tab_list()
        if len(tabs) <= 1:
            return
        idx = tabs.index(self._active_tab) if self._active_tab in tabs else 0
        self._active_tab = tabs[(idx + 1) % len(tabs)]
        self._sync_active_tab()

    def nav_tab_prev(self):
        tabs = self._tab_list()
        if len(tabs) <= 1:
            return
        idx = tabs.index(self._active_tab) if self._active_tab in tabs else 0
        self._active_tab = tabs[(idx - 1) % len(tabs)]
        self._sync_active_tab()

    def switch_channel(self, channel_id: int):
        """全局频道切换（由 _cycle_channel 调用）— 保持兼容"""
        self.current_channel = channel_id

    def _sync_active_tab(self):
        """切换标签后同步 state 并重新渲染"""
        st = self._state_mgr
        if st:
            st.chat.active_tab = self._active_tab
            st.chat.dm_unread.discard(self._active_tab)
        self._render_header()
        self._replay_tab()

    # ── 渲染 ──

    def _render_header(self):
        """渲染标签栏"""
        tabs = self._tab_list()
        st = self._state_mgr
        unread = st.chat.dm_unread if st else set()
        tab_parts = []
        for t in tabs:
            label = "全局" if t == "global" else t
            has_unread = t != "global" and t in unread
            if has_unread:
                label = f"{label}*"
            if t == self._active_tab:
                plain = f"● {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
            elif has_unread:
                plain = f"  {label}"
                markup = f"  [italic {COLOR_HINT_TAB_ACTIVE}]{label}[/]"
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        active_idx = tabs.index(self._active_tab) if self._active_tab in tabs else 0
        avail = _widget_width(self, "chat-header")
        tab_line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)

        try:
            header = self.query_one("#chat-header", Static)
            header.update(tab_line)
        except Exception:
            pass

    def on_resize(self, event) -> None:
        self._render_header()

    def _replay_tab(self):
        """重放当前标签页的消息"""
        try:
            log: RichLog = self.query_one("#chat-log", RichLog)
        except Exception:
            return
        log.clear()

        st = self._state_mgr
        if not st:
            return

        if self._active_tab == "global":
            # 全局频道 — 复用原有 entries
            for entry in st.chat.entries:
                if entry[0] == MSG:
                    _, name, text, channel, time_str = entry
                    if channel == self.current_channel:
                        if name == '[SYS]' and ('上线了' in text or '下线了' in text):
                            continue
                        log.write(_chat_text(f"{name}> {text}"))
                elif entry[0] == SYS:
                    log.write(_chat_text(f"{M_DIM}>>> {entry[1]}{M_END}"))
                elif entry[0] == HISTORY:
                    _, messages, channel = entry
                    if channel == self.current_channel:
                        log.clear()
                        for m in messages:
                            mn = m.get('name', '???')
                            mt = m.get('text', '')
                            if mn == '[SYS]' and ('上线了' in mt or '下线了' in mt):
                                continue
                            log.write(_chat_text(f"{mn}> {mt}"))
        else:
            # 私聊标签
            peer = self._active_tab
            entries = st.chat.dm_entries.get(peer, [])
            if not entries:
                log.write(_chat_text(f"{M_DIM}暂无消息{M_END}"))
                return
            for from_name, text, time_str in entries:
                log.write(_chat_text(f"{from_name}> {text}"))

        try:
            log.scroll_end(animate=False)
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
            if self._active_tab != "global":
                return
            if channel != self.current_channel:
                return
            if name == '[SYS]' and ('上线了' in text or '下线了' in text):
                return
            log.write(_chat_text(f"{name}> {text}"))

        elif event == 'add_system_message':
            if self._active_tab != "global":
                return
            (text,) = args
            log.write(_chat_text(f"{M_DIM}>>> {text}{M_END}"))

        elif event == 'set_history':
            messages, channel = args
            if self._active_tab != "global":
                return
            if channel != self.current_channel:
                return
            log.clear()
            for m in messages:
                mn = m.get('name', '???')
                mt = m.get('text', '')
                if mn == '[SYS]' and ('上线了' in mt or '下线了' in mt):
                    continue
                log.write(_chat_text(f"{mn}> {mt}"))

        elif event == 'switch_channel':
            (channel_id,) = args
            self.current_channel = channel_id
            if self._active_tab == "global":
                self._replay_tab()

        elif event == 'update_online_count':
            # 不再显示在线人数，由定时器显示时间
            pass

        elif event == 'open_private_tab':
            (peer_name,) = args
            self._active_tab = peer_name
            self._render_header()
            self._replay_tab()

        elif event == 'close_private_tab':
            (peer_name,) = args
            if self._active_tab == peer_name:
                self._active_tab = "global"
            self._render_header()
            self._replay_tab()

        elif event == 'switch_tab':
            (tab_name,) = args
            self._active_tab = tab_name
            self._render_header()
            self._replay_tab()

        elif event == 'add_private_message':
            peer, from_name, text, time_str = args
            # 更新标签栏（可能新开了标签）
            self._render_header()
            # 如果当前正在看这个私聊标签，追加显示
            if self._active_tab == peer:
                st = self._state_mgr
                # 首条消息时清除"暂无消息"占位
                if st and len(st.chat.dm_entries.get(peer, [])) == 1:
                    log.clear()
                log.write(_chat_text(f"{from_name}> {text}"))

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.chat
        st.set_listener(self._on_state_event)
        # 同步频道
        self.current_channel = st.current_channel
        self._active_tab = st.active_tab
        # 渲染标签栏
        self._render_header()
        # 恢复历史消息
        self._replay_tab()
        # 显示当前时间
        self._update_time()
        self._time_timer = self.set_interval(30, self._update_time)

    def _update_time(self):
        _set_pane_subtitle(self, datetime.now().strftime('%H:%M'))
