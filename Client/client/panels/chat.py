"""ChatPanel — 聊天面板（标签页：全局 + 私聊）"""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..widgets import InputBar, _set_pane_subtitle, MenuNav, render_menu_lines
from ..widgets.prompt import InputBarMixin
from ..widgets.helpers import update_tab_header
from ..config import (
    MAX_LINES_CHAT, CHANNEL_NAMES, M_DIM, M_BOLD, M_END,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT, COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ..state import ModuleStateManager, MSG, SYS, HISTORY


def _chat_text(markup: str) -> RichText:
    """创建 overflow=fold 的 Rich Text，确保长文本在任意字符处断行。"""
    return RichText.from_markup(markup, overflow="fold")


def _fmt_msg(name: str, text: str, time_str: str = "") -> str:
    """格式化一条聊天消息 markup: [MM:SS] name> text"""
    t = time_str[:5] if len(time_str) >= 5 else ""
    if t:
        return f"{M_DIM}{t}{M_END} {name}> {text}"
    return f"{name}> {text}"


_SETTINGS_TAB_ACTIONS = ["关闭标签页", "清空标签页"]


class ChatPanel(InputBarMixin, Widget):
    """聊天面板：标签页（全局 + 私聊 + 设置）+ 消息日志 + 输入框"""

    _input_bar_id = "chat-input-bar"
    _scroll_target_id = "chat-log"

    def on_input_submit(self, text: str):
        if not text:
            return
        if self._active_tab != "global":
            self.app.network.send({"type": "private_chat", "target": self._active_tab, "text": text})
        else:
            self.app.send_chat(text, self.current_channel)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.current_channel = 1
        self._active_tab: str = "global"  # "global" | peer_name | "settings"
        self._state_mgr: ModuleStateManager | None = None
        self._settings_nav = MenuNav([])
        self._settings_target: str | None = None
        self._settings_action: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="chat-header", markup=True)
        yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_CHAT, min_width=0)
        yield InputBar(prompt_id="chat-prompt", id="chat-input-bar")

    # ── 标签页导航 ──

    def _tab_list(self) -> list[str]:
        """返回当前所有标签: ["global", peer1, peer2, ..., "settings"]"""
        tabs = ["global"]
        st = self._state_mgr
        if st:
            tabs.extend(st.chat.dm_tabs)
        tabs.append("settings")
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

    def nav_down(self, count=1):
        if self._active_tab == "settings":
            self._settings_nav.nav_down()
            self._replay_tab()
            return
        try:
            log: RichLog = self.query_one("#chat-log", RichLog)
            for _ in range(count):
                log.scroll_down(animate=False)
        except Exception:
            pass

    def nav_up(self, count=1):
        if self._active_tab == "settings":
            self._settings_nav.nav_up()
            self._replay_tab()
            return
        try:
            log: RichLog = self.query_one("#chat-log", RichLog)
            for _ in range(count):
                log.scroll_up(animate=False)
        except Exception:
            pass

    def nav_enter(self):
        if self._active_tab != "settings":
            return
        nav = self._settings_nav
        if nav.depth == 0:
            # 选定某个私聊标签
            items = self._settings_items()
            if not items:
                return
            self._settings_target = nav.selected
            nav.push(_SETTINGS_TAB_ACTIONS)
        elif nav.depth == 1:
            # 选择操作（关闭/清空）
            self._settings_action = nav.selected
            nav.push(["确认", "取消"])
        elif nav.depth == 2:
            if nav.cursor == 0:  # 确认
                peer = self._settings_target
                action = self._settings_action
                st = self._state_mgr
                if st and peer:
                    if action == "关闭标签页":
                        st.chat.close_private_tab(peer)
                    elif action == "清空标签页":
                        st.chat.clear_private_tab(peer)
                self._settings_target = None
                self._settings_action = None
                nav.reset(self._settings_items())
                self._render_header()
            else:  # 取消
                nav.pop()
                self._settings_action = None
        self._replay_tab()

    def nav_back(self) -> bool:
        if self._active_tab != "settings":
            return False
        nav = self._settings_nav
        if nav.pop():
            if nav.depth < 2:
                self._settings_action = None
            if nav.depth < 1:
                self._settings_target = None
            self._replay_tab()
            return True
        self._active_tab = "global"
        self._sync_active_tab()
        return True

    nav_escape = nav_back

    def _settings_items(self) -> list[str]:
        """设置页可关闭的私聊标签列表"""
        st = self._state_mgr
        if not st:
            return []
        return list(st.chat.dm_tabs)

    def switch_channel(self, channel_id: int):
        """全局频道切换（由 _cycle_channel 调用）— 保持兼容"""
        self.current_channel = channel_id

    def _sync_active_tab(self):
        """切换标签后同步 state 并重新渲染"""
        st = self._state_mgr
        if st and self._active_tab != "settings":
            st.chat.active_tab = self._active_tab
            st.chat.dm_unread.pop(self._active_tab, None)
        if self._active_tab == "settings":
            self._settings_nav.reset(self._settings_items())
            self._settings_target = None
            self._settings_action = None
        self._render_header()
        self._replay_tab()
        if hasattr(self.screen, 'update_badges'):
            self.screen.update_badges()

    def on_panel_focus(self):
        """面板聚焦时清除当前标签的未读"""
        st = self._state_mgr
        if st and self._active_tab not in ("global", "settings"):
            st.chat.dm_unread.pop(self._active_tab, None)
            self._render_header()
            if hasattr(self.screen, 'update_badges'):
                self.screen.update_badges()

    # ── 渲染 ──

    def _render_header(self):
        """渲染标签栏"""
        tabs = self._tab_list()
        st = self._state_mgr
        unread = st.chat.dm_unread if st else {}
        tab_parts = []
        for t in tabs:
            if t == "global":
                label = "全局"
            elif t == "settings":
                label = "设置"
            else:
                label = t
            has_unread = t not in ("global", "settings") and t in unread
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
        update_tab_header(self, "chat-header", tab_parts, active_idx)

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
                        log.write(_chat_text(_fmt_msg(name, text, time_str)))
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
                            log.write(_chat_text(_fmt_msg(mn, mt, m.get('time', ''))))
        elif self._active_tab == "settings":
            nav = self._settings_nav
            if nav.depth == 0:
                if not nav.items:
                    log.write(_chat_text(f"{M_DIM}暂无私聊标签页{M_END}"))
                    return
                labels = nav.items
            elif nav.depth == 1:
                peer = self._settings_target or "?"
                log.write(_chat_text(
                    f"{M_DIM}{peer}{M_END}"))
                labels = nav.items
            else:
                peer = self._settings_target or "?"
                action = self._settings_action or "?"
                log.write(_chat_text(
                    f"{M_DIM}{action} [{COLOR_FG_PRIMARY}]{peer}[/]？{M_END}"))
                labels = ["确认", "取消"]
            for line in render_menu_lines(
                    labels, nav.cursor,
                    COLOR_ACCENT, COLOR_FG_PRIMARY, COLOR_FG_SECONDARY):
                log.write(_chat_text(line))
        else:
            # 私聊标签
            peer = self._active_tab
            entries = st.chat.dm_entries.get(peer, [])
            if not entries:
                log.write(_chat_text(f"{M_DIM}暂无消息{M_END}"))
                return
            for from_name, text, time_str in entries:
                log.write(_chat_text(_fmt_msg(from_name, text, time_str)))

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
            log.write(_chat_text(_fmt_msg(name, text, time_str)))

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
                log.write(_chat_text(_fmt_msg(mn, mt, m.get('time', ''))))

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
                log.write(_chat_text(_fmt_msg(from_name, text, time_str)))

        elif event == 'dm_history_loaded':
            # 私聊历史批量加载完毕，刷新标签栏和当前视图
            self._render_header()
            self._replay_tab()

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.chat
        st.add_listener(self._on_state_event)
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

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.chat.remove_listener(self._on_state_event)

    def _update_time(self):
        _set_pane_subtitle(self, datetime.now().strftime('%H:%M'))
