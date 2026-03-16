"""AIChatPanel — AI 伙伴面板（角色选择 → 创建 → 聊天 + 菜单）"""

from __future__ import annotations

import asyncio
import re

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import M_DIM, M_END, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY
from ..state import ModuleStateManager
from ..widgets.input_bar import InputBar
from ..widgets import _set_pane_subtitle
from ..widgets.prompt import InputBarMixin
from ._ai_chat_render import _ChatRenderMixin, _TABS
from ._ai_chat_views import (
    _ChatViewsMixin,
    _VIEW_SETUP, _VIEW_SELECT, _VIEW_CREATE, _VIEW_CHAT,
)


class AIChatPanel(InputBarMixin, _ChatViewsMixin, _ChatRenderMixin, Widget):
    """AI 面板：选择角色 → 创建角色 → 聊天（菜单 + 状态栏）"""

    _input_bar_id = "ai-input-bar"

    class RequestInsert(Message):
        """面板请求 Screen 进入 INSERT 模式"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._service = None
        self._streaming = False
        self._stream_baseline = 0  # 流式开始前 log.lines 长度
        self._panel_active = False
        self._state_mgr: ModuleStateManager | None = None

        # 视图状态
        self._view: str = _VIEW_SELECT
        self._wants_insert: bool = False

        # SELECT 视图
        self._char_list: list = []
        self._select_cursor: int = 0

        # SETUP 视图
        self._setup_step: str = "api_key"  # api_key | model
        self._setup_key: str = ""
        self._setup_models: list[dict] = []
        self._setup_model_cursor: int = 0
        self._model_scroll_offset: int = 0

        # CREATE 视图
        self._create_step: str = ""     # desc | review
        self._create_desc: str = ""
        self._create_char = None        # Character | None
        self._create_status: str = ""   # 状态/错误信息
        self._create_tokens: int = 0    # 创建过程累计 token

        # CHAT 视图
        self._menu_tab: str = "chat"
        self._gift_items: list[dict] = []
        self._gift_cursor: int = 0
        self._gift_qty: int = 0         # 0=未选中, >0=选择数量中
        self._settings_cursor: int = 0
        self._model_picking: bool = False  # 设置中选模型
        self._reset_confirming: bool = False  # 重置记忆确认中
        self._has_unread: bool = False     # 未读 AI 消息

    def compose(self) -> ComposeResult:
        yield Static(id="ai-panel-content", markup=True)
        yield Static(id="ai-chat-header", markup=True)
        yield RichLog(
            id="ai-chat-log", wrap=True, highlight=True,
            markup=True, max_lines=500, min_width=0,
        )
        yield InputBar(prompt_id="ai-prompt", id="ai-input-bar")

    def on_mount(self) -> None:
        try:
            self.query_one("#ai-chat-log", RichLog).display = False
            self.query_one("#ai-chat-header", Static).display = False
        except Exception:
            pass

    def on_resize(self, event) -> None:
        if self._view == _VIEW_CHAT:
            self._render_header()

    # ── InputBar 标准接口 ──

    def show_input_bar(self):
        try:
            self.query_one("#ai-input-bar", InputBar).add_class("visible")
        except Exception:
            pass
        try:
            log = self.query_one("#ai-chat-log", RichLog)
            if log.display:
                log.scroll_end(animate=False)
        except Exception:
            pass
        try:
            content = self.query_one("#ai-panel-content", Static)
            if content.display:
                content.scroll_end(animate=False)
        except Exception:
            pass

    def cancel_input(self):
        # SETUP/CREATE 视图中必须保持输入状态
        if self._view in (_VIEW_SETUP, _VIEW_CREATE):
            return
        self._wants_insert = False

    # ── 属性 ──

    @property
    def wants_insert(self) -> bool:
        return self._wants_insert

    # ── 状态同步 ──

    def _set_view(self, view: str):
        self._view = view
        if self._state_mgr:
            self._state_mgr.ai_chat.view = view

    def _set_tab(self, tab: str):
        self._menu_tab = tab
        if self._state_mgr:
            self._state_mgr.ai_chat.menu_tab = tab

    def _sync_create_to_state(self):
        """将 CREATE/SETUP 瞬态同步到 State（rebuild 时保留）"""
        if not self._state_mgr:
            return
        st = self._state_mgr.ai_chat
        st.create_step = self._create_step
        st.create_desc = self._create_desc
        st.create_char = self._create_char
        st.create_status = self._create_status
        st.setup_step = self._setup_step
        st.setup_key = self._setup_key
        st.wants_insert = self._wants_insert

    # ── 导航协议 ──

    def nav_down(self):
        if self._view == _VIEW_SETUP:
            if self._setup_step == "model" and self._setup_models:
                self._setup_model_cursor = (self._setup_model_cursor + 1) % len(self._setup_models)
                self._adjust_model_scroll()
                self._refresh_content()
        elif self._view == _VIEW_SELECT:
            if self._char_list:
                self._select_cursor = (self._select_cursor + 1) % (len(self._char_list) + 1)
            self._refresh_content()
        elif self._view == _VIEW_CREATE:
            try:
                if self._create_step == "review":
                    self.query_one("#ai-chat-log", RichLog).scroll_down(animate=False)
                else:
                    self.query_one("#ai-panel-content", Static).scroll_down(animate=False)
            except Exception:
                pass
        elif self._view == _VIEW_CHAT:
            if self._menu_tab == "gift":
                if self._gift_qty > 0:
                    self._gift_qty = max(1, self._gift_qty - 1)
                elif self._gift_items:
                    self._gift_cursor = (self._gift_cursor + 1) % len(self._gift_items)
                self._refresh_content()
            elif self._menu_tab == "settings":
                if self._model_picking and self._setup_models:
                    self._setup_model_cursor = (self._setup_model_cursor + 1) % len(self._setup_models)
                    self._adjust_model_scroll()
                else:
                    self._settings_cursor = (self._settings_cursor + 1) % 8
                    self._reset_confirming = False
                self._refresh_content()
            else:
                try:
                    self.query_one("#ai-chat-log", RichLog).scroll_down(animate=False)
                except Exception:
                    pass

    def nav_up(self):
        if self._view == _VIEW_SETUP:
            if self._setup_step == "model" and self._setup_models:
                self._setup_model_cursor = (self._setup_model_cursor - 1) % len(self._setup_models)
                self._adjust_model_scroll()
                self._refresh_content()
        elif self._view == _VIEW_SELECT:
            if self._char_list:
                self._select_cursor = (self._select_cursor - 1) % (len(self._char_list) + 1)
            self._refresh_content()
        elif self._view == _VIEW_CREATE:
            try:
                if self._create_step == "review":
                    self.query_one("#ai-chat-log", RichLog).scroll_up(animate=False)
                else:
                    self.query_one("#ai-panel-content", Static).scroll_up(animate=False)
            except Exception:
                pass
        elif self._view == _VIEW_CHAT:
            if self._menu_tab == "gift":
                if self._gift_qty > 0:
                    item = self._gift_items[self._gift_cursor] if self._gift_items else None
                    max_qty = item.get("count", 1) if item else 1
                    self._gift_qty = min(max_qty, self._gift_qty + 1)
                elif self._gift_items:
                    self._gift_cursor = (self._gift_cursor - 1) % len(self._gift_items)
                self._refresh_content()
            elif self._menu_tab == "settings":
                if self._model_picking and self._setup_models:
                    self._setup_model_cursor = (self._setup_model_cursor - 1) % len(self._setup_models)
                    self._adjust_model_scroll()
                else:
                    self._settings_cursor = (self._settings_cursor - 1) % 8
                    self._reset_confirming = False
                self._refresh_content()
            else:
                try:
                    self.query_one("#ai-chat-log", RichLog).scroll_up(animate=False)
                except Exception:
                    pass

    def nav_enter(self):
        if self._view == _VIEW_SETUP:
            if self._setup_step == "model":
                self._on_setup_model_enter()
            return
        if self._view == _VIEW_SELECT:
            self._on_select_enter()
        elif self._view == _VIEW_CHAT:
            if self._menu_tab in ("chat", "action"):
                self._wants_insert = True
                self.show_input_bar()
            elif self._menu_tab == "gift":
                self._on_gift_enter()
            elif self._menu_tab == "settings":
                self._on_settings_enter()
        self._refresh_content()

    def nav_back(self) -> bool:
        if self._wants_insert:
            return False
        if self._gift_qty > 0:
            self._gift_qty = 0
            self._refresh_content()
            return True
        if self._model_picking:
            self._model_picking = False
            self._refresh_content()
            return True
        if self._view == _VIEW_CHAT:
            if self._menu_tab != "chat":
                self._set_tab("chat")
                self._refresh_content()
                return True
            return False
        if self._view == _VIEW_CREATE:
            self._set_view(_VIEW_SELECT)
            self._refresh_content()
            self._show_static()
            return True
        if self._view == _VIEW_SELECT:
            return False
        if self._view == _VIEW_SETUP:
            return False
        return False

    def nav_escape(self) -> bool:
        if self._gift_qty > 0:
            self._gift_qty = 0
            self._refresh_content()
            return True
        if self._model_picking:
            self._model_picking = False
            self._refresh_content()
            return True
        if self._wants_insert:
            self._wants_insert = False
            self.hide_input_bar()
            self._refresh_content()
            return True
        if self._view == _VIEW_SETUP:
            return False
        if self._view == _VIEW_CREATE:
            self._set_view(_VIEW_SELECT)
            self._refresh_content()
            self._show_static()
            return True
        return False

    def nav_tab_next(self):
        if self._view == _VIEW_CHAT and not self._wants_insert:
            idx = _TABS.index(self._menu_tab) if self._menu_tab in _TABS else 0
            self._set_tab(_TABS[(idx + 1) % len(_TABS)])
            self._refresh_content()

    def nav_tab_prev(self):
        if self._view == _VIEW_CHAT and not self._wants_insert:
            idx = _TABS.index(self._menu_tab) if self._menu_tab in _TABS else 0
            self._set_tab(_TABS[(idx - 1) % len(_TABS)])
            self._refresh_content()

    # ── State / Service 事件 ──

    def _on_state_event(self, event: str, *args):
        if event == "add_user":
            (text,) = args
            self._log(f"你> {text}")
        elif event == "add_ai":
            (text,) = args
            self._log_ai(text)
            if not self._is_panel_focused():
                self._has_unread = True
                self._update_unread_marker()

    def _on_service_event(self, event: str, *args):
        if event == "token_update":
            (display,) = args
            _set_pane_subtitle(self, f"tokens: {display}")
        elif event == "status_update":
            if self._view == _VIEW_CHAT:
                self._refresh_content()

    # ── 日志 / 流式输出 ──

    def _log(self, markup: str):
        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            # display 刚变 True 时 content region 宽度为 0，shrink 会把文本压成空行
            shrink = log.scrollable_content_region.width > 0
            log.write(RichText.from_markup(markup), shrink=shrink)
            log.scroll_end(animate=False)
        except Exception:
            pass

    def _log_streaming(self, text: str):
        """流式显示：截断回基线，用 _log_ai 格式重写"""
        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            if len(log.lines) > self._stream_baseline:
                del log.lines[self._stream_baseline:]
                log._line_cache.clear()
            self._log_ai(text)
            log.scroll_end(animate=False)
        except Exception:
            pass

    def _end_streaming_line(self):
        """移除所有流式占位行"""
        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            if len(log.lines) > self._stream_baseline:
                del log.lines[self._stream_baseline:]
                log._line_cache.clear()
                log.virtual_size = log.virtual_size._replace(
                    height=len(log.lines),
                )
                log.refresh()
        except Exception:
            pass

    _ACTION_RE = re.compile(r'\*([^*]+)\*')
    _PUNCTUATION_ONLY_RE = re.compile(r'^[\s。，！？…、；：.,!?;:]+$')
    _WRAP_QUOTES_RE = re.compile(r'^[""「](.+?)[""」]$')

    def _log_ai(self, text: str):
        """记录 AI 回复，按行解析 *动作* 和说话"""
        label = self._char_label
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            last = 0
            has_content = False
            for m in self._ACTION_RE.finditer(line):
                speech = line[last:m.start()].strip()
                speech = self._WRAP_QUOTES_RE.sub(r'\1', speech)
                if speech and not self._PUNCTUATION_ONLY_RE.match(speech):
                    self._log(f"{label}> {speech}")
                    has_content = True
                self._log(f"[italic {COLOR_FG_TERTIARY}]*{m.group(1)}*[/]")
                has_content = True
                last = m.end()
            tail = line[last:].strip()
            tail = self._WRAP_QUOTES_RE.sub(r'\1', tail)
            if tail and not self._PUNCTUATION_ONLY_RE.match(tail):
                self._log(f"{label}> {tail}")
                has_content = True
            if not has_content and not self._ACTION_RE.search(line):
                line = self._WRAP_QUOTES_RE.sub(r'\1', line)
                self._log(f"{label}> {line}")

    @property
    def _char_label(self) -> str:
        if self._service and self._service.character:
            return self._service.character.name or "?"
        return "?"

    # ── 未读标记 ──

    def _is_panel_focused(self) -> bool:
        node = self.parent
        while node is not None:
            if hasattr(node, 'pane_id'):
                return node.has_class("--focused")
            node = node.parent
        return False

    def _update_unread_marker(self):
        node = self.parent
        while node is not None:
            if hasattr(node, 'pane_id'):
                from ..registry import get_module_labels
                base = get_module_labels().get(node.module_name, '')
                node.border_title = f"{base} *" if self._has_unread else base
                return
            node = node.parent

    def on_panel_focus(self):
        """Screen 聚焦到本面板时调用，清除未读标记"""
        if self._has_unread:
            self._has_unread = False
            self._update_unread_marker()

    # ── 视图切换辅助 ──

    def _show_static(self):
        """显示 Static 内容面板，隐藏聊天日志和 Header"""
        try:
            self.query_one("#ai-panel-content", Static).display = True
            self.query_one("#ai-chat-log", RichLog).display = False
            self.query_one("#ai-chat-header", Static).display = False
        except Exception:
            pass
        self.hide_input_bar()

    def _show_chat(self):
        """显示聊天日志，隐藏 Static"""
        try:
            self.query_one("#ai-panel-content", Static).display = False
            self.query_one("#ai-chat-log", RichLog).display = True
        except Exception:
            pass

    # ── 内容刷新 ──

    def _refresh_content(self):
        """根据视图刷新 Static 面板内容或状态栏"""
        self._sync_create_to_state()
        if self._view == _VIEW_SETUP:
            self._render_setup()
        elif self._view == _VIEW_SELECT:
            self._render_select()
        elif self._view == _VIEW_CREATE:
            self._render_create()
        elif self._view == _VIEW_CHAT:
            self._render_chat_overlay()

    # ── 初始化 & 恢复 ──

    def restore(self, state: ModuleStateManager):
        self._panel_active = True
        self._state_mgr = state
        st = state.ai_chat
        st.set_listener(self._on_state_event)

        self._refresh_char_list()

        # 从 State 恢复 CREATE/SETUP 瞬态（rebuild 后保留进度）
        if st.view in (_VIEW_CREATE, _VIEW_SETUP):
            self._view = st.view
            self._create_step = st.create_step
            self._create_desc = st.create_desc
            self._create_char = st.create_char
            self._create_status = st.create_status
            self._setup_step = st.setup_step
            self._setup_key = st.setup_key
            self._wants_insert = st.wants_insert
            # 异步任务在 rebuild 中丢失：如果处于等待状态则恢复为可输入
            if self._create_status and not self._create_char and self._create_step == "desc":
                self._create_status = "窗口操作中断了上次请求，请重新提交"
                self._wants_insert = True
            # SETUP model 步骤丢失了模型列表 → 重新获取
            if st.view == _VIEW_SETUP and self._setup_step == "model" and not self._setup_models:
                self._create_status = "正在获取可用模型..."
                self._wants_insert = False
                self._show_static()
                self._refresh_content()
                import asyncio
                asyncio.get_event_loop().call_soon(
                    lambda: asyncio.ensure_future(self._do_fetch_models_for_setup()))
                return
            self._show_static()
            self._refresh_content()
            if self._wants_insert:
                self.post_message(self.RequestInsert())
            return

        # 检查全局 API Key
        from ..ai.config import load_global_config
        cfg = load_global_config()
        if not cfg.get("api_key", ""):
            self._set_view(_VIEW_SETUP)
            self._setup_step = "api_key"
            self._setup_key = ""
            self._setup_models = []
            self._setup_model_cursor = 0
            self._create_status = ""
            self._wants_insert = True
            self._show_static()
            self._refresh_content()
            self.post_message(self.RequestInsert())
            return

        # 根据状态恢复视图
        auto_start = cfg.get("auto_start", False)
        if auto_start:
            # 自动启动 — 恢复聊天或进入上次角色
            if st.current_char_id and st.view == _VIEW_CHAT:
                self._enter_character(st.current_char_id)
            else:
                last_id = cfg.get("last_character_id", "")
                if last_id and any(c.id == last_id for c in self._char_list):
                    self._enter_character(last_id)
                else:
                    self._set_view(_VIEW_SELECT)
                    self._show_static()
                    self._refresh_content()
        else:
            # 自动启动关闭 — 始终进入选择界面
            self._set_view(_VIEW_SELECT)
            self._show_static()
            self._refresh_content()

    def _ensure_service(self):
        if self._service:
            return
        try:
            from ..ai import AIService
            self._service = AIService(self._state_mgr)
            self._service.set_listener(self._on_service_event)
        except ImportError:
            self._log(f"{M_DIM}>>> AI 依赖未安装 (pip install google-genai){M_END}")

    # ── 用户提交 ──

    def on_user_submit(self, text: str):
        if not text:
            return

        if self._view == _VIEW_SETUP:
            self._on_setup_submit(text)
            return

        if self._view == _VIEW_CREATE:
            self._on_create_submit(text)
            return

        if self._view == _VIEW_CHAT:
            # Settings Tab: 仅允许修改 API Key
            if self._menu_tab == "settings":
                if self._settings_cursor == 0:
                    key = text.strip()
                    self._save_api_key(key)
                    if self._service:
                        self._service.set_api_key(key)
                        self._log(f"{M_DIM}>>> API Key 已更新{M_END}")
                        asyncio.create_task(self._check_key(key))
                    self._wants_insert = False
                    self.hide_input_bar()
                return

            # Gift Tab 不接受文本输入
            if self._menu_tab == "gift":
                return

            if not self._service or not self._service.api_key:
                self._log(f"{M_DIM}>>> 请先设置 API Key{M_END}")
                return
            if self._streaming:
                return

            if self._menu_tab == "action":
                asyncio.create_task(self._do_action(text))
            else:
                if self._state_mgr:
                    self._state_mgr.ai_chat.add_user_message(text)
                asyncio.create_task(self._stream_reply(text))

    # ── 退出清理 ──

    def on_unmount(self):
        self._panel_active = False
        if self._service:
            self._service.on_exit()
        self._upload_ai_sync()
