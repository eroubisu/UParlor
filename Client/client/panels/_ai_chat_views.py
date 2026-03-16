"""AI 面板 — 视图业务逻辑 (mixin for AIChatPanel)"""

from __future__ import annotations

import asyncio

from textual.widgets import RichLog

from ..config import M_DIM, M_END, COLOR_FG_TERTIARY
from ..widgets import _set_pane_subtitle

# 视图常量（ai_chat.py 共用）
_VIEW_SETUP  = "setup"
_VIEW_SELECT = "select"
_VIEW_CREATE = "create"
_VIEW_CHAT   = "chat"

_CONFIRM_PHRASES = {"确定", "确认", "ok", "好", "好的", "可以", "没问题", "保存"}


class _ChatViewsMixin:
    """AIChatPanel 的视图操作方法集"""

    # ── 流式通用 ──

    async def _run_streaming(self, stream, *, log_error: bool = True) -> str:
        """执行流式对话通用模式，返回完整回复（出错返回空串）

        等待 AI 响应时显示…思考指示器，首个流式块到达时自动替换。
        正常完成时保留流式输出作为最终显示。
        """
        self._streaming = True
        try:
            log = self.query_one("#ai-chat-log", RichLog)
            self._stream_baseline = len(log.lines)
        except Exception:
            self._stream_baseline = 0
        # 思考指示器（在 baseline 之后，会被 _log_streaming 替换）
        self._log(f"[{COLOR_FG_TERTIARY}]…[/]")
        full_reply = ""
        try:
            async for chunk in stream:
                if not self._panel_active:
                    break
                full_reply += chunk
                self._log_streaming(full_reply)
        except Exception as e:
            self._end_streaming_line()
            if log_error:
                self._log(f"{M_DIM}>>> 出错: {e}{M_END}")
            full_reply = ""
        finally:
            self._streaming = False
            if not full_reply:
                self._end_streaming_line()
        return full_reply

    def _save_ai_reply(self, reply: str):
        """将 AI 回复保存到状态（流式已显示，不重复输出）"""
        if self._state_mgr:
            self._state_mgr.ai_chat.messages.append(
                {"role": "assistant", "content": reply}
            )
            if not self._is_panel_focused():
                self._has_unread = True
                self._update_unread_marker()
        else:
            self._log_ai(reply)

    # ── API Key ──

    def _get_api_key(self) -> str:
        from ..ai.config import load_global_config
        return load_global_config().get("api_key", "")

    def _save_api_key(self, key: str):
        from ..ai.config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["api_key"] = key
        save_global_config(cfg)

    # ── SELECT 视图 ──

    def _refresh_char_list(self):
        from ..ai.character import list_characters
        self._char_list = list_characters()

    def _on_select_enter(self):
        total = len(self._char_list)
        if self._select_cursor < total:
            char = self._char_list[self._select_cursor]
            self._enter_character(char.id)
        else:
            self._set_view(_VIEW_CREATE)
            self._create_step = "desc"
            self._create_desc = ""
            self._create_char = None
            self._create_status = ""
            self._create_tokens = 0
            self._wants_insert = True
            self._refresh_content()

    def _enter_character(self, char_id: str):
        """进入角色聊天"""
        self._ensure_service()
        if not self._service:
            return
        self._service.load_character(char_id)
        self._service.set_sync_callback(self._upload_ai_sync)

        if self._state_mgr:
            self._state_mgr.ai_chat.current_char_id = char_id

        from ..ai.config import load_global_config, save_global_config
        cfg = load_global_config()
        cfg["last_character_id"] = char_id
        save_global_config(cfg)

        self._set_view(_VIEW_CHAT)
        self._set_tab("chat")
        self._show_chat()

        _set_pane_subtitle(self, f"tokens: {self._service.today_tokens_display}")

        try:
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            log.clear()
        except Exception:
            pass

        for msg in self._service.display_recent:
            if msg["role"] == "user":
                content = msg["content"]
                if content.startswith("[玩家对你做了一个动作: "):
                    action = content.split(": ", 1)[-1].rstrip("]")
                    self._log(f"[{COLOR_FG_TERTIARY}]◆ {action}[/]")
                elif content.startswith("[玩家送给你"):
                    gift = content.split(": ", 1)[-1].rstrip("]")
                    self._log(f"[{COLOR_FG_TERTIARY}]◆ 赠送 {gift}[/]")
                elif content.startswith("[系统:"):
                    pass
                else:
                    self._log(f"你> {content}")
            elif msg["role"] == "assistant":
                self._log_ai(msg['content'])

        self._refresh_content()

        if not self._service.api_key:
            self._log(f"{M_DIM}>>> 请设置 API Key（在设置 Tab 中）{M_END}")
        elif not self._service._recent:
            asyncio.create_task(self._auto_validate())

    # ── SETUP 视图 ──

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
            self._save_api_key(key)
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
            char, tokens = await structurize_description(
                self._create_desc, self._get_api_key()
            )
            if self._view != _VIEW_CREATE:
                return
            self._create_char = char
            self._create_tokens += tokens
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
        except Exception:
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
            self._create_char, tokens = await refine_character(
                self._create_char, feedback, self._get_api_key()
            )
            self._create_tokens += tokens
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
        except Exception:
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
            creation_tokens = self._create_tokens
            self._create_tokens = 0
            self._enter_character(char.id)
            if creation_tokens and self._service:
                self._service._add_tokens(creation_tokens)
                _set_pane_subtitle(self, f"tokens: {self._service.today_tokens_display}")
        except Exception:
            if self._view != _VIEW_CREATE:
                return
            self._create_status = "保存失败，请重试"
            self._create_step = "review"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    # ── CHAT 动作 ──

    async def _do_action(self, text: str):
        if self._streaming or not self._panel_active:
            return
        self._log(f"[{COLOR_FG_TERTIARY}]◆ {text}[/]")
        reply = await self._run_streaming(self._service.do_action(text))
        if reply:
            self._save_ai_reply(reply)

    def _on_gift_enter(self):
        if not self._gift_items or not self._service:
            return
        item = self._gift_items[self._gift_cursor]
        if self._gift_qty == 0:
            self._gift_qty = 1
            self._refresh_content()
        else:
            qty = self._gift_qty
            self._gift_qty = 0
            asyncio.create_task(self._do_gift(item, qty))

    async def _do_gift(self, item: dict, qty: int = 1):
        if self._streaming or not self._panel_active:
            return
        name = item.get("name", "?")
        item_id = item.get("id", "")
        label = f"{name} x{qty}" if qty > 1 else name
        # 切换到聊天视图并立即显示赠送标记
        self._set_tab("chat")
        self._show_chat()
        self._render_header()
        self._log(f"[{COLOR_FG_TERTIARY}]◆ 赠送 {label}[/]")
        # 立即扣除物品并通知服务器
        if item_id:
            for gi in self._gift_items:
                if gi["id"] == item_id:
                    gi["count"] = max(0, gi["count"] - qty)
                    break
            self._gift_items = [g for g in self._gift_items if g["count"] > 0]
            try:
                self.app.network.send({
                    "type": "ai_gift_consume",
                    "item_id": item_id,
                    "qty": qty,
                })
            except Exception:
                pass
        reply = await self._run_streaming(self._service.give_gift(name, qty))
        if reply:
            self._save_ai_reply(reply)

    def _on_settings_enter(self):
        if self._model_picking:
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
            self._wants_insert = True
            self.show_input_bar()
            self._log(f"{M_DIM}>>> 输入新的 API Key{M_END}")
        elif idx == 1:
            self._create_status = "正在获取可用模型..."
            self._refresh_content()
            asyncio.create_task(self._do_fetch_models_for_settings())
        elif idx == 2:
            from ..ai.config import load_global_config, save_global_config
            cfg = load_global_config()
            cfg["auto_start"] = not cfg.get("auto_start", False)
            save_global_config(cfg)
            self._refresh_content()
        elif idx == 3:
            from ..ai.config import load_global_config, save_global_config
            cfg = load_global_config()
            levels = ["quiet", "normal", "talkative"]
            cur = cfg.get("attention_level", "normal")
            nxt = levels[(levels.index(cur) + 1) % 3] if cur in levels else "normal"
            cfg["attention_level"] = nxt
            save_global_config(cfg)
            self._refresh_content()
        elif idx == 4:
            try:
                log: RichLog = self.query_one("#ai-chat-log", RichLog)
                log.clear()
            except Exception:
                pass
            if self._service:
                self._service.clear_display()
        elif idx == 5:
            # 重置所有记忆 — 需确认
            if self._reset_confirming:
                self._reset_confirming = False
                if self._service:
                    self._service.reset_memory()
                    try:
                        log: RichLog = self.query_one("#ai-chat-log", RichLog)
                        log.clear()
                    except Exception:
                        pass
                    self._log(f"{M_DIM}>>> 所有记忆已重置{M_END}")
            else:
                self._reset_confirming = True
        elif idx == 6:
            self._reset_confirming = False
            # 手动切回角色选择 → 取消自动启动
            from ..ai.config import load_global_config, save_global_config
            cfg = load_global_config()
            if cfg.get('auto_start', False):
                cfg['auto_start'] = False
                save_global_config(cfg)
            if self._service:
                self._service.unload_character()
            self._set_view(_VIEW_SELECT)
            self._refresh_char_list()
            self._refresh_content()
            self._show_static()
        elif idx == 7:
            self._reset_confirming = False
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

    async def _do_fetch_models_for_setup(self):
        """SETUP model 步骤恢复时重新获取模型列表"""
        try:
            from ..ai.service import AIService
            key = self._get_api_key()
            if not key:
                self._setup_step = "api_key"
                self._create_status = ""
                self._wants_insert = True
                self._refresh_content()
                self.post_message(self.RequestInsert())
                return
            models = await AIService.list_models(key)
            if self._view != _VIEW_SETUP:
                return
            self._setup_models = models
            self._setup_model_cursor = 0
            self._model_scroll_offset = 0
            for i, m in enumerate(models):
                if m["name"] == "gemini-2.5-flash":
                    self._setup_model_cursor = i
                    break
            self._adjust_model_scroll()
            self._create_status = ""
            self._refresh_content()
        except Exception as e:
            self._create_status = f"获取模型列表失败: {e}"
            self._setup_step = "api_key"
            self._wants_insert = True
            self._refresh_content()
            self.post_message(self.RequestInsert())

    # ── 流式聊天 ──

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
        if self._streaming or not self._service or not self._panel_active:
            return
        reply = await self._run_streaming(
            self._service.proactive_chat("玩家刚打开聊天窗口"),
            log_error=False,
        )
        if reply:
            self._save_ai_reply(reply)

    async def _stream_reply(self, text: str):
        if not self._panel_active:
            return
        reply = await self._run_streaming(self._service.chat(text))
        if reply:
            self._save_ai_reply(reply)

    async def handle_proactive(self, reason: str):
        if not self._panel_active:
            return
        if self._streaming or not self._service or not self._service.api_key:
            return
        reply = await self._run_streaming(
            self._service.proactive_chat(reason),
            log_error=False,
        )
        if reply:
            self._save_ai_reply(reply)

    # ── 数据同步 ──

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

    def _upload_ai_sync(self):
        """将本地 AI 角色数据上传到服务器进行同步"""
        try:
            from ..ai.config import export_all_chars
            data = export_all_chars()
            if data:
                self.app.network.send({"type": "ai_sync_up", "companions": data})
        except Exception:
            pass
