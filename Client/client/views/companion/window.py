"""Single-window AI companion chat and settings."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import datetime
from types import SimpleNamespace

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static

from ...companion import CompanionController
from ...companion import config as cfg
from ...companion.character import list_characters
from ...companion.mood import MOODS
from ...companion.provider import PROVIDER_NAMES
from ...chat_style import render_chat_groups
from ...config import (
    COLOR_FG_PRIMARY,
    COLOR_FG_TERTIARY,
    COLOR_HINT_TAB_DIM,
    ICON_INDENT,
)
from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import InputSpec, Option, WindowSpec, register_window
from ...window_engine.text import grapheme_clusters
from ...window_specs import bind_state, logged_in

def _split_action_and_speech(text: str) -> str:
    return text


_REPLY_REVEAL_INTERVAL = 0.004


def _mask_key(key: str) -> str:
    if not key:
        return "未设置"
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _configured_provider(config: dict) -> str:
    provider = config.get("provider", "gemini")
    return provider if provider in ("gemini", "deepseek") else "gemini"


def _mark_companion_seen(window, context) -> None:
    window.mark_seen(context)


class CompanionPanel(Panel):
    """Chat with, inspect, and configure a local AI companion."""

    tabs = ["对话", "设置", "状态"]
    has_input = True
    placeholder = "输入消息"
    icon_align = True

    class OpenCreation(Message):
        """Request the separate stepwise companion creation window."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._controller: CompanionController | None = None
        self._controller_generation = -1
        self._streaming = False
        self._chat_queue: deque[tuple[str, int]] = deque()
        self._reply_buffers: dict[int, str] = {}
        self._chat_worker_running = False
        self._chat_lines: list[str] = []
        self._chat_meta: list[tuple[str, str, str]] = []
        self._settings_menu = ""
        self._editing = ""
        self._pending_key = ""
        self._draft_provider = "gemini"
        self._models: list[dict] = []
        self._api_revision = 0
        self._status = ""
        self._character_action_id = ""

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Static("", classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t1"):
            yield Static("", classes="content", markup=True)
        with VerticalScroll(classes="tab", id="t2"):
            yield Static("", classes="content", markup=True)

    def _render_tabs(self) -> str:
        names = self.tabs if self._selected_character_name() else self.tabs[:2]
        parts = []
        for index, name in enumerate(names):
            style = (
                f"bold {COLOR_FG_PRIMARY}"
                if index == self._active else COLOR_HINT_TAB_DIM
            )
            parts.append(f"[{style}]{name}[/]")
        return " ".join(parts)

    def bind_controller(self, controller: CompanionController) -> None:
        if controller.generation != self._controller_generation:
            self._chat_lines.clear()
            self._chat_meta.clear()
            self._chat_queue.clear()
            self._reply_buffers.clear()
            self._chat_worker_running = False
            self._streaming = False
            self._controller_generation = controller.generation
        self._controller = controller
        self._draft_provider = _configured_provider(cfg.load_global_config())
        self._restore_chat_history()
        self.border_title = self._render_tabs()
        self._render_current_tab()

    def _add_record(self, text: str) -> None:
        if self._controller is not None:
            self._controller.add_record(text)

    def on_panel_focus(self) -> None:
        self._render_current_tab()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._settings_menu = ""
        self._cancel_edit()
        if self._active != 0:
            super().switch_tab(0)
        self._render_current_tab()

    def open_settings(self) -> None:
        self._settings_menu = ""
        self.switch_tab(1)

    def switch_tab(self, index: int) -> None:
        if self.input_session.editing:
            return
        visible_count = 3 if self._selected_character_name() else 2
        super().switch_tab(index % visible_count)
        self._settings_menu = ""
        self._render_current_tab()

    def nav(self, action: str) -> None:
        if self.input_session.editing:
            return
        if action in ("tab_prev", "tab_next"):
            super().nav(action)
            self._render_current_tab()
            return
        if self._active == 0:
            if action in ("up", "down"):
                if (
                    action == "up"
                    and self._controller
                    and self._controller.restore_visible_history()
                ):
                    self._restore_chat_history()
                    self._render_chat()
                    return
                super().nav(action)
            return
        if self._active == 2:
            if action in ("up", "down"):
                super().nav(action)
            return
        self._settings_nav(action)

    def _render_current_tab(self) -> None:
        if not self.is_mounted:
            return
        if self._active == 0:
            self._render_chat()
        elif self._active == 1:
            self._render_settings()
        else:
            self._render_status()
        self._sync_input()

    def _selected_character_name(self) -> str:
        selected = cfg.load_player_config().get("last_character_id", "")
        return next(
            (character.name for character in list_characters()
             if character.id == selected),
            "",
        )

    def _restore_chat_history(self) -> None:
        controller = self._controller
        if controller is None:
            self._chat_lines = []
            return
        history = controller.visible_history()
        self._chat_lines = [
            item["content"]
            for item in history
        ]
        self._chat_meta = [
            (
                item["role"],
                item.get("time", ""),
                str(item.get("mood", {}).get("primary", "")),
            )
            for item in history
        ]

    def _render_chat(self) -> None:
        controller = self._controller
        configured_provider = _configured_provider(cfg.load_global_config())
        self.border_subtitle = escape(self._selected_character_name())
        if not controller or not controller.player:
            text = "尚未登录。"
        elif self._draft_provider != configured_provider:
            text = "AI 服务变更尚未保存。请在“设置”中保存并验证。"
        elif self._chat_lines:
            self._flush_chat()
            return
        elif not controller.has_api_key() or not cfg.load_global_config().get("model"):
            text = "AI 服务未配置。请切换到“设置”标签完成配置。"
        elif not controller.has_character():
            text = "未选择旅伴。请切换到“设置”标签选择或创建旅伴。"
        elif not controller.is_enabled():
            text = "旅伴未启用。请在“设置”标签中启用。"
        else:
            text = ""
        self.query_one("#t0 .content", Static).update(text)

    def _render_status(self) -> None:
        self.border_subtitle = ""
        controller = self._controller
        status = controller.public_status() if controller else {}
        relationship = status.get("relationship", {})
        mood = status.get("mood", {})
        lines = [
            "关系",
            f"{ICON_INDENT}阶段       "
            f"{escape(str(relationship.get('stage', '未知')))}",
            f"{ICON_INDENT}亲密度     {relationship.get('intimacy', 0)}/100",
            f"{ICON_INDENT}信任度     {relationship.get('trust', 0)}/100",
            f"{ICON_INDENT}熟悉度     {relationship.get('familiarity', 0)}/100",
            "",
            "心情",
            f"{ICON_INDENT}当前心情   "
            f"{escape(str(mood.get('primary', '未知')))}",
            f"{ICON_INDENT}强度       {mood.get('intensity', 0)}%",
        ]
        if mood.get("secondary"):
            lines.append(
                f"{ICON_INDENT}次要心情   "
                f"{escape(str(mood['secondary']))}")
        if mood.get("source"):
            lines.append(
                f"{ICON_INDENT}原因       {escape(str(mood['source']))}")
        self.query_one("#t2 .content", Static).update(
            f"[{COLOR_FG_TERTIARY}]" + "\n".join(lines) + "[/]")

    def input_spec(self) -> InputSpec:
        controller = self._controller
        configured_provider = _configured_provider(cfg.load_global_config())
        chat_ready = bool(
            self._active == 0
            and controller
            and controller.is_enabled()
            and controller.is_ready()
            and self._draft_provider == configured_provider
        )
        editing_api = self._active == 1 and self._editing == "api_key"
        return InputSpec(
            context_id=(
                "companion:api-key" if editing_api else "companion:chat"
            ),
            placeholder="输入 API Key" if editing_api else self.placeholder,
            visible=self._active == 0 or editing_api,
            enabled=chat_ready or editing_api,
            password=editing_api,
            focus=True,
            on_cancel=self._on_input_cancelled,
        )

    def _sync_input(self) -> None:
        self.activate_input_context()

    def _on_input_cancelled(self, _draft: str) -> None:
        del _draft
        if self._editing:
            self._editing = ""
            self.call_after_refresh(self.activate_input_context)

    def can_enter_insert(self) -> bool:
        """Report whether the shared input row is actionable."""
        controller = self._controller
        configured_provider = _configured_provider(cfg.load_global_config())
        return bool(
            self._editing
            or (
                self._active == 1
                and not self._settings_menu
                and self.selected_option is not None
                and self.selected_option.id == "api_key"
            )
            or (
                self._active == 0
                and controller
                and controller.is_enabled()
                and controller.is_ready()
                and self._draft_provider == configured_provider
            )
        )

    def prepare_insert(self) -> None:
        if (
            self._active == 1
            and not self._settings_menu
            and self.selected_option is not None
            and self.selected_option.id == "api_key"
            and not self._editing
        ):
            self._editing = "api_key"
            self.activate_input_context()

    def _settings_rows(self) -> list[tuple[str, str]]:
        global_config = cfg.load_global_config()
        player_config = cfg.load_player_config()
        provider_config = cfg.provider_config(
            global_config, self._draft_provider,
        )
        key = self._pending_key or provider_config["api_key"]
        if self._pending_key:
            key_label = "待验证"
        else:
            key_label = _mask_key(key)
        model = provider_config["model"]
        character = self._selected_character_name() or "未选择"
        enabled = "开" if player_config.get("enabled", False) else "关"
        proactive = (
            "开" if player_config.get("background_proactive", True) else "关")
        return [
            ("provider", f"AI 服务        {PROVIDER_NAMES[self._draft_provider]}"),
            ("api_key", f"API Key        {key_label}"),
            ("validate", "保存并验证"),
            ("model", f"模型           {model or '未选择'}"),
            ("character", f"当前旅伴       {character}"),
            ("enabled", f"启用旅伴       {enabled}"),
            ("background", f"允许主动搭话   {proactive}"),
            ("clear_history", "清空聊天记录"),
        ]

    def _render_settings(self) -> None:
        self.border_subtitle = ""
        if self._settings_menu:
            self._render_settings_menu()
            return
        self.set_options(
            (Option(key, label) for key, label in self._settings_rows()),
            "companion-settings",
        )
        rows = [self.render_options()]
        if self._status:
            rows.extend((
                "",
                f"[{COLOR_FG_TERTIARY}]{escape(self._status)}[/]",
            ))
        self.query_one("#t1 .content", Static).update("\n".join(rows))

    def _menu_items(self) -> list[tuple[str, str]]:
        if self._settings_menu == "provider":
            return [
                ("gemini", "Gemini"),
                ("deepseek", "DeepSeek"),
                ("back", "返回"),
            ]
        if self._settings_menu == "model":
            return [
                *[(model["name"], model.get("display") or model["name"])
                  for model in self._models],
                ("back", "返回"),
            ]
        if self._settings_menu == "character":
            return [
                *[(character.id, character.name)
                  for character in list_characters()],
                ("create", "创建旅伴"),
                ("back", "返回"),
            ]
        if self._settings_menu == "character_action":
            return [
                ("select", "选择"),
                ("delete", "删除"),
                ("back", "返回"),
            ]
        if self._settings_menu == "delete_confirm":
            character = next(
                (item for item in list_characters()
                 if item.id == self._character_action_id),
                None,
            )
            name = character.name if character else "该旅伴"
            return [
                ("delete_confirmed", f"删除 {name}"),
                ("back", "取消"),
            ]
        return []

    def _render_settings_menu(self) -> None:
        items = self._menu_items()
        self.set_options(
            (Option(value, label) for value, label in items),
            f"companion-settings:{self._settings_menu}",
        )
        self.update(
            self.render_options(),
            tab=1,
            focus_line=self.selected_line(),
        )

    def _settings_nav(self, action: str) -> None:
        if self._settings_menu:
            self._settings_menu_nav(action)
            return
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._render_settings()
        elif selected is not None:
            self._activate_setting(selected.id)

    def _settings_menu_nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._render_settings_menu()
        elif selected is not None:
            self._activate_menu_item(selected.id)

    def _activate_setting(self, key: str) -> None:
        controller = self._controller
        if controller is None:
            return
        if key == "provider":
            self._open_menu("provider")
        elif key == "api_key":
            self._status = "按 i 输入 API Key。"
            self._render_settings()
        elif key == "validate":
            self._validate_pending_api()
        elif key == "model":
            self._open_model_menu()
        elif key == "character":
            self._open_menu("character")
        elif key == "enabled":
            controller.set_enabled(not controller.is_enabled())
            self._render_current_tab()
        elif key == "background":
            current = cfg.load_player_config().get(
                "background_proactive", True)
            controller.set_background_proactive(not current)
            self._render_settings()
        elif key == "clear_history":
            if controller.clear_visible_history():
                self._chat_lines.clear()
                self._chat_meta.clear()
                controller.add_record("旅伴聊天记录已清空。")
            self._render_settings()

    def _open_menu(self, menu: str) -> None:
        self._settings_menu = menu
        self._render_settings_menu()

    def _activate_menu_item(self, value: str) -> None:
        if value == "back":
            if self._settings_menu == "delete_confirm":
                self._settings_menu = "character_action"
            elif self._settings_menu == "character_action":
                self._settings_menu = "character"
            else:
                self._settings_menu = ""
            if self._settings_menu:
                self._render_settings_menu()
            else:
                self._render_settings()
            return
        if self._settings_menu == "provider":
            if value != self._draft_provider:
                self._draft_provider = value
                self._pending_key = ""
                self._models = []
                self._api_revision += 1
                saved = cfg.provider_config(
                    cfg.load_global_config(), self._draft_provider,
                )
                self._status = (
                    "已载入该服务的 API Key；请保存并验证。"
                    if saved["api_key"]
                    else "服务已切换；请输入对应 API Key。"
                )
            self._settings_menu = ""
            self._render_settings()
        elif self._settings_menu == "model":
            controller = self._controller
            if controller:
                controller.set_model(value)
            self._settings_menu = ""
            self._status = ""
            self._add_record("旅伴模型已保存。")
            self._render_settings()
        elif self._settings_menu == "character":
            if value == "create":
                self._settings_menu = ""
                self._begin_create_character()
                return
            self._character_action_id = value
            self._open_menu("character_action")
        elif self._settings_menu == "character_action":
            if value == "delete":
                self._open_menu("delete_confirm")
                return
            if value != "select":
                return
            controller = self._controller
            if controller:
                controller.load_character(self._character_action_id)
                self._restore_chat_history()
            self._settings_menu = ""
            self._status = ""
            self._add_record("当前旅伴已切换。")
            self.border_title = self._render_tabs()
            self._render_settings()
        elif self._settings_menu == "delete_confirm":
            controller = self._controller
            if controller:
                controller.delete_character(self._character_action_id)
                self._restore_chat_history()
            self._character_action_id = ""
            self._settings_menu = ""
            self._status = ""
            self._add_record("旅伴已删除。")
            self.border_title = self._render_tabs()
            self._render_settings()

    def _begin_edit(
        self, field: str, placeholder: str, *, password: bool = False,
    ) -> None:
        self._editing = field
        self.replace_input_spec(InputSpec(
            context_id=f"companion:{field}",
            placeholder=placeholder,
            visible=True,
            enabled=True,
            password=password,
            focus=True,
            on_cancel=self._on_input_cancelled,
        ))

    def _cancel_edit(self) -> None:
        self._editing = ""
        if not self.is_mounted:
            return
        self.input_session.clear()
        self._sync_input()
        self._render_current_tab()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = self.submit_input(event, clear=True).strip()
        if self._editing:
            field = self._editing
            self._editing = ""
            if field == "api_key":
                self._pending_key = text
                self._api_revision += 1
                self._status = (
                    "API Key 待验证。" if text else "未输入 API Key。")
                self._render_settings()
            self._sync_input()
            return
        if not text:
            return
        controller = self._controller
        if (
            not controller
            or not controller.is_enabled()
            or not controller.is_ready()
        ):
            self._render_chat()
            self._sync_input()
            return
        self._enqueue_chat(text)
        self._sync_input()

    def _validate_pending_api(self) -> None:
        controller = self._controller
        if controller is None:
            return
        saved = cfg.load_global_config()
        key = self._pending_key
        if not key:
            key = cfg.provider_config(
                saved, self._draft_provider,
            )["api_key"]
        if not key:
            self._status = "请先输入 API Key。"
            self._render_settings()
            return
        self._status = "正在验证 API Key。"
        self._render_settings()
        self._run_api_validation(
            self._draft_provider, key, self._api_revision)

    @work(exclusive=True, group="companion-api-validation")
    async def _run_api_validation(
        self, provider_name: str, key: str, revision: int,
    ) -> None:
        controller = self._controller
        if controller is None:
            return
        try:
            valid, error, models = await controller.validate_api(
                provider_name, key)
        except Exception as exc:
            self._finish_api_validation(
                False, str(exc), [], provider_name, key, revision)
            return
        self._finish_api_validation(
            valid, error, models, provider_name, key, revision)

    def _finish_api_validation(
        self,
        valid: bool,
        error: str,
        models: list[dict],
        provider_name: str,
        key: str,
        revision: int,
    ) -> None:
        if (
            revision != self._api_revision
            or provider_name != self._draft_provider
        ):
            return
        if not valid:
            self._status = f"验证失败：{error}"
            self._render_settings()
            return
        controller = self._controller
        if controller is None:
            return
        old_config = cfg.load_global_config()
        old_model = cfg.provider_config(
            old_config, provider_name,
        )["model"]
        names = {model["name"] for model in models}
        model = old_model if old_model in names else ""
        controller.apply_api_config(provider_name, key, model)
        self._pending_key = ""
        self._models = models
        self._status = ""
        self._add_record("旅伴 API Key 验证成功并已保存。")
        self._render_settings()

    def _open_model_menu(self) -> None:
        config = cfg.load_global_config()
        saved_provider = _configured_provider(config)
        if self._draft_provider != saved_provider or not config.get("api_key"):
            self._status = "请先保存并验证当前服务的 API Key。"
            self._render_settings()
            return
        if self._models:
            self._open_menu("model")
            return
        self._status = "正在获取模型列表。"
        self._render_settings()
        self._load_models(saved_provider, config["api_key"])

    @work(exclusive=True, group="companion-models")
    async def _load_models(self, provider_name: str, key: str) -> None:
        controller = self._controller
        if controller is None:
            return
        try:
            models = await controller.list_models(provider_name, key)
        except Exception as exc:
            if not self._model_request_is_current(provider_name, key):
                return
            self._status = f"模型列表获取失败：{exc}"
            self._render_settings()
            return
        if not self._model_request_is_current(provider_name, key):
            return
        self._models = models
        if not models:
            self._status = "未获取到可用模型。"
            self._render_settings()
            return
        self._status = ""
        self._open_menu("model")

    def _model_request_is_current(
        self, provider_name: str, key: str,
    ) -> bool:
        config = cfg.load_global_config()
        return (
            provider_name == self._draft_provider
            and provider_name == _configured_provider(config)
            and key == config.get("api_key")
        )

    def _begin_create_character(self) -> None:
        controller = self._controller
        if controller is None or not controller.has_api_key():
            self._status = "请先完成 AI 服务配置。"
            self._render_settings()
            return
        if not cfg.load_global_config().get("model"):
            self._status = "请先选择模型。"
            self._render_settings()
            return
        self.post_message(self.OpenCreation())

    def _append_user(self, text: str, *, flush: bool = True) -> None:
        self._chat_lines.append(text)
        self._chat_meta.append((
            "user", datetime.now().strftime("%H:%M:%S"), "",
        ))
        if flush:
            self._flush_chat()

    def _enqueue_chat(self, text: str) -> None:
        self._append_user(text, flush=False)
        slot = len(self._chat_lines)
        self._chat_lines.append("")
        self._chat_meta.append((
            "assistant", datetime.now().strftime("%H:%M:%S"), ""))
        self._reply_buffers[slot] = ""
        self._chat_queue.append((text, slot))
        self._streaming = True
        self._flush_chat()
        if not self._chat_worker_running:
            self._chat_worker_running = True
            self._run_chat_queue()

    def _stream_ai(self, slot: int, chunk: str) -> None:
        reply = self._reply_buffers.get(slot, "") + chunk
        self._reply_buffers[slot] = reply
        self._chat_lines[slot] = reply
        self._flush_chat()

    async def _reveal_ai_chunk(self, slot: int, chunk: str) -> None:
        for cluster in grapheme_clusters(chunk):
            self._stream_ai(slot, cluster)
            await asyncio.sleep(_REPLY_REVEAL_INTERVAL)

    def _end_ai(self, slot: int) -> None:
        self._reply_buffers.pop(slot, None)
        controller = self._controller
        if controller and slot < len(self._chat_meta):
            role, time_text, _ = self._chat_meta[slot]
            mood = controller.public_status().get("mood", {})
            self._chat_meta[slot] = (
                role, time_text, str(mood.get("primary", "未知")),
            )
        self._flush_chat()
        if self._active == 2:
            self._render_status()

    def _flush_chat(self) -> None:
        controller = self._controller
        if controller is None:
            self.update("", tab=0)
            return
        player_sender_getter = getattr(
            controller, "player_chat_sender", None)
        player_sender = (
            player_sender_getter()
            if callable(player_sender_getter)
            else {"name": controller.player}
        )
        player_name = str(player_sender.get("name") or controller.player)
        status = controller.public_status()
        mood = status.get("mood", {})
        companion_name = self._selected_character_name() or "旅伴"
        companion_key = f"companion:{companion_name}"
        companion_sender = {
            "name": companion_key,
            "labels": [companion_name],
            "style": player_sender.get("style", {}),
        }
        entries = []
        for index, content in enumerate(self._chat_lines):
            if index >= len(self._chat_meta):
                continue
            meta = self._chat_meta[index]
            role, time_text = meta[:2]
            if not content and role != "assistant":
                continue
            message_mood = (
                meta[2] if len(meta) > 2 and meta[2]
                else str(mood.get("primary", "未知"))
            )
            sender_name = player_name if role == "user" else companion_key
            if role == "user":
                text = content
            else:
                assistant_lines = _split_action_and_speech(content).splitlines()
                text = "\n".join(
                    f"{ICON_INDENT}{line}"
                    if re.fullmatch(r"\*[^*\n]+\*", line)
                    else line
                    for line in assistant_lines
                )
            entries.append(SimpleNamespace(
                sender_name=sender_name,
                text=text,
                time=time_text,
                role=role,
                mood=message_mood,
            ))
        senders = {player_name: player_sender}
        for entry in entries:
            if entry.role != "assistant":
                continue
            mood_label = MOODS.get(entry.mood, entry.mood or "未知")
            sender_key = f"{companion_key}:{mood_label}"
            entry.sender_name = sender_key
            senders[sender_key] = {
                **companion_sender,
                "name": sender_key,
                "labels": [companion_name],
            }
        self.update(
            render_chat_groups(
                entries,
                senders,
                self._content_width(0),
                line_formatter=self._format_companion_frame_line,
            ),
            tab=0,
        )

    @staticmethod
    def _format_companion_frame_line(entry, line: str, body_color: str) -> str:
        escaped = escape(line)
        if (
                getattr(entry, "role", "") == "assistant"
                and re.fullmatch(
                    rf"{re.escape(ICON_INDENT)}\*[^*\n]+\*", line)):
            return f"[italic {COLOR_FG_TERTIARY}]{escaped}[/]"
        return f"[{body_color}]{escaped}[/]"

    def reflow_content(self) -> None:
        self._render_current_tab()

    @work(exclusive=True, group="companion-chat-queue")
    async def _run_chat_queue(self) -> None:
        try:
            while self._chat_queue:
                text, slot = self._chat_queue.popleft()
                controller = self._controller
                if controller is None:
                    self._stream_ai(slot, "[错误：旅伴服务不可用]")
                    self._end_ai(slot)
                    continue
                try:
                    async for chunk in controller.chat(text):
                        await self._reveal_ai_chunk(slot, chunk)
                except Exception as exc:
                    self._stream_ai(slot, f"\n[错误：{exc}]")
                finally:
                    self._end_ai(slot)
        finally:
            self._chat_worker_running = False
            self._streaming = bool(self._chat_queue or self._reply_buffers)
            self._sync_input()
            if self._chat_queue:
                self._chat_worker_running = True
                self._run_chat_queue()

    def _add_proactive(self, text: str) -> None:
        self._chat_lines.append(text)
        self._chat_meta.append((
            "assistant",
            datetime.now().strftime("%H:%M:%S"),
            str(self._controller.public_status().get("mood", {}).get(
                "primary", "未知")) if self._controller else "未知",
        ))
        self._flush_chat()


class CompanionWindow(Window):
    """Single floating window for companion chat and configuration."""

    DEFAULT_CSS = """
    CompanionWindow {
        layer: floating;
        width: 62%;
        height: 62%;
    }
    CompanionWindow > #companion-panel {
        width: 1fr;
        height: 1fr;
    }
    """

    focus_grid = [["companion-panel"]]
    primary_panel = "companion-panel"

    spec = WindowSpec(
        id="companion-window",
        title="旅伴",
        menu=True,
        group="root",
        order=50,
        preconditions=(logged_in,),
        bind=bind_state,
        on_open=_mark_companion_seen,
    )

    def compose(self) -> ComposeResult:
        yield CompanionPanel(id="companion-panel")

    def bind_state(self, state) -> None:
        controller = CompanionController.instance(state)
        panel = self.query_one("#companion-panel", CompanionPanel)
        panel.bind_controller(controller)

    def open_settings(self) -> None:
        self.query_one("#companion-panel", CompanionPanel).open_settings()

    def mark_seen(self, context) -> None:
        context.state.notify.clear_companion_unread()
        context.update_badges()

    def refresh_companion(self) -> None:
        controller = CompanionController.instance()
        self.query_one(
            "#companion-panel", CompanionPanel,
        ).bind_controller(controller)

    def receive_proactive(self, text: str) -> None:
        panel = self.query_one("#companion-panel", CompanionPanel)
        if panel._controller_generation == CompanionController.instance().generation:
            panel._add_proactive(text)


register_window(CompanionWindow)
