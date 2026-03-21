"""StatusPanel — 渲染层 (mixin)"""

from __future__ import annotations

from rich.text import Text as RichText
from textual.widgets import RichLog

from ...config import (
    M_BOLD, M_DIM, M_END, M_MUTED,
    COLOR_FG_PRIMARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT,
)
from ...widgets.helpers import render_tab_header, _widget_width
from .card import render_card, CARD_FIELD_DEFS, DEFAULT_CARD_FIELDS
from ...data import COLOR_PRESETS as _COLOR_PRESETS
from ...data import EQUIPMENT_SLOT_LABELS, ATTRIBUTE_LABELS
from ...data import GAME_STATUS_CONFIG

# 页面常量
_PAGE_STATUS = 'status'
_PAGE_EQUIP = 'equip'
_PAGE_CARD = 'card'
_PAGE_SETTINGS = 'settings'
_PAGE_GAME = 'game'
_PAGES = [_PAGE_STATUS, _PAGE_EQUIP, _PAGE_CARD, _PAGE_SETTINGS]
_PAGE_LABELS = {
    _PAGE_STATUS: '状态', _PAGE_EQUIP: '装备',
    _PAGE_CARD: '名片', _PAGE_SETTINGS: '设置',
    _PAGE_GAME: '游戏',
}

# 设置菜单项
_SETTINGS_ITEMS = [
    ('edit_motto', '修改签名'),
    ('edit_colors', '更改颜色'),
    ('switch_pattern', '切换花色'),
    ('edit_fields', '名片字段'),
    ('change_password', '修改密码'),
    ('delete_account', '注销账号'),
]

# 颜色子菜单
_COLOR_MENU_ITEMS = [
    ('name_color', '名字颜色'),
    ('motto_color', '签名颜色'),
    ('border_color', '边框颜色'),
]

# 子模式常量
_SUB_NONE = ''
_SUB_COLOR_MENU = 'color_menu'
_SUB_COLOR_PICK = 'color_pick'
_SUB_PATTERN_PICK = 'pattern_pick'
_SUB_MOTTO_INPUT = 'motto_input'
_SUB_FIELD_PICK = 'field_pick'


class StatusRenderMixin:
    """渲染方法集合 — 由 StatusPanel 继承使用。"""

    def _render_all(self):
        self._render_header()
        self._render_page()
        name = self._player_data.get('name', '') if self._player_data else ''
        if name:
            try:
                from ...widgets.helpers import _set_pane_subtitle
                _set_pane_subtitle(self, name)
            except Exception:
                pass

    def _get_pages(self) -> list[str]:
        """根据游戏上下文返回可用页面列表"""
        pages = list(_PAGES)
        game_type = self._current_game_type()
        if game_type and game_type in GAME_STATUS_CONFIG:
            pages.insert(-1, _PAGE_GAME)  # 在设置前插入
        return pages

    def _current_game_type(self) -> str | None:
        """从 StatusState.location 提取当前游戏类型"""
        loc = ''
        st = getattr(self, '_state_mgr', None)
        if st:
            loc = st.status.location or ''
        if not loc:
            return None
        for game_type in GAME_STATUS_CONFIG:
            if loc.startswith(game_type):
                return game_type
        return None

    def _render_header(self):
        pages = self._get_pages()
        render_tab_header(self, "status-header", pages, _PAGE_LABELS, self._page)

    def _render_page(self):
        if self._page == _PAGE_CARD:
            self._render_card_page()
        elif self._page == _PAGE_STATUS:
            self._render_status_page()
        elif self._page == _PAGE_EQUIP:
            self._render_equip_page()
        elif self._page == _PAGE_GAME:
            self._render_game_page()
        elif self._page == _PAGE_SETTINGS:
            self._render_settings_page()

    def _render_card_page(self):
        try:
            log: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        pd = self._player_data
        if not pd:
            log.clear()
            log.write(RichText.from_markup(f"{M_DIM}暂无数据{M_END}"))
            return
        card = pd.get('profile_card', {})
        card_data = {
            'name': pd.get('name', '?'),
            'title': pd.get('title', ''),
            'level': pd.get('level', 1),
            'gold': pd.get('gold', 0),
            'motto': card.get('motto', ''),
            'name_color': card.get('name_color', '#ffffff'),
            'motto_color': card.get('motto_color', '#b3b3b3'),
            'border_color': card.get('border_color', '#5a5a5a'),
            'pattern': card.get('pattern', {}),
            'card_fields': card.get('card_fields', DEFAULT_CARD_FIELDS),
            'created_at': pd.get('created_at', ''),
            'game_stats': pd.get('game_stats', {}),
            'social_stats': pd.get('social_stats', {}),
            'friends_count': pd.get('friends_count', 0),
        }
        avail_w = _widget_width(self, "status-content")
        avail_h = self._visible_height()
        render_card(log, card_data, avail_w, avail_h)

    def _visible_height(self) -> int:
        try:
            log = self.query_one("#status-content", RichLog)
            h = log.scrollable_content_region.height
            return h if h > 0 else 15
        except Exception:
            return 15

    def _render_status_page(self):
        try:
            log: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        log.clear()
        pd = self._player_data
        if not pd:
            log.write(RichText.from_markup(f"{M_DIM}暂无数据{M_END}"))
            return
        name = pd.get('name', '?')
        title = pd.get('title', '')
        level = pd.get('level', 1)
        gold = pd.get('gold', 0)
        log.write(RichText.from_markup(f"{M_BOLD}{name}{M_END}"))
        if title:
            log.write(RichText.from_markup(f"{M_MUTED}{title}{M_END}"))
        log.write(RichText.from_markup(f"{M_MUTED}Lv.{level}  {gold}G{M_END}"))

        # 经验进度条
        exp = pd.get('exp', 0)
        exp_to_next = pd.get('exp_to_next', 0)
        if exp_to_next > 0:
            ratio = min(exp / exp_to_next, 1.0)
            bar_len = 20
            filled = int(ratio * bar_len)
            bar = '█' * filled + '░' * (bar_len - filled)
            log.write(RichText.from_markup(
                f"[#a0a0a0]{bar}[/] {M_DIM}{exp}/{exp_to_next}{M_END}"))
        elif exp_to_next == 0 and level > 1:
            log.write(RichText.from_markup(f"{M_DIM}MAX LEVEL{M_END}"))

        attr_data = pd.get('attributes', {})
        if attr_data:
            log.write(RichText())
            cur_hp = attr_data.get('current_hp', 0)
            max_hp = attr_data.get('max_hp', 0)
            cur_mp = attr_data.get('current_mp', 0)
            max_mp = attr_data.get('max_mp', 0)
            log.write(RichText.from_markup(
                f"HP {cur_hp}/{max_hp}  MP {cur_mp}/{max_mp}"))
            stats = attr_data.get('stats', {})
            for key, label in ATTRIBUTE_LABELS.items():
                if key in ('hp', 'mp'):
                    continue
                val = stats.get(key, 0)
                if val:
                    log.write(RichText.from_markup(
                        f"{M_DIM}{label}{M_END} {val}"))

    def _render_equip_page(self):
        try:
            log: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        log.clear()
        pd = self._player_data
        if not pd:
            log.write(RichText.from_markup(f"{M_DIM}暂无数据{M_END}"))
            return
        equip_data = pd.get('equipment', {})
        slots = list(EQUIPMENT_SLOT_LABELS.items())
        if self._equip_cursor >= len(slots):
            self._equip_cursor = 0

        vh = max(1, self._visible_height())
        cursor_slot = slots[self._equip_cursor][0] if self._equip_cursor < len(slots) else ''
        cursor_lines = 2 if (self._equip_confirm and self._equip_confirm == cursor_slot) else 1

        if self._equip_cursor < self._equip_scroll:
            self._equip_scroll = self._equip_cursor
        elif self._equip_cursor + cursor_lines > self._equip_scroll + vh:
            self._equip_scroll = self._equip_cursor + cursor_lines - vh
        self._equip_scroll = max(0, min(self._equip_scroll, max(0, len(slots) - 1)))

        lines_written = 0
        skipped = 0
        log.auto_scroll = False
        for i, (slot, slot_label) in enumerate(slots):
            if skipped < self._equip_scroll:
                skipped += 1
                continue
            if lines_written >= vh:
                break
            item = equip_data.get(slot)
            selected = (i == self._equip_cursor)
            confirming = (self._equip_confirm == slot and selected)
            if item and isinstance(item, dict):
                name = item.get('name', '?')
                if selected:
                    log.write(RichText.from_markup(
                        f"  [{COLOR_ACCENT}]●[/] {M_BOLD}{slot_label}{M_END} {name}"))
                else:
                    log.write(RichText.from_markup(
                        f"    {M_DIM}{slot_label}{M_END} {name}"))
            elif selected:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] {M_DIM}{slot_label} —{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    {M_DIM}{slot_label} —{M_END}"))
            lines_written += 1
            if confirming and lines_written < vh:
                log.write(RichText.from_markup(
                    f"      {M_DIM}确认卸下？{M_END}"))
                lines_written += 1
        log.scroll_home(animate=False)

    def _render_game_page(self):
        """渲染游戏标签页 — 显示游戏名 + 游戏专属槽位（同装备逻辑）"""
        try:
            log: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        log.clear()
        game_type = self._current_game_type()
        if not game_type:
            log.write(RichText.from_markup(f"{M_DIM}暂无游戏{M_END}"))
            return
        config = GAME_STATUS_CONFIG.get(game_type, {})
        game_name = config.get('name', game_type)
        slot_labels = config.get('slots', {})

        pd = self._player_data
        if not pd:
            log.write(RichText.from_markup(f"{M_DIM}暂无数据{M_END}"))
            return

        log.auto_scroll = False
        log.write(RichText.from_markup(f"  {M_BOLD}{game_name}{M_END}"))
        log.write(RichText())

        equip_data = pd.get('equipment', {})
        slots = list(slot_labels.items())
        if not slots:
            return

        game_cursor = getattr(self, '_game_cursor', 0)
        game_confirm = getattr(self, '_game_confirm', '')
        if game_cursor >= len(slots):
            game_cursor = 0

        vh = max(1, self._visible_height() - 2)  # 减去标题行
        game_scroll = getattr(self, '_game_scroll', 0)
        cursor_lines = 2 if (game_confirm and game_confirm == slots[game_cursor][0]) else 1

        if game_cursor < game_scroll:
            game_scroll = game_cursor
        elif game_cursor + cursor_lines > game_scroll + vh:
            game_scroll = game_cursor + cursor_lines - vh
        game_scroll = max(0, min(game_scroll, max(0, len(slots) - 1)))
        self._game_scroll = game_scroll

        lines_written = 0
        skipped = 0
        for i, (slot, slot_label) in enumerate(slots):
            if skipped < game_scroll:
                skipped += 1
                continue
            if lines_written >= vh:
                break
            item = equip_data.get(slot)
            selected = (i == game_cursor)
            confirming = (game_confirm == slot and selected)
            if item and isinstance(item, dict):
                name = item.get('name', '?')
                if selected:
                    log.write(RichText.from_markup(
                        f"  [{COLOR_ACCENT}]●[/] {M_BOLD}{slot_label}{M_END} {name}"))
                else:
                    log.write(RichText.from_markup(
                        f"    {M_DIM}{slot_label}{M_END} {name}"))
            elif selected:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] {M_DIM}{slot_label} —{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    {M_DIM}{slot_label} —{M_END}"))
            lines_written += 1
            if confirming and lines_written < vh:
                log.write(RichText.from_markup(
                    f"      {M_DIM}确认卸下？{M_END}"))
                lines_written += 1
        log.scroll_home(animate=False)

    def _render_settings_page(self):
        try:
            log: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        log.clear()
        if self._sub_mode == _SUB_COLOR_MENU:
            self._render_color_menu(log)
            return
        if self._sub_mode == _SUB_COLOR_PICK:
            self._render_color_picker(log)
            return
        if self._sub_mode == _SUB_PATTERN_PICK:
            self._render_pattern_picker(log)
            return
        if self._sub_mode == _SUB_FIELD_PICK:
            self._render_field_picker(log)
            return
        for i, (action_id, label) in enumerate(_SETTINGS_ITEMS):
            if action_id == 'delete_account' and i > 0:
                log.write(RichText.from_markup(f"{M_DIM}{'─' * 16}{M_END}"))
            if i == self._settings_cursor:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] {M_BOLD}{label}{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    {M_DIM}{label}{M_END}"))

    def _render_color_picker(self, log: RichLog):
        log.write(RichText.from_markup(
            f"{M_DIM}选择颜色 (j/k 移动, Enter 确认, Esc 取消){M_END}"))
        log.write(RichText())
        for i, (color, name) in enumerate(_COLOR_PRESETS):
            if i == self._sub_cursor:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] [{color}]■■[/] {M_BOLD}{name}{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    [{color}]■■[/] {M_DIM}{name}{M_END}"))

    def _render_pattern_picker(self, log: RichLog):
        log.write(RichText.from_markup(
            f"{M_DIM}选择花色 (j/k 移动, Enter 确认, Esc 取消){M_END}"))
        log.write(RichText())
        if not self._sub_items:
            log.write(RichText.from_markup(f"{M_DIM}无可用花色{M_END}"))
            return
        for i, item in enumerate(self._sub_items):
            name = item.get('name', item.get('id', '?'))
            pattern = item.get('pattern', {})
            preview_chars = pattern.get('chars', '...')[:8]
            preview_colors = pattern.get('colors', ['#808080'])
            preview = RichText()
            for ci, ch in enumerate(preview_chars):
                c = preview_colors[ci % len(preview_colors)] if preview_colors else '#808080'
                preview.append(ch, style=c)
            line = RichText()
            if i == self._sub_cursor:
                line.append("  ")
                line.append("● ", style=COLOR_ACCENT)
                line.append_text(preview)
                line.append(f" {name}", style=f'bold {COLOR_FG_PRIMARY}')
            else:
                line.append("    ")
                line.append_text(preview)
                line.append(f" {name}", style=COLOR_FG_TERTIARY)
            log.write(line)

    def _render_field_picker(self, log: RichLog):
        card = self._player_data.get('profile_card', {}) if self._player_data else {}
        selected = card.get('card_fields', DEFAULT_CARD_FIELDS)
        count = len(selected)
        log.write(RichText.from_markup(
            f"{M_DIM}选择字段 ({count}/4){M_END}"))
        log.write(RichText())
        for i, (fid, label) in enumerate(CARD_FIELD_DEFS):
            checked = fid in selected
            mark = '●' if checked else '○'
            if i == self._sub_cursor:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] {mark} {M_BOLD}{label}{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    {mark} {M_DIM}{label}{M_END}"))

    def _render_color_menu(self, log: RichLog):
        log.write(RichText.from_markup(
            f"{M_DIM}选择颜色类型 (j/k 移动, Enter 确认, Esc 返回){M_END}"))
        log.write(RichText())
        for i, (key, label) in enumerate(_COLOR_MENU_ITEMS):
            if i == self._sub_cursor:
                log.write(RichText.from_markup(
                    f"  [{COLOR_ACCENT}]●[/] {M_BOLD}{label}{M_END}"))
            else:
                log.write(RichText.from_markup(
                    f"    {M_DIM}{label}{M_END}"))
