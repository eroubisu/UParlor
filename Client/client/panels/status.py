"""StatusPanel — 玩家状态面板（名片 / 状态 / 设置）"""

from __future__ import annotations

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import (
    MAX_LINES_STATUS,
    M_BOLD, M_DIM, M_END, M_ACCENT, M_MUTED,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT,
)
from ..state import ModuleStateManager
from ..widgets.helpers import render_tab_header, _widget_width
from ..widgets.input_bar import InputBar
from ..widgets.prompt import InputBarMixin
from ._card_render import render_card, CARD_FIELD_DEFS, DEFAULT_CARD_FIELDS


# ── 页面 ──
_PAGE_STATUS = 'status'
_PAGE_CARD = 'card'
_PAGE_SETTINGS = 'settings'
_PAGES = [_PAGE_STATUS, _PAGE_CARD, _PAGE_SETTINGS]
_PAGE_LABELS = {_PAGE_STATUS: '状态', _PAGE_CARD: '名片', _PAGE_SETTINGS: '设置'}

# ── 设置菜单项 ──
_SETTINGS_ITEMS = [
    ('edit_motto', '修改签名'),
    ('edit_colors', '颜色'),
    ('switch_pattern', '切换花色'),
    ('edit_fields', '名片字段'),
    ('delete_account', '注销账号'),
]

# ── 颜色预设 ──
_COLOR_PRESETS = [
    ('#ffffff', '白'),
    ('#c0c0c0', '银'),
    ('#808080', '灰'),
    ('#FFB6C1', '粉'),
    ('#87CEEB', '天蓝'),
    ('#90EE90', '浅绿'),
    ('#FFD700', '金'),
    ('#DDA0DD', '紫'),
    ('#98FB98', '薄荷'),
    ('#FFBF00', '琥珀'),
    ('#FF7F50', '珊瑚'),
    ('#007FFF', '蔚蓝'),
]

# ── 颜色子菜单 ──
_COLOR_MENU_ITEMS = [
    ('name_color', '名字颜色'),
    ('motto_color', '签名颜色'),
    ('border_color', '边框颜色'),
]

# ── 删除流程 ──
_DEL_IDLE = ''
_DEL_CONFIRM = 'confirm'
_DEL_PASSWORD = 'password'

# ── 设置子模式 ──
_SUB_NONE = ''
_SUB_COLOR_MENU = 'color_menu'
_SUB_COLOR_PICK = 'color_pick'
_SUB_PATTERN_PICK = 'pattern_pick'
_SUB_MOTTO_INPUT = 'motto_input'
_SUB_FIELD_PICK = 'field_pick'


class StatusPanel(InputBarMixin, Widget):
    """状态面板：名片 / 状态 / 设置"""

    _input_bar_id = "status-input-bar"
    _scroll_target_id = "status-content"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._player_data: dict = {}
        self._page: str = _PAGE_STATUS
        self._settings_cursor: int = 0
        self._sub_mode: str = _SUB_NONE
        self._sub_cursor: int = 0
        self._sub_items: list = []
        self._color_target: str = ''  # 'name_color' | 'motto_color'
        self._delete_step: str = _DEL_IDLE
        self._delete_username: str = ''
        self._wants_insert: bool = False
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="status-header", markup=True)
        yield RichLog(
            id="status-content", wrap=True, highlight=True,
            markup=True, max_lines=MAX_LINES_STATUS, min_width=0,
        )
        yield InputBar(prompt_id="status-prompt", id="status-input-bar")

    def on_mount(self) -> None:
        try:
            self.query_one("#status-input-bar", InputBar).remove_class("visible")
        except Exception:
            pass

    @property
    def wants_insert(self) -> bool:
        return self._wants_insert

    # ── 渲染 ──

    def _render_all(self):
        self._render_header()
        self._render_page()
        # 始终显示用户名
        name = self._player_data.get('name', '') if self._player_data else ''
        if name:
            try:
                from ..widgets.helpers import _set_pane_subtitle
                _set_pane_subtitle(self, name)
            except Exception:
                pass

    def _render_header(self):
        render_tab_header(self, "status-header", _PAGES, _PAGE_LABELS, self._page)

    def _render_page(self):
        if self._page == _PAGE_CARD:
            self._render_card_page()
        elif self._page == _PAGE_STATUS:
            self._render_status_page()
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
        log.write(RichText.from_markup(f"{M_BOLD}{name}{M_END}"))
        if title:
            log.write(RichText.from_markup(f"{M_MUTED}{title}{M_END}"))
        log.write(RichText.from_markup(f"{M_MUTED}Lv.{level}{M_END}"))

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
        # 主菜单
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

    # ── 导航 ──

    def nav_tab_next(self):
        if self._wants_insert or self._sub_mode:
            return
        idx = _PAGES.index(self._page) if self._page in _PAGES else 0
        self._page = _PAGES[(idx + 1) % len(_PAGES)]
        self._render_all()

    def nav_tab_prev(self):
        if self._wants_insert or self._sub_mode:
            return
        idx = _PAGES.index(self._page) if self._page in _PAGES else 0
        self._page = _PAGES[(idx - 1) % len(_PAGES)]
        self._render_all()

    def nav_up(self):
        if self._page == _PAGE_CARD:
            try:
                log = self.query_one("#status-content", RichLog)
                log.scroll_up(animate=False)
            except Exception:
                pass
            return
        if self._page == _PAGE_SETTINGS:
            if self._sub_mode in (_SUB_COLOR_MENU, _SUB_COLOR_PICK, _SUB_PATTERN_PICK, _SUB_FIELD_PICK):
                if self._sub_cursor > 0:
                    self._sub_cursor -= 1
                self._render_page()
                return
            if self._settings_cursor > 0:
                self._settings_cursor -= 1
            self._render_page()

    def nav_down(self):
        if self._page == _PAGE_CARD:
            try:
                log = self.query_one("#status-content", RichLog)
                log.scroll_down(animate=False)
            except Exception:
                pass
            return
        if self._page == _PAGE_SETTINGS:
            if self._sub_mode == _SUB_COLOR_MENU:
                if self._sub_cursor < len(_COLOR_MENU_ITEMS) - 1:
                    self._sub_cursor += 1
                self._render_page()
                return
            if self._sub_mode == _SUB_COLOR_PICK:
                if self._sub_cursor < len(_COLOR_PRESETS) - 1:
                    self._sub_cursor += 1
                self._render_page()
                return
            if self._sub_mode == _SUB_PATTERN_PICK:
                if self._sub_cursor < len(self._sub_items) - 1:
                    self._sub_cursor += 1
                self._render_page()
                return
            if self._sub_mode == _SUB_FIELD_PICK:
                if self._sub_cursor < len(CARD_FIELD_DEFS) - 1:
                    self._sub_cursor += 1
                self._render_page()
                return
            if self._settings_cursor < len(_SETTINGS_ITEMS) - 1:
                self._settings_cursor += 1
            self._render_page()

    def nav_enter(self):
        if self._page != _PAGE_SETTINGS:
            return
        if self._sub_mode == _SUB_COLOR_MENU:
            if self._sub_cursor < len(_COLOR_MENU_ITEMS):
                color_key, _ = _COLOR_MENU_ITEMS[self._sub_cursor]
                self._color_target = color_key
                self._sub_mode = _SUB_COLOR_PICK
                self._sub_cursor = 0
                self._render_page()
            return
        if self._sub_mode == _SUB_COLOR_PICK:
            self._apply_color()
            return
        if self._sub_mode == _SUB_PATTERN_PICK:
            self._apply_pattern()
            return
        if self._sub_mode == _SUB_FIELD_PICK:
            self._toggle_field()
            return
        if self._delete_step:
            return
        if self._settings_cursor >= len(_SETTINGS_ITEMS):
            return
        action_id, _ = _SETTINGS_ITEMS[self._settings_cursor]
        if action_id == 'edit_motto':
            self._sub_mode = _SUB_MOTTO_INPUT
            self._wants_insert = True
            try:
                log: RichLog = self.query_one("#status-content", RichLog)
                log.clear()
                log.write(RichText.from_markup(
                    f"{M_DIM}输入新签名 (Enter 确认, Esc 取消){M_END}"))
                card = self._player_data.get('profile_card', {}) if self._player_data else {}
                motto = card.get('motto', '')
                if motto:
                    log.write(RichText.from_markup(
                        f"{M_DIM}当前: \"{motto}\"{M_END}"))
            except Exception:
                pass
        elif action_id == 'edit_colors':
            self._sub_mode = _SUB_COLOR_MENU
            self._sub_cursor = 0
            self._render_page()
        elif action_id == 'switch_pattern':
            self._load_owned_patterns()
            self._sub_mode = _SUB_PATTERN_PICK
            self._sub_cursor = 0
            self._render_page()
        elif action_id == 'edit_fields':
            self._sub_mode = _SUB_FIELD_PICK
            self._sub_cursor = 0
            self._render_page()
        elif action_id == 'delete_account':
            self._start_delete()

    def nav_back(self) -> bool:
        if self._wants_insert:
            return False
        if self._sub_mode:
            if self._sub_mode == _SUB_COLOR_PICK:
                self._sub_mode = _SUB_COLOR_MENU
                self._sub_cursor = 0
                self._render_page()
                return True
            self._sub_mode = _SUB_NONE
            self._render_page()
            return True
        if self._page != _PAGE_STATUS:
            self._page = _PAGE_STATUS
            self._render_all()
            return True
        return False

    def nav_escape(self) -> bool:
        if self._wants_insert:
            self.cancel_input()
            return True
        if self._sub_mode:
            self._sub_mode = _SUB_NONE
            self._render_page()
            return True
        return False

    # ── 输入处理 ──

    def on_input_submit(self, text: str):
        text = text.strip()
        if self._sub_mode == _SUB_MOTTO_INPUT:
            self._send_card_update({'motto': text})
            self._sub_mode = _SUB_NONE
            self._wants_insert = False
            self.hide_input_bar()
            self._render_page()
            return
        if self._delete_step == _DEL_CONFIRM:
            name = self._player_data.get('name', '')
            if text != name:
                self._log(f"{M_DIM}用户名不匹配，已取消。{M_END}")
                self._reset_delete()
                return
            self._delete_username = text
            self._delete_step = _DEL_PASSWORD
            self._log(f"{M_DIM}请输入密码：{M_END}")
            self._wants_insert = True
        elif self._delete_step == _DEL_PASSWORD:
            if not text:
                self._log(f"{M_DIM}已取消。{M_END}")
                self._reset_delete()
                return
            try:
                self.app.network.send({
                    "type": "delete_account",
                    "password": text,
                })
            except Exception:
                self._log(f"{M_DIM}发送失败。{M_END}")
            self._reset_delete()

    def cancel_input(self):
        if self._sub_mode == _SUB_MOTTO_INPUT:
            self._sub_mode = _SUB_NONE
            self._wants_insert = False
            self.hide_input_bar()
            self._render_page()
            return
        if self._delete_step:
            self._log(f"{M_DIM}已取消注销。{M_END}")
            self._reset_delete()

    # ── 设置操作 ──

    def _apply_color(self):
        if self._sub_cursor < len(_COLOR_PRESETS):
            color, _ = _COLOR_PRESETS[self._sub_cursor]
            self._send_card_update({self._color_target: color})
        self._sub_mode = _SUB_COLOR_MENU
        self._sub_cursor = 0
        self._render_page()

    def _apply_pattern(self):
        if self._sub_items and self._sub_cursor < len(self._sub_items):
            item = self._sub_items[self._sub_cursor]
            self._send_card_update({'pattern_id': item['id']})
        self._sub_mode = _SUB_NONE
        self._render_page()

    def _send_card_update(self, updates: dict):
        try:
            self.app.network.send({
                'type': 'update_profile_card',
                'data': updates,
            })
        except Exception:
            pass

    def _load_owned_patterns(self):
        """从物品栏找出拥有的花色物品"""
        st = self._state_mgr
        if not st:
            self._sub_items = []
            return
        self._sub_items = [
            item for item in st.inventory.items if item.get('pattern')
        ]

    def _toggle_field(self):
        """切换字段选中状态并立即保存"""
        card = self._player_data.get('profile_card', {}) if self._player_data else {}
        selected = list(card.get('card_fields', DEFAULT_CARD_FIELDS))
        fid = CARD_FIELD_DEFS[self._sub_cursor][0]
        if fid in selected:
            selected.remove(fid)
        elif len(selected) < 4:
            selected.append(fid)
        if self._player_data:
            self._player_data.setdefault('profile_card', {})['card_fields'] = selected
        self._send_card_update({'card_fields': selected})
        self._render_page()

    # ── 删除流程 ──

    def _start_delete(self):
        name = self._player_data.get('name', '?')
        self._delete_step = _DEL_CONFIRM
        self._log(f"{M_DIM}警告：注销账号将永久删除所有数据，不可恢复！{M_END}")
        self._log(f"{M_DIM}请输入用户名 [{name}] 以确认：{M_END}")
        self._wants_insert = True
        self.show_input_bar()

    def _reset_delete(self):
        self._delete_step = _DEL_IDLE
        self._delete_username = ''
        self._wants_insert = False
        self.hide_input_bar()

    def _log(self, markup: str):
        try:
            content: RichLog = self.query_one("#status-content", RichLog)
            content.write(RichText.from_markup(markup))
        except Exception:
            pass

    def on_delete_result(self, message: str):
        """服务端返回删除结果"""
        self._log(f"{M_DIM}{message}{M_END}")

    def on_resize(self, event) -> None:
        self._render_all()

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_player_info':
            (player_data,) = args
            self._player_data = player_data
            self._render_all()
        elif event == 'clear':
            try:
                content: RichLog = self.query_one("#status-content", RichLog)
                content.clear()
            except Exception:
                pass

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        st = state.status
        st.set_listener(self._on_state_event)
        self._page = st.page
        self._settings_cursor = st.settings_cursor
        if st.player_data:
            self._player_data = st.player_data
            self._render_all()

    def on_unmount(self):
        if self._state_mgr:
            st = self._state_mgr.status
            st.page = self._page
            st.settings_cursor = self._settings_cursor
