"""AIChatPanel — AI 伙伴面板（角色选择 → 创建 → 聊天 + 菜单）"""

from __future__ import annotations

import asyncio
import re

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import M_DIM, M_END, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY, COLOR_BORDER_LIGHT, COLOR_ACCENT
from ..state import ModuleStateManager
from ..widgets.input_bar import InputBar
from ..widgets import _set_pane_subtitle

# ── 视图常量 ──
_VIEW_SETUP  = "setup"
_VIEW_SELECT = "select"
_VIEW_CREATE = "create"
_VIEW_CHAT   = "chat"

# ── 菜单 Tab ──
_TABS = ["chat", "gift", "action", "settings"]
_TAB_LABELS = {"chat": "聊天", "gift": "赠送", "action": "互动", "settings": "设置"}


# ── 确认短语 ──
_CONFIRM_PHRASES = {"确定", "确认", "ok", "好", "好的", "可以", "没问题", "保存"}

_MAX_MODEL_VISIBLE = 8  # 模型列表最大可见行数


class AIChatPanel(Widget):
    """AI 面板：选择角色 → 创建角色 → 聊天（菜单 + 状态栏）"""

    class RequestInsert(Message):
        """面板请求 Screen 进入 INSERT 模式"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._service = None
        self._streaming = False
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

        # CHAT 视图
        self._menu_tab: str = "chat"
        self._gift_items: list[dict] = []
        self._gift_cursor: int = 0
        self._gift_qty: int = 0         # 0=未选中, >0=选择数量中
        self._settings_cursor: int = 0
        self._model_picking: bool = False  # 设置中选模型

    def compose(self) -> ComposeResult:
        yield Static(id="ai-panel-content", markup=True)
        yield Static(id="ai-chat-header", markup=True)
        yield RichLog(
            id="ai-chat-log", wrap=True, highlight=True,
            markup=True, max_lines=500,
        )
        yield InputBar(prompt_id="ai-prompt", id="ai-input-bar")

    def on_mount(self) -> None:
        try:
            self.query_one("#ai-chat-log", RichLog).display = False
            self.query_one("#ai-chat-header", Static).display = False
        except Exception:
            pass

    # ── InputBar 标准接口 ──

    def show_prompt(self, text: str = ""):
        try:
            self.query_one("#ai-input-bar", InputBar).show_prompt(text)
        except Exception:
            pass

    def update_prompt(self, text: str):
        try:
            self.query_one("#ai-input-bar", InputBar).update_prompt(text)
        except Exception:
            pass

    def hide_prompt(self):
        try:
            self.query_one("#ai-input-bar", InputBar).hide_prompt()
        except Exception:
            pass

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

    def hide_input_bar(self):
        try:
            self.query_one("#ai-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    def cancel_input(self):
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
                self.query_one("#ai-panel-content", Static).scroll_down(animate=False)
            except Exception:
                pass
        elif self._view == _VIEW_CHAT:
            if self._menu_tab == "gift":
                if self._gift_qty > 0:
                    # 数量选择模式：减少数量
                    self._gift_qty = max(1, self._gift_qty - 1)
                elif self._gift_items:
                    self._gift_cursor = (self._gift_cursor + 1) % len(self._gift_items)
                self._refresh_content()
            elif self._menu_tab == "settings":
                if self._model_picking and self._setup_models:
                    self._setup_model_cursor = (self._setup_model_cursor + 1) % len(self._setup_models)
                    self._adjust_model_scroll()
                else:
                    self._settings_cursor = (self._settings_cursor + 1) % 6
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
                self.query_one("#ai-panel-content", Static).scroll_up(animate=False)
            except Exception:
                pass
        elif self._view == _VIEW_CHAT:
            if self._menu_tab == "gift":
                if self._gift_qty > 0:
                    # 数量选择模式：增加数量
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
                    self._settings_cursor = (self._settings_cursor - 1) % 6
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
            if self._service:
                self._service.unload_character()
            self._set_view(_VIEW_SELECT)
            self._refresh_char_list()
            self._refresh_content()
            self._show_static()
            return True
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
        if self._view != _VIEW_SELECT:
            if self._service:
                self._service.unload_character()
            self._set_view(_VIEW_SELECT)
            self._refresh_char_list()
            self._refresh_content()
            self._show_static()
            return True
        return False

    # Tab 切换：在 CHAT 视图中用 h/l 切换 Tab
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

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == "add_user":
            (text,) = args
            self._log(f"[b]你>[/b] {text}")
        elif event == "add_ai":
            (text,) = args
            self._log_ai(text)

    def _on_service_event(self, event: str, *args):
        if event == "token_update":
            (display,) = args
            _set_pane_subtitle(self, f"tokens: {display}")
        elif event == "status_update":
            if self._view == _VIEW_CHAT:
                self._refresh_content()

    def _log(self, markup: str):
        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            log.write(RichText.from_markup(markup, overflow="fold"))
            log.scroll_end(animate=False)
        except Exception:
            pass

    _ACTION_RE = re.compile(r'\*([^*]+)\*')

    def _log_ai(self, text: str):
        """记录 AI 回复，*动作* 独立行无前缀，说话行带 name> 前缀"""
        label = self._char_label
        last = 0
        for m in self._ACTION_RE.finditer(text):
            speech = text[last:m.start()].strip()
            if speech:
                self._log(f"[{COLOR_FG_SECONDARY}]{label}>[/] {speech}")
            self._log(f"[italic {COLOR_FG_TERTIARY}]*{m.group(1)}*[/]")
            last = m.end()
        tail = text[last:].strip()
        if tail:
            self._log(f"[{COLOR_FG_SECONDARY}]{label}>[/] {tail}")
        if not text.strip():
            self._log(f"[{COLOR_FG_SECONDARY}]{label}>[/] {text}")

    @property
    def _char_label(self) -> str:
        if self._service and self._service.character:
            return self._service.character.name or "?"
        return "?"

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

    # ── SELECT 视图 ──

    def _refresh_char_list(self):
        from ..ai.character import list_characters
        self._char_list = list_characters()

    def _on_select_enter(self):
        total = len(self._char_list)
        if self._select_cursor < total:
            # 选择已有角色
            char = self._char_list[self._select_cursor]
            self._enter_character(char.id)
        else:
            # 创建新角色 — 直接描述（API key 已在 SETUP 阶段设置）
            self._set_view(_VIEW_CREATE)
            self._create_step = "desc"
            self._create_desc = ""
            self._create_char = None
            self._create_status = ""
            self._wants_insert = True
            self._refresh_content()

    def _enter_character(self, char_id: str):
        """进入角色聊天"""
        self._ensure_service()
        if not self._service:
            return
        self._service.load_character(char_id)

        if self._state_mgr:
            self._state_mgr.ai_chat.current_char_id = char_id

        # 记录最后使用的角色
        from ..ai.config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["last_character_id"] = char_id
        save_global_config(cfg)

        self._set_view(_VIEW_CHAT)
        self._set_tab("chat")
        self._show_chat()

        # 初始 token 显示
        _set_pane_subtitle(self, f"tokens: {self._service.today_tokens_display}")

        # 清空并恢复聊天日志
        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            log.clear()
        except Exception:
            pass

        char_name = self._service.character.name if self._service.character else "?"
        for msg in self._service.display_recent:
            if msg["role"] == "user":
                content = msg["content"]
                if content.startswith("[玩家对你做了一个动作: "):
                    action = content[10:-1]
                    self._log(f"[{COLOR_FG_TERTIARY}]◆ {action}[/]")
                elif content.startswith("[玩家送给你"):
                    gift = content.split(": ", 1)[-1].rstrip("]")
                    self._log(f"[{COLOR_FG_TERTIARY}]◆ 赠送 {gift}[/]")
                elif content.startswith("[系统:"):
                    pass  # 不显示系统提示
                else:
                    self._log(f"[b]你>[/b] {content}")
            elif msg["role"] == "assistant":
                self._log_ai(msg['content'])

        self._refresh_content()

        # 验证 API key
        if not self._service.api_key:
            self._log(f"{M_DIM}>>> 请设置 API Key（在设置 Tab 中）{M_END}")
        elif not self._service._recent:
            asyncio.create_task(self._auto_validate())

    # ── 全局 API Key ──

    def _get_api_key(self) -> str:
        from ..ai.config import load_global_config
        return load_global_config().get("api_key", "")

    def _save_api_key(self, key: str):
        from ..ai.config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["api_key"] = key
        save_global_config(cfg)

    # ── SETUP 视图（首次设置 API Key + 选模型） ──

    def _on_setup_submit(self, text: str):
        if not text.strip():
            return
        if self._setup_step == "api_key":
            key = text.strip()
            self._setup_key = key
            self._create_status = "验证 API Key 中..."
            self._wants_insert = False
            self._refresh_content()
            asyncio.create_task(self._do_setup_validate(key))

    def _on_setup_model_enter(self):
        """在 SETUP model 步骤按 Enter 确认选择"""
        if not self._setup_models:
            return
        chosen = self._setup_models[self._setup_model_cursor]
        self._save_api_key(self._setup_key)
        # 保存模型到全局配置
        from ..ai.config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["model"] = chosen["name"]
        save_global_config(cfg)
        self._create_status = ""
        self._set_view(_VIEW_SELECT)
        self._refresh_char_list()
        self._refresh_content()
        self._show_static()

    async def _do_setup_validate(self, key: str):
        """验证 API Key → 成功则列出可用模型"""
        self._ensure_service()
        if not self._service:
            self._create_status = "AI 服务初始化失败"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())
            return
        ok, err = await self._service.validate_key(key)
        if self._view != _VIEW_SETUP:
            return
        if ok:
            self._create_status = "正在获取可用模型..."
            self._refresh_content()
            try:
                from ..ai.service import AIService
                models = await AIService.list_models(key)
                if self._view != _VIEW_SETUP:
                    return
                self._setup_models = models
                self._setup_model_cursor = 0
                self._model_scroll_offset = 0
                # 默认选中 gemini-2.5-flash（如果存在）
                for i, m in enumerate(models):
                    if m["name"] == "gemini-2.5-flash":
                        self._setup_model_cursor = i
                        break
                self._adjust_model_scroll()
                self._setup_step = "model"
                self._create_status = ""
                self._wants_insert = False
                self._refresh_content()
            except Exception as e:
                self._create_status = f"获取模型列表失败: {e}"
                self._wants_insert = True
                self._refresh_content()
                self.post_message(self.RequestInsert())
        else:
            short = err[:80] + "..." if len(err) > 80 else err
            self._create_status = f"Key 无效: {short}" if short else "Key 无效"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    # ── CREATE 视图 ──

    def _on_create_submit(self, text: str):
        if not text.strip():
            return
        text = text.strip()
        if self._create_step == "desc":
            self._create_desc = text
            self._create_status = "正在整理角色信息..."
            self._wants_insert = False
            self._refresh_content()
            asyncio.create_task(self._do_structurize())
        elif self._create_step == "review":
            if text.lower() in _CONFIRM_PHRASES:
                self._create_status = "保存中..."
                self._wants_insert = False
                self._refresh_content()
                asyncio.create_task(self._do_save_char())
            else:
                self._create_status = "AI 正在调整..."
                self._wants_insert = False
                self._refresh_content()
                asyncio.create_task(self._do_refine(text))

    async def _do_structurize(self):
        """调用 AI 结构化描述 → 进入确认步骤"""
        try:
            from ..ai.character import structurize_description
            char = await structurize_description(
                self._create_desc, self._get_api_key()
            )
            if self._view != _VIEW_CREATE:
                return
            self._create_char = char
            self._create_step = "review"
            self._create_status = ""
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())
        except ValueError as e:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = str(e)
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())
        except Exception as e:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = "整理失败，请重新描述或精简描述后再试"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    async def _do_refine(self, feedback: str):
        """调用 AI 微调角色 → 更新确认视图"""
        try:
            from ..ai.character import refine_character
            self._create_char = await refine_character(
                self._create_char, feedback, self._get_api_key()
            )
            if self._view != _VIEW_CREATE:
                return
            self._create_status = ""
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())
        except ValueError as e:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = str(e)
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())
        except Exception as e:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = "调整失败，请换个方式描述修改意见"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    async def _do_save_char(self):
        """保存角色并进入聊天"""
        try:
            from ..ai.character import save_character
            from ..ai.config import save_api_config
            char = self._create_char
            save_character(char)
            save_api_config(char.id, {"api_key": self._get_api_key()})
            self._refresh_char_list()
            self._enter_character(char.id)
        except Exception as e:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = "保存失败，请重试"
            self._create_step = "review"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    # ── CHAT 视图子操作 ──

    async def _do_action(self, text: str):
        if self._streaming:
            return
        self._streaming = True
        self._log(f"[{COLOR_FG_TERTIARY}]◆ {text}[/]")
        full_reply = ""
        try:
            async for chunk in self._service.do_action(text):
                full_reply += chunk
        except Exception as e:
            self._log(f"{M_DIM}>>> 出错: {e}{M_END}")
        finally:
            self._streaming = False
            if full_reply:
                self._log_ai(full_reply)

    def _on_gift_enter(self):
        if not self._gift_items or not self._service:
            return
        item = self._gift_items[self._gift_cursor]
        if self._gift_qty == 0:
            # 进入数量选择
            self._gift_qty = 1
            self._refresh_content()
        else:
            # 确认赠送
            qty = self._gift_qty
            self._gift_qty = 0
            asyncio.create_task(self._do_gift(item, qty))

    async def _do_gift(self, item: dict, qty: int = 1):
        if self._streaming:
            return
        self._streaming = True
        name = item.get("name", "?")
        label = f"{name} x{qty}" if qty > 1 else name
        self._log(f"[{COLOR_FG_TERTIARY}]◆ 赠送 {label}[/]")
        full_reply = ""
        try:
            async for chunk in self._service.give_gift(name, qty):
                full_reply += chunk
        except Exception as e:
            self._log(f"{M_DIM}>>> 出错: {e}{M_END}")
        finally:
            self._streaming = False
            if full_reply:
                self._log_ai(full_reply)

    def _on_settings_enter(self):
        if self._model_picking:
            # 确认模型选择
            if self._setup_models:
                chosen = self._setup_models[self._setup_model_cursor]
                from ..ai.config import load_global_config, save_global_config
                cfg = load_global_config()
                cfg["model"] = chosen["name"]
                save_global_config(cfg)
                self._log(f"{M_DIM}>>> 模型已切换为 {chosen['display']}{M_END}")
            self._model_picking = False
            self._refresh_content()
            return
        idx = self._settings_cursor
        if idx == 0:
            # 设置 API Key
            self._wants_insert = True
            self.show_input_bar()
            self._log(f"{M_DIM}>>> 输入新的 API Key{M_END}")
        elif idx == 1:
            # 切换模型
            self._create_status = "正在获取可用模型..."
            self._refresh_content()
            asyncio.create_task(self._do_fetch_models_for_settings())
        elif idx == 2:
            # 切换自动启动
            from ..ai.config import load_global_config, save_global_config
            cfg = load_global_config()
            cfg["auto_start"] = not cfg.get("auto_start", False)
            save_global_config(cfg)
            self._refresh_content()
        elif idx == 3:
            # 切换注意力等级
            from ..ai.config import load_global_config, save_global_config
            cfg = load_global_config()
            levels = ["quiet", "normal", "talkative"]
            cur = cfg.get("attention_level", "normal")
            nxt = levels[(levels.index(cur) + 1) % 3] if cur in levels else "normal"
            cfg["attention_level"] = nxt
            save_global_config(cfg)
            self._refresh_content()
        elif idx == 4:
            # 清空聊天显示
            try:
                log: RichLog = self.query_one("#ai-chat-log", RichLog)
                log.clear()
            except Exception:
                pass
            if self._service:
                self._service.clear_display()
        elif idx == 5:
            # 删除角色
            if self._service and self._service.char_id:
                from ..ai.config import delete_character
                cid = self._service.char_id
                self._service.unload_character()
                delete_character(cid)
                self._log(f"{M_DIM}>>> 角色已删除{M_END}")
                self._set_view(_VIEW_SELECT)
                self._refresh_char_list()
                self._show_static()
                self._refresh_content()

    async def _do_fetch_models_for_settings(self):
        """获取模型列表用于设置中切换"""
        try:
            from ..ai.service import AIService
            key = self._get_api_key()
            models = await AIService.list_models(key)
            if self._view != _VIEW_CHAT or self._menu_tab != "settings":
                return
            self._setup_models = models
            self._setup_model_cursor = 0
            self._model_scroll_offset = 0
            # 选中当前模型
            from ..ai.config import load_global_config
            current = load_global_config().get("model", "gemini-2.5-flash")
            for i, m in enumerate(models):
                if m["name"] == current:
                    self._setup_model_cursor = i
                    break
            self._adjust_model_scroll()
            self._model_picking = True
            self._create_status = ""
            self._refresh_content()
        except Exception as e:
            self._create_status = ""
            self._log(f"{M_DIM}>>> 获取模型列表失败: {e}{M_END}")
            self._refresh_content()

    # ── 初始化 & 恢复 ──

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.ai_chat
        st.set_listener(self._on_state_event)

        self._refresh_char_list()

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
        if st.current_char_id and st.view == _VIEW_CHAT:
            self._enter_character(st.current_char_id)
        else:
            # 尝试自动启动
            last_id = cfg.get("last_character_id", "")
            if cfg.get("auto_start", False) and last_id:
                if any(c.id == last_id for c in self._char_list):
                    self._enter_character(last_id)
                    return
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
            if self._menu_tab == "settings" and self._settings_cursor == 0:
                # API key 输入 — 更新全局 + 角色级
                key = text.strip()
                self._save_api_key(key)
                if self._service:
                    self._service.set_api_key(key)
                    self._log(f"{M_DIM}>>> API Key 已更新{M_END}")
                    asyncio.create_task(self._check_key(key))
                self._wants_insert = False
                self.hide_input_bar()
                return

            if not self._service or not self._service.api_key:
                self._log(f"{M_DIM}>>> 请先设置 API Key{M_END}")
                return
            if self._streaming:
                return

            if self._menu_tab == "action":
                # 互动模式：输入作为动作
                asyncio.create_task(self._do_action(text))
            else:
                # 聊天模式
                if self._state_mgr:
                    self._state_mgr.ai_chat.add_user_message(text)
                asyncio.create_task(self._stream_reply(text))

    async def _auto_validate(self):
        self._log(f"{M_DIM}>>> 验证 API Key...{M_END}")
        try:
            ok, err = await self._service.validate_key(self._service.api_key)
            if ok:
                await self._greet()
            else:
                self._service.clear_api_key()
                self._log(f"{M_DIM}>>> Key 已失效: {err}{M_END}" if err
                          else f"{M_DIM}>>> Key 已失效{M_END}")
        except Exception as e:
            self._service.clear_api_key()
            self._log(f"{M_DIM}>>> 验证失败: {e}{M_END}")

    async def _check_key(self, key: str):
        self._log(f"{M_DIM}>>> 验证中...{M_END}")
        try:
            ok, err = await self._service.validate_key(key)
            if ok:
                self._log(f"{M_DIM}>>> 验证成功{M_END}")
                await self._greet()
            else:
                self._service.clear_api_key()
                self._log(f"{M_DIM}>>> Key 无效: {err}{M_END}" if err
                          else f"{M_DIM}>>> Key 无效{M_END}")
        except Exception as e:
            self._service.clear_api_key()
            self._log(f"{M_DIM}>>> 验证失败: {e}{M_END}")

    async def _greet(self):
        if self._streaming or not self._service:
            return
        self._streaming = True
        full_reply = ""
        try:
            async for chunk in self._service.proactive_chat("玩家刚打开聊天窗口"):
                full_reply += chunk
        except Exception:
            pass
        finally:
            self._streaming = False
            if full_reply:
                if self._state_mgr:
                    self._state_mgr.ai_chat.add_ai_message(full_reply)
                else:
                    self._log_ai(full_reply)

    async def _stream_reply(self, text: str):
        self._streaming = True
        full_reply = ""
        try:
            async for chunk in self._service.chat(text):
                full_reply += chunk
        except Exception as e:
            self._log(f"{M_DIM}>>> 出错: {e}{M_END}")
        finally:
            self._streaming = False
            if full_reply:
                if self._state_mgr:
                    self._state_mgr.ai_chat.add_ai_message(full_reply)
                else:
                    self._log_ai(full_reply)

    # ── 主动搭话 ──

    async def handle_proactive(self, reason: str):
        if self._streaming or not self._service or not self._service.api_key:
            return
        self._streaming = True
        full_reply = ""
        try:
            async for chunk in self._service.proactive_chat(reason):
                full_reply += chunk
        except Exception:
            pass
        finally:
            self._streaming = False
            if full_reply:
                if self._state_mgr:
                    self._state_mgr.ai_chat.add_ai_message(full_reply)
                else:
                    self._log_ai(full_reply)

    # ── 滚动辅助 ──

    def _adjust_model_scroll(self):
        """保持 cursor 在可见窗口内"""
        total = len(self._setup_models)
        if total <= _MAX_MODEL_VISIBLE:
            self._model_scroll_offset = 0
            return
        if self._setup_model_cursor < self._model_scroll_offset:
            self._model_scroll_offset = self._setup_model_cursor
        elif self._setup_model_cursor >= self._model_scroll_offset + _MAX_MODEL_VISIBLE:
            self._model_scroll_offset = self._setup_model_cursor - _MAX_MODEL_VISIBLE + 1
        self._model_scroll_offset = max(0, min(self._model_scroll_offset, total - _MAX_MODEL_VISIBLE))

    def _render_model_list(self) -> list[str]:
        """渲染带滚动条的模型列表（SETUP 和设置共用）"""
        if not self._setup_models:
            return [f"{M_DIM}无可用模型{M_END}"]
        total = len(self._setup_models)
        offset = self._model_scroll_offset
        visible = self._setup_models[offset:offset + _MAX_MODEL_VISIBLE]

        need_sb = total > _MAX_MODEL_VISIBLE
        if need_sb:
            max_off = max(1, total - _MAX_MODEL_VISIBLE)
            thumb_size = max(1, round(len(visible) / total * len(visible)))
            track_space = len(visible) - thumb_size
            thumb_start = round(offset / max_off * track_space) if track_space > 0 else 0

        lines = []
        for vi, m in enumerate(visible):
            real_idx = offset + vi
            display = m["display"]
            info = m.get("info", "")
            selected = real_idx == self._setup_model_cursor
            if selected:
                marker = f"[{COLOR_ACCENT}]●[/]"
                text = f"[b]{display}[/b]"
            else:
                marker = " "
                text = f"[{COLOR_FG_SECONDARY}]{display}{M_END}"
            line = f" {marker} {text}"
            if selected and info:
                line += f"  [{COLOR_FG_TERTIARY}]{info}{M_END}"
            if need_sb:
                if thumb_start <= vi < thumb_start + thumb_size:
                    line += f" [{COLOR_ACCENT}]█{M_END}"
                else:
                    line += f" [{COLOR_FG_TERTIARY}]│{M_END}"
            lines.append(line)
        return lines

    # ── 内容渲染 ──

    def _refresh_content(self):
        """根据视图刷新 Static 面板内容或状态栏"""
        if self._view == _VIEW_SETUP:
            self._render_setup()
        elif self._view == _VIEW_SELECT:
            self._render_select()
        elif self._view == _VIEW_CREATE:
            self._render_create()
        elif self._view == _VIEW_CHAT:
            self._render_chat_overlay()

    def _render_setup(self):
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
        except Exception:
            return

        lines = [
            f"[b]初始设置[/b]",
            f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}",
        ]
        if self._setup_step == "api_key":
            lines.append(f"[{COLOR_FG_SECONDARY}]步骤 1/2 — 输入 Gemini API Key{M_END}")
            lines.append(f"[{COLOR_FG_TERTIARY}]获取: https://aistudio.google.com/app/apikey{M_END}")
            lines.append("")
            lines.append(f"[{COLOR_FG_TERTIARY}]请输入你的 API Key:{M_END}")
        elif self._setup_step == "model":
            lines.append(f"[{COLOR_FG_SECONDARY}]步骤 2/2 — 选择模型{M_END}")
            lines.append("")
            lines.extend(self._render_model_list())
            lines.append("")
            lines.append(f"[{COLOR_FG_TERTIARY}]j/k 导航  Enter 确认{M_END}")
        if self._create_status:
            lines.append("")
            lines.append(f"{M_DIM}{self._create_status}{M_END}")
        content.update("\n".join(lines))

    def _render_select(self):
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
        except Exception:
            return

        lines = [
            f"[b]AI 伙伴[/b]",
            f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}",
        ]

        for i, ch in enumerate(self._char_list):
            if i == self._select_cursor:
                lines.append(f" [{COLOR_ACCENT}]●[/] [b]{ch.name}[/b]")
            else:
                lines.append(f"   [{COLOR_FG_SECONDARY}]{ch.name}{M_END}")

        # 最后一项：创建新角色
        new_idx = len(self._char_list)
        if self._select_cursor == new_idx:
            lines.append(f" [{COLOR_ACCENT}]●[/] [b]+ 创建新角色[/b]")
        else:
            lines.append(f"   [{COLOR_FG_TERTIARY}]+ 创建新角色{M_END}")

        lines.append("")
        lines.append(f"[{COLOR_FG_TERTIARY}]j/k 导航  Enter 选择{M_END}")
        content.update("\n".join(lines))

    def _render_create(self):
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
        except Exception:
            return

        lines = [
            f"[b]创建新角色[/b]",
            f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}",
        ]
        if self._create_step == "desc":
            lines.append(f"[{COLOR_FG_SECONDARY}]步骤 1/2 — 描述你的 AI 伙伴{M_END}")
            lines.append(f"[{COLOR_FG_TERTIARY}]名字、性格、说话风格、外貌、背景等{M_END}")
            lines.append(f"[{COLOR_FG_TERTIARY}]随意描述即可，AI 会自动整理{M_END}")
        elif self._create_step == "review":
            lines.append(f"[{COLOR_FG_SECONDARY}]步骤 2/2 — 确认角色信息{M_END}")
            lines.append(f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}")
            if self._create_char:
                c = self._create_char
                lines.append(f"[b]名字:[/b] {c.name}")
                lines.append(f"[b]性格:[/b] {c.personality}")
                lines.append(f"[b]说话风格:[/b] {c.speech_style}")
                lines.append(f"[b]外貌:[/b] {c.appearance}")
                lines.append(f"[b]背景:[/b] {c.backstory}")
                if c.custom_rules:
                    lines.append(f"[b]特殊规则:[/b]")
                    for rule in c.custom_rules:
                        lines.append(f"  - {rule}")
            lines.append("")
            lines.append(f"[{COLOR_FG_TERTIARY}]输入修改意见，或输入「确定」保存{M_END}")
        if self._create_status:
            lines.append("")
            lines.append(f"{M_DIM}{self._create_status}{M_END}")
        content.update("\n".join(lines))

    def _render_header(self):
        """渲染常驻顶栏：Tab 栏 + 角色状态"""
        # Tab 栏
        parts = []
        for t in _TABS:
            label = _TAB_LABELS[t]
            if t == self._menu_tab:
                parts.append(f"[{COLOR_ACCENT}]●[/] [b]{label}[/b]")
            else:
                parts.append(f"  [{COLOR_FG_TERTIARY}]{label}{M_END}")
        tab_line = " ".join(parts)

        # 状态行
        if self._service:
            mood_label, _, _ = self._service.mood.to_display()
            sd = self._service.social.to_display()
            status_line = (f"{mood_label} [{COLOR_FG_TERTIARY}]|{M_END} "
                          f"亲:{sd['intimacy']} 信:{sd['trust']} 熟:{sd['familiarity']} "
                          f"[{COLOR_FG_TERTIARY}]|{M_END} {sd['stage']}")
        else:
            status_line = ""

        try:
            header = self.query_one("#ai-chat-header", Static)
            header.update(f"{tab_line}\n{status_line}")
            header.display = True
        except Exception:
            pass

    def _render_chat_overlay(self):
        """渲染聊天视图的顶栏 + 菜单内容"""
        self._render_header()

        # chat / action tab → RichLog，其余 → Static
        if self._menu_tab in ("chat", "action"):
            self._show_chat()
        else:
            self._show_menu_content()

    def _show_menu_content(self):
        """非聊天 Tab 的内容渲染到 Static"""
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
            content.display = True
            self.query_one("#ai-chat-log", RichLog).display = False
        except Exception:
            return
        self.hide_input_bar()

        lines: list[str] = []

        if self._menu_tab == "gift":
            lines.extend(self._render_gift_list())
        elif self._menu_tab == "settings":
            lines.extend(self._render_settings())

        content.update("\n".join(lines))

    def _render_gift_list(self) -> list[str]:
        # 从 inventory state 获取物品
        self._sync_gift_items()
        lines = []
        if not self._gift_items:
            lines.append(f"[{COLOR_FG_TERTIARY}](背包空空如也){M_END}")
            return lines
        for i, item in enumerate(self._gift_items):
            name = item.get("name", "?")
            count = item.get("count", 0)
            selected = i == self._gift_cursor
            if selected and self._gift_qty > 0:
                # 数量选择模式
                lines.append(f" [{COLOR_ACCENT}]●[/] [b]{name} x{count}[/b]")
                lines.append(f"   赠送数量: [{COLOR_ACCENT}]{self._gift_qty}[/]")
                lines.append(f"   [{COLOR_FG_TERTIARY}]j/k 调整  Enter 确定  Esc 取消{M_END}")
            elif selected:
                lines.append(f" [{COLOR_ACCENT}]●[/] [b]{name} x{count}[/b]")
            else:
                lines.append(f"   [{COLOR_FG_SECONDARY}]{name} x{count}{M_END}")
        return lines

    def _render_settings(self) -> list[str]:
        if self._model_picking:
            return self._render_model_pick()
        from ..ai.config import load_global_config
        cfg = load_global_config()
        auto_start = cfg.get("auto_start", False)
        auto_label = "开启" if auto_start else "关闭"
        current_model = cfg.get("model", "gemini-2.5-flash")
        attn = cfg.get("attention_level", "normal")
        attn_labels = {"quiet": "安静", "normal": "普通", "talkative": "话多"}
        attn_label = attn_labels.get(attn, attn)

        settings_items = [
            f"修改 API Key",
            f"切换模型: {current_model}",
            f"自动启动: {auto_label}",
            f"注意力: {attn_label}",
            f"清空聊天记录",
            f"删除此角色",
        ]
        lines = []
        for i, label in enumerate(settings_items):
            if i == self._settings_cursor:
                lines.append(f" [{COLOR_ACCENT}]●[/] [b]{label}[/b]")
            else:
                lines.append(f"   [{COLOR_FG_SECONDARY}]{label}{M_END}")
        if self._create_status:
            lines.append("")
            lines.append(f"{M_DIM}{self._create_status}{M_END}")
        return lines

    def _render_model_pick(self) -> list[str]:
        """渲染模型选择列表（设置中切换模型）"""
        lines = [f"[{COLOR_FG_SECONDARY}]选择模型:{M_END}", ""]
        lines.extend(self._render_model_list())
        lines.append("")
        lines.append(f"[{COLOR_FG_TERTIARY}]j/k 导航  Enter 确认  Esc 取消{M_END}")
        return lines

    def _sync_gift_items(self):
        """从 state 同步物品列表"""
        if not self._state_mgr:
            self._gift_items = []
            return
        items = getattr(self._state_mgr.inventory, 'items', [])
        self._gift_items = [
            {"id": it.get("id", ""), "name": it.get("name", "?"), "count": it.get("count", 0)}
            for it in items
            if it.get("count", 0) > 0
        ]

    # ── 退出清理 ──

    def on_unmount(self):
        if self._service:
            self._service.on_exit()
