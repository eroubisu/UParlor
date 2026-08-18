"""游戏详情面板 — 右侧展示游戏信息 + 设置项 + 创建房间按钮"""

from __future__ import annotations

import json

from ...config import (
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY,
    M_DIM, M_BOLD, M_END, M_MUTED, ICON_INDENT,
)
from ...widgets.panel import Panel, text_width
from ...window_engine.text import wrap_cells
from ...window_engine import Option
from ...protocol.renderer import get_renderer

def _pad_left(s: str, target: int) -> str:
    w = text_width(s)
    return s + ' ' * max(0, target - w)

def _wrap_text(text: str, width: int, indent: str) -> list[str]:
    """按显示宽度手动折行，每行添加前缀 indent"""
    if width <= 0:
        return [f"{indent}{text}"]
    return [f"{indent}{line}" for line in wrap_cells(text, width)]

class GameDetailPanel(Panel):
    """游戏详情：简介 + 设置项 + 创建房间

    光标在设置项和创建按钮间移动。
    Enter 在设置项上循环切换选项值，在创建按钮上发送 /create。
    """

    icon_align = True
    follow_focus = True
    title = "游戏详情"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._game: dict | None = None
        self._send = None
        self._panel_focused: bool = False
        self._settings: dict = {}       # key → current value
        self._items: list[dict] = []    # [{type:'setting', key, ...}, {type:'create'}]
        self._header_lines: int = 0     # lines before items

    def bind_send(self, send_fn) -> None:
        self._send = send_fn

    def show_game(self, game: dict | None) -> None:
        self._game = game
        self._settings.clear()
        self._items.clear()
        if not game:
            self.update(f"{M_DIM}选择一个游戏查看详情{M_END}")
            return
        for s in game.get('room_settings', []):
            self._settings[s['key']] = s['default']
        self._build_items()
        self._redraw()

    def _build_items(self) -> None:
        self._items.clear()
        if not self._game:
            return
        for s in self._game.get('room_settings', []):
            self._items.append({'type': 'setting', 'key': s['key'], 'schema': s})
        self._items.append({'type': 'create'})

    def _redraw(self) -> None:
        if not self._game:
            return
        g = self._game
        game_id = g.get('id', '')
        name = g.get('name', game_id or '???')
        renderer = get_renderer(game_id)
        icon = renderer.icon if renderer else ''
        desc = g.get('description', '')
        mn = g.get('min_players', '')
        mx = g.get('max_players', '')
        focused = self._panel_focused

        lines: list[str] = [f"{M_BOLD}{icon} {name}{M_END}", ""]
        if desc:
            # 手动折行，保证每行都有 ICON_INDENT
            panel_w = self._content_width(0)
            desc_w = max(10, panel_w - text_width(ICON_INDENT))
            for dl in _wrap_text(desc, desc_w, ICON_INDENT):
                lines.append(f"{M_MUTED}{dl}{M_END}")
            lines.append("")
        if mn and mx:
            lines.append(f"{ICON_INDENT}人数    {mn}-{mx}")
        lines.append(f"{ICON_INDENT}标识    {g.get('id', '???')}")
        lines.append("")

        self._header_lines = len(lines)

        # 找最大标签宽度
        max_label_w = 4
        for item in self._items:
            if item['type'] == 'setting':
                w = text_width(item['schema']['label'])
                if w > max_label_w:
                    max_label_w = w

        row_w = max(20, self._content_width(0))
        options = []
        for item in self._items:
            if item['type'] == 'setting':
                s = item['schema']
                label = s['label']
                val = self._settings.get(s['key'], s['default'])
                val_label = str(val)
                for o in s['options']:
                    if o['value'] == val:
                        val_label = str(o['label'])
                        break

                padded_label = _pad_left(label, max_label_w)
                options.append(Option(
                    item["key"],
                    padded_label,
                    val_label,
                    data=item,
                    description_align="right",
                ))
            elif item['type'] == 'create':
                options.append(Option("create", "创建房间", data=item))

        self.set_options(options, f"game-detail:{game_id}")
        lines.extend(("", self.selection.render(
            row_w,
            idle_prefix=ICON_INDENT,
            selected_style=(
                f"bold {COLOR_FG_PRIMARY}"
                if focused else COLOR_FG_TERTIARY
            ),
            idle_style=COLOR_FG_TERTIARY,
        )))

        self._focus_line = self._header_lines + self.selected_line(width=row_w)
        self.update("\n".join(lines))

    def _cycle_setting(self, key: str, schema: dict, step: int = 1) -> None:
        options = schema['options']
        cur = self._settings.get(key, schema['default'])
        idx = 0
        for i, o in enumerate(options):
            if o['value'] == cur:
                idx = i
                break
        self._settings[key] = options[(idx + step) % len(options)]['value']

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._redraw()

    def on_panel_focus(self) -> None:
        self._panel_focused = True
        self._redraw()

    def on_panel_blur(self) -> None:
        self._panel_focused = False
        self._redraw()

    def reflow_content(self) -> None:
        self._redraw()

    def nav(self, action: str) -> None:
        if not self._items:
            super().nav(action)
            return
        if action in ("up", "down"):
            if self.selection.move(-1 if action == 'up' else 1):
                self._redraw()
        elif action == "enter":
            selected = self.selected_option
            if selected is None:
                return
            item = selected.data
            if item['type'] == 'setting':
                self._cycle_setting(item['key'], item['schema'])
                self._redraw()
            elif item['type'] == 'create' and self._send:
                gid = self._game.get('id', '')
                if gid:
                    settings = json.dumps(self._settings, ensure_ascii=False)
                    self._send(f"/create {gid} {settings}")
        elif action in ("tab_prev", "tab_next"):
            selected = self.selected_option
            item = selected.data if selected is not None else None
            if item and item['type'] == 'setting':
                step = -1 if action == "tab_prev" else 1
                self._cycle_setting(item['key'], item['schema'], step)
                self._redraw()
        else:
            super().nav(action)
