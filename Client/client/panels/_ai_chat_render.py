"""AI 面板 — 渲染层 (mixin for AIChatPanel)"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text as RichText
from textual.widgets import RichLog, Static

from ..config import (
    M_DIM, M_END,
    COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_BORDER_LIGHT, COLOR_ACCENT,
)
from ..widgets.helpers import build_tab_overflow, _widget_width

_MAX_MODEL_VISIBLE = 8

# 菜单 Tab 常量（ai_chat.py 共用）
_TABS = ["chat", "gift", "action", "settings"]
_TAB_LABELS = {"chat": "聊天", "gift": "赠送", "action": "互动", "settings": "设置"}


class _ChatRenderMixin:
    """AIChatPanel 的渲染方法集"""

    # ── 模型列表 ──

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
        """渲染模型列表，溢出时右侧显示滚动条"""
        if not self._setup_models:
            return [f"{M_DIM}暂无可用模型{M_END}"]
        total = len(self._setup_models)
        offset = self._model_scroll_offset
        visible = self._setup_models[offset:offset + _MAX_MODEL_VISIBLE]

        need_sb = total > _MAX_MODEL_VISIBLE
        if need_sb:
            max_off = max(1, total - _MAX_MODEL_VISIBLE)
            thumb_size = max(1, round(len(visible) / total * len(visible)))
            track_space = len(visible) - thumb_size
            thumb_start = round(offset / max_off * track_space) if track_space > 0 else 0

        # 获取可用宽度用于右对齐滚动条
        try:
            avail = self.query_one("#ai-panel-content").size.width
        except Exception:
            avail = 40

        lines = []
        for vi, m in enumerate(visible):
            real_idx = offset + vi
            display = m["display"]
            info = m.get("info", "")
            selected = real_idx == self._setup_model_cursor
            if selected:
                marker = f"[{COLOR_ACCENT}]●[/]"
                text = f"[b]{display}[/b]"
                plain = f" ● {display}"
            else:
                marker = " "
                text = f"[{COLOR_FG_SECONDARY}]{display}{M_END}"
                plain = f"   {display}"
            line = f" {marker} {text}"
            if selected and info:
                line += f"  [{COLOR_FG_TERTIARY}]{info}{M_END}"
                plain += f"  {info}"
            if need_sb:
                pad = max(0, avail - cell_len(plain) - 2)
                if thumb_start <= vi < thumb_start + thumb_size:
                    line += f"{' ' * pad} [{COLOR_ACCENT}]█{M_END}"
                else:
                    line += f"{' ' * pad} [{COLOR_FG_TERTIARY}]│{M_END}"
            lines.append(line)
        return lines

    # ── SETUP 视图 ──

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
        if self._create_status:
            lines.append("")
            lines.append(f"{M_DIM}{self._create_status}{M_END}")
        content.update("\n".join(lines))

    # ── SELECT 视图 ──

    def _render_select(self):
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
        except Exception:
            return

        lines = [
            f"[b]AI 旅伴[/b]",
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
        content.update("\n".join(lines))

    # ── CREATE 视图 ──

    def _render_create(self):
        if self._create_step == "review":
            self._render_create_review()
            return
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
        except Exception:
            return

        lines = [
            f"[b]创建新角色[/b]",
            f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}",
        ]
        if self._create_step == "desc":
            lines.append(f"[{COLOR_FG_SECONDARY}]步骤 1/2 — 描述你的 AI 旅伴{M_END}")
            lines.append(f"[{COLOR_FG_TERTIARY}]名字、性格、说话风格、外貌、背景等{M_END}")
            lines.append(f"[{COLOR_FG_TERTIARY}]随意描述即可，AI 会自动整理{M_END}")
        if self._create_status:
            lines.append("")
            lines.append(f"{M_DIM}{self._create_status}{M_END}")
        content.update("\n".join(lines))

    def _render_create_review(self):
        """确认步骤 — 使用 RichLog 渲染，确保长内容可滚动"""
        try:
            content: Static = self.query_one("#ai-panel-content", Static)
            content.display = False
            log: RichLog = self.query_one("#ai-chat-log", RichLog)
            log.display = True
            log.clear()
        except Exception:
            return

        def _w(markup: str):
            log.write(RichText.from_markup(markup, overflow="fold"))

        _w(f"[b]创建新角色[/b]")
        _w(f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}")
        _w(f"[{COLOR_FG_SECONDARY}]步骤 2/2 — 确认角色信息{M_END}")
        _w(f"[{COLOR_BORDER_LIGHT}]{'─' * 24}{M_END}")
        if self._create_char:
            c = self._create_char
            _w(f"[b]名字:[/b] {c.name}")
            _w(f"[b]性格:[/b] {c.personality}")
            _w(f"[b]说话风格:[/b] {c.speech_style}")
            _w(f"[b]外貌:[/b] {c.appearance}")
            _w(f"[b]背景:[/b] {c.backstory}")
            if c.custom_rules:
                _w(f"[b]特殊规则:[/b]")
                for rule in c.custom_rules:
                    _w(f"  - {rule}")
        _w("")
        _w(f"[{COLOR_FG_TERTIARY}]输入修改意见，或输入「确定」保存{M_END}")
        if self._create_status:
            _w("")
            _w(f"{M_DIM}{self._create_status}{M_END}")
        log.scroll_end(animate=False)

    # ── CHAT 视图 ──

    def _render_header(self):
        """渲染常驻顶栏：Tab 栏（溢出时显示箭头滚动）+ 角色状态"""
        tab_parts = []
        for t in _TABS:
            label = _TAB_LABELS[t]
            if t == self._menu_tab:
                plain = f"● {label}"
                markup = f"[{COLOR_ACCENT}]{plain}[/]"
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_FG_TERTIARY}]{label}{M_END}"
            tab_parts.append((markup, cell_len(plain)))

        active_idx = _TABS.index(self._menu_tab) if self._menu_tab in _TABS else 0
        avail = _widget_width(self, "ai-chat-header")
        tab_line = build_tab_overflow(tab_parts, active_idx, avail, COLOR_FG_TERTIARY)

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
        self._sync_gift_items()
        lines = []
        if not self._gift_items:
            lines.append(f"[{COLOR_FG_TERTIARY}]暂无物品{M_END}")
            return lines
        for i, item in enumerate(self._gift_items):
            name = item.get("name", "?")
            count = item.get("count", 0)
            selected = i == self._gift_cursor
            if selected and self._gift_qty > 0:
                lines.append(f" [{COLOR_ACCENT}]●[/] [b]{name} x{count}[/b]")
                lines.append(f"   赠送数量: [{COLOR_ACCENT}]{self._gift_qty}[/]")
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
            f"重置所有记忆",
            f"切换角色",
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
        return lines
