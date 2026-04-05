"""Inventory 面板 — 渲染层 (mixin for InventoryPanel)"""

from __future__ import annotations

from rich.cells import cell_len
from textual.widgets import Static

from ...config import (
    COLOR_FG_PRIMARY,
    COLOR_FG_SECONDARY,
    COLOR_FG_TERTIARY,
    COLOR_ACCENT,
    COLOR_HINT_TAB_ACTIVE, COLOR_HINT_TAB_DIM,
)
from ...widgets.helpers import update_tab_header, render_action_menu
from ...data import QUALITY_MARKERS as _QUALITY_MARKERS, QUALITY_LABELS as _QUALITY_LABELS

# ── 共享常量（主文件和 views mixin 从此处导入） ──

_BASE_ACTIONS: list[tuple[str, str]] = [
    ('use',  '使用'),
    ('gift', '赠送'),
    ('info', '详情'),
    ('drop', '丢弃'),
]

_MODE_BROWSE  = 'browse'
_MODE_SEARCH  = 'search'
_MODE_ACTION  = 'action'
_MODE_USE_SUB = 'use_sub'
_MODE_DETAIL  = 'detail'
_MODE_INPUT   = 'input'
_MODE_GIFT         = 'gift'
_MODE_CONFIRM      = 'confirm'
_MODE_MULTI_SELECT = 'multi_select'
_MODE_QUANTITY     = 'quantity'
_MODE_SELECTED     = 'selected'

_FILTER_TABS = ["all", "consumable", "prop", "equipment", "material", "currency", "special"]
_FILTER_LABELS = {
    "all": "全部",
    "consumable": "消耗",
    "prop": "道具",
    "equipment": "装备",
    "material": "材料",
    "currency": "货币",
    "special": "特殊",
}

_QUALITY_ALL = ["all"] + sorted(k for k in _QUALITY_LABELS if k != "all")

_SORT_OPTIONS = [("name", "名称"), ("count", "数量"), ("category", "分类"), ("quality", "品质"), ("equipped", "装备")]

_MAX_GIFT_VISIBLE = 5


def _quality_name(name: str, quality: int) -> str:
    """给物品名添加品质标记"""
    pre, suf = _QUALITY_MARKERS.get(quality, ('', ''))
    if pre:
        return f"{pre}{name}{suf}"
    return name


class InventoryRenderMixin:
    """渲染逻辑 mixin — 标签栏 + 内容渲染"""

    # ── 标签栏渲染 ──

    def _render_header(self):
        if self._tab_row == 0:
            self._render_cat_header()
        elif self._tab_row == 1:
            self._render_sort_header()
        else:
            self._render_quality_header()

    def _render_cat_header(self):
        items = self._build_cat_items()
        if not items:
            return
        if self._cat_cursor >= len(items):
            self._cat_cursor = 0

        tab_parts: list[tuple[str, int]] = []
        real_active = 0

        for i, (val, label) in enumerate(items):
            if i == self._cat_cursor:
                plain = f"\u25cf {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    def _render_sort_header(self):
        active_idx = self._sort_cursor // 2
        is_asc = (self._sort_cursor % 2 == 0)
        tab_parts: list[tuple[str, int]] = []
        real_active = 0
        for i, (val, label) in enumerate(_SORT_OPTIONS):
            if i == active_idx:
                if is_asc:
                    arrows = "\u25b2\u25bd"
                else:
                    arrows = "\u25b3\u25bc"
                plain = f"{arrows}{label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"\u25b3\u25bd{label}"
                markup = f"[{COLOR_HINT_TAB_DIM}]{plain}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    def _render_quality_header(self):
        items = self._build_quality_items()
        if not items:
            return
        if self._quality_cursor >= len(items):
            self._quality_cursor = 0

        tab_parts: list[tuple[str, int]] = []
        real_active = 0

        for i, (val, label) in enumerate(items):
            if i == self._quality_cursor:
                plain = f"\u25cf {label}"
                markup = f"[{COLOR_HINT_TAB_ACTIVE}]{plain}[/]"
                real_active = len(tab_parts)
            else:
                plain = f"  {label}"
                markup = f"  [{COLOR_HINT_TAB_DIM}]{label}[/]"
            tab_parts.append((markup, cell_len(plain)))

        update_tab_header(self, "inventory-header", tab_parts, real_active)

    # ── 内容渲染 ──

    def _refresh_content(self):
        try:
            content: Static = self.query_one("#inventory-content", Static)
        except Exception:
            return

        self._update_gold_subtitle()

        if not self._filtered:
            search_hint = ""
            if self._search_query:
                search_hint = f"\n[{COLOR_FG_TERTIARY}]搜索: {self._search_query} — 无匹配[/]"
            content.update(
                f"[{COLOR_FG_TERTIARY}]暂无物品[/]{search_hint}"
            )
            return

        self._ensure_scroll()
        vh = self._visible_height()

        lines: list[str] = []

        # 头部状态行
        if self._search_query:
            lines.append(f"[{COLOR_FG_TERTIARY}]搜索: {self._search_query} ({len(self._filtered)})[/]")

        if self._mode in (_MODE_MULTI_SELECT, _MODE_QUANTITY):
            n = len(self._selections)
            total = sum(self._selections.values()) if self._selections else 0
            lines.append(f"[{COLOR_FG_TERTIARY}]多选模式  已选 {n} 种 {total} 件[/]")
        elif self._mode == _MODE_SELECTED or self._batch_mode:
            n = len(self._selections)
            total = sum(self._selections.values()) if self._selections else 0
            lines.append(f"[{COLOR_FG_TERTIARY}]已选物品  {n} 种 {total} 件[/]")

        start = self._scroll_offset
        end = min(len(self._filtered), start + max(1, vh))

        for i in range(start, end):
            item = self._filtered[i]
            selected = (i == self._cursor)
            self._render_item_line(lines, item, i, selected)

            if selected:
                self._render_item_submenu(lines, item)

        # 滚动指示
        total = len(self._filtered)
        if total > end - start:
            lines.append(f"[{COLOR_FG_TERTIARY}]  {self._cursor + 1}/{total}[/]")

        content.update("\n".join(lines))

    def _render_item_line(self, lines: list[str], item: dict, idx: int, selected: bool):
        """渲染单个物品行"""
        name = item.get('name', item['id'])
        quality = item.get('quality', 0)
        display_name = _quality_name(name, quality)
        count = item.get('count', 0)
        equipped_slot = item.get('equipped', '')
        equip_tag = f" [{COLOR_FG_TERTIARY}]<装备中>[/]" if equipped_slot else ""

        if self._mode in (_MODE_MULTI_SELECT, _MODE_QUANTITY):
            key = self._item_key(item)
            sel_qty = self._selections.get(key, 0)
            if selected:
                marker = f"[{COLOR_ACCENT}]\u25cf[/]"
                text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count}[/]"
            elif sel_qty > 0:
                marker = f"[{COLOR_FG_SECONDARY}]\u25cf[/]"
                text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"
            else:
                marker = f"[{COLOR_FG_TERTIARY}]\u25cb[/]"
                text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"
            if sel_qty > 0:
                text += f" [{COLOR_FG_TERTIARY}]({sel_qty})[/]"
        elif self._mode == _MODE_SELECTED or self._batch_mode:
            key = self._item_key(item)
            sel_qty = self._selections.get(key, 0)
            if selected:
                marker = f"[{COLOR_ACCENT}]\u25cf[/]"
                text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count} \u2192 {sel_qty}[/]"
            else:
                marker = " "
                text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count} \u2192 {sel_qty}[/]"
        elif selected:
            marker = f"[{COLOR_ACCENT}]\u25cf[/]"
            text = f"[bold {COLOR_FG_PRIMARY}]{display_name}[/]  [{COLOR_FG_SECONDARY}]x{count}[/]{equip_tag}"
        else:
            marker = " "
            text = f"[{COLOR_FG_SECONDARY}]{display_name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]{equip_tag}"

        lines.append(f" {marker} {text}")

    def _render_item_submenu(self, lines: list[str], item: dict):
        """渲染当前选中物品的子菜单（ACTION/USE_SUB/GIFT/DETAIL 等）"""
        if self._mode == _MODE_ACTION:
            actions = self._get_item_actions(item)
            lines += render_action_menu(actions, self._action_cursor)

        elif self._mode == _MODE_USE_SUB:
            if not self._use_methods:
                lines.append(f"     [{COLOR_FG_TERTIARY}]此物品无法使用[/]")
            else:
                use_actions = [(str(i), m['name']) for i, m in enumerate(self._use_methods)]
                lines += render_action_menu(use_actions, self._use_cursor, indent="       ")

        elif self._mode == _MODE_INPUT:
            lines.append(f"     [{COLOR_FG_SECONDARY}]{self._input_label}[/]")

        elif self._mode == _MODE_GIFT:
            lines += self._render_gift_lines()

        elif self._mode == _MODE_QUANTITY:
            lines.append(f"     [{COLOR_FG_SECONDARY}]{self._input_label}[/]")

        elif self._mode == _MODE_CONFIRM:
            lines.append(f"     [{COLOR_FG_SECONDARY}]{self._confirm_label}[/]")

        elif self._mode == _MODE_DETAIL:
            desc = item.get('desc') or '暂无描述'
            quality = item.get('quality', 0)
            cat_label = _FILTER_LABELS.get(item.get('category', ''), item.get('category', ''))
            qual_label = _QUALITY_LABELS.get(str(quality), '普通')
            lines.append(f"     [{COLOR_FG_SECONDARY}]{desc}[/]")
            detail_parts = []
            if cat_label:
                detail_parts.append(f"分类: {cat_label}")
            detail_parts.append(f"品质: {qual_label}")
            lines.append(f"     [{COLOR_FG_TERTIARY}]{'  '.join(detail_parts)}[/]")

    def _render_gift_lines(self) -> list[str]:
        lines = []
        if not self._gift_friends:
            hint = "搜索好友..." if not self._gift_query else "无匹配好友"
            lines.append(f"     [{COLOR_FG_TERTIARY}]{hint}[/]")
            return lines

        total = len(self._gift_friends)
        offset = max(0, min(self._gift_scroll, total - _MAX_GIFT_VISIBLE))
        self._gift_scroll = offset
        vis_end = min(total, offset + _MAX_GIFT_VISIBLE)

        visible = [(str(i), self._gift_friends[i]) for i in range(offset, vis_end)]
        lines += render_action_menu(visible, self._gift_cursor - offset)

        if total > _MAX_GIFT_VISIBLE:
            lines.append(f"     [{COLOR_FG_TERTIARY}]{self._gift_cursor + 1}/{total}[/]")

        return lines
