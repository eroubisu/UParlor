"""StatusPanel — 玩家状态面板（名片 / 状态 / 设置）"""

from __future__ import annotations

from rich.text import Text as RichText
from textual.app import ComposeResult
from textual.widgets import RichLog, Static
from textual.widget import Widget

from ..config import (
    MAX_LINES_STATUS,
    M_DIM, M_END,
)
from ..state import ModuleStateManager
from ..widgets.input_bar import InputBar
from ..widgets.prompt import InputBarMixin
from ._mixins.card import CARD_FIELD_DEFS, DEFAULT_CARD_FIELDS
from ..data import COLOR_PRESETS as _COLOR_PRESETS
from ..data import EQUIPMENT_SLOT_LABELS
from ._mixins.status import (
    StatusRenderMixin,
    _PAGES, _PAGE_STATUS, _PAGE_EQUIP, _PAGE_CARD, _PAGE_SETTINGS, _PAGE_GAME,
    _SETTINGS_ITEMS, _COLOR_MENU_ITEMS,
    _SUB_NONE, _SUB_COLOR_MENU, _SUB_COLOR_PICK, _SUB_PATTERN_PICK,
    _SUB_MOTTO_INPUT, _SUB_FIELD_PICK,
)

# ── 删除流程 ──
_DEL_IDLE = ''
_DEL_CONFIRM = 'confirm'
_DEL_PASSWORD = 'password'

# ── 改密流程 ──
_PW_IDLE = ''
_PW_NEW = 'new'
_PW_CONFIRM = 'confirm'


class StatusPanel(StatusRenderMixin, InputBarMixin, Widget):
    """状态面板：名片 / 状态 / 设置"""

    _input_bar_id = "status-input-bar"
    _scroll_target_id = "status-content"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._player_data: dict = {}
        self._page: str = _PAGE_STATUS
        self._settings_cursor: int = 0
        self._equip_cursor: int = 0
        self._equip_confirm: str = ''
        self._equip_scroll: int = 0
        self._game_cursor: int = 0
        self._game_confirm: str = ''
        self._game_scroll: int = 0
        self._sub_mode: str = _SUB_NONE
        self._sub_cursor: int = 0
        self._sub_items: list = []
        self._color_target: str = ''  # 'name_color' | 'motto_color'
        self._delete_step: str = _DEL_IDLE
        self._delete_username: str = ''
        self._passwd_step: str = _PW_IDLE
        self._passwd_new: str = ''
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

    # ── 导航 ──

    def nav_tab_next(self):
        if self._wants_insert or self._sub_mode:
            return
        pages = self._get_pages()
        idx = pages.index(self._page) if self._page in pages else 0
        self._page = pages[(idx + 1) % len(pages)]
        self._equip_confirm = ''
        self._game_confirm = ''
        self._render_all()

    def nav_tab_prev(self):
        if self._wants_insert or self._sub_mode:
            return
        pages = self._get_pages()
        idx = pages.index(self._page) if self._page in pages else 0
        self._page = pages[(idx - 1) % len(pages)]
        self._equip_confirm = ''
        self._game_confirm = ''
        self._render_all()

    def nav_up(self, count=1):
        for _ in range(count):
            self._nav_up_step()

    def _nav_up_step(self):
        if self._page == _PAGE_EQUIP:
            if self._equip_cursor > 0:
                self._equip_cursor -= 1
                self._equip_confirm = ''
                self._render_page()
            return
        if self._page == _PAGE_GAME:
            if self._game_cursor > 0:
                self._game_cursor -= 1
                self._game_confirm = ''
                self._render_page()
            return
        if self._page in (_PAGE_CARD, _PAGE_STATUS):
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

    def nav_down(self, count=1):
        for _ in range(count):
            self._nav_down_step()

    def _nav_down_step(self):
        if self._page == _PAGE_EQUIP:
            max_idx = len(EQUIPMENT_SLOT_LABELS) - 1
            if self._equip_cursor < max_idx:
                self._equip_cursor += 1
                self._equip_confirm = ''
                self._render_page()
            return
        if self._page == _PAGE_GAME:
            from ..data import GAME_STATUS_CONFIG
            game_type = self._current_game_type()
            slots = GAME_STATUS_CONFIG.get(game_type, {}).get('slots', {}) if game_type else {}
            max_idx = len(slots) - 1
            if self._game_cursor < max_idx:
                self._game_cursor += 1
                self._game_confirm = ''
                self._render_page()
            return
        if self._page in (_PAGE_CARD, _PAGE_STATUS):
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
        if self._page == _PAGE_EQUIP:
            slots = list(EQUIPMENT_SLOT_LABELS.keys())
            if 0 <= self._equip_cursor < len(slots):
                slot_key = slots[self._equip_cursor]
                pd = self._player_data
                equip_data = pd.get('equipment', {}) if pd else {}
                item = equip_data.get(slot_key)
                if item and isinstance(item, dict):
                    if self._equip_confirm == slot_key:
                        try:
                            self.app.network.send({'type': 'unequip', 'slot': slot_key})
                        except Exception:
                            pass
                        self._equip_confirm = ''
                    else:
                        self._equip_confirm = slot_key
                    self._render_page()
            return
        if self._page == _PAGE_GAME:
            from ..data import GAME_STATUS_CONFIG
            game_type = self._current_game_type()
            slots = list((GAME_STATUS_CONFIG.get(game_type, {}).get('slots', {})).keys()) if game_type else []
            if 0 <= self._game_cursor < len(slots):
                slot_key = slots[self._game_cursor]
                pd = self._player_data
                equip_data = pd.get('equipment', {}) if pd else {}
                item = equip_data.get(slot_key)
                if item and isinstance(item, dict):
                    if self._game_confirm == slot_key:
                        try:
                            self.app.network.send({'type': 'unequip', 'slot': slot_key})
                        except Exception:
                            pass
                        self._game_confirm = ''
                    else:
                        self._game_confirm = slot_key
                    self._render_page()
            return
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
        if self._passwd_step:
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
        elif action_id == 'change_password':
            self._start_passwd()

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
        if self._passwd_step == _PW_NEW:
            if len(text) < 6 or len(text) > 20:
                self._log(f"{M_DIM}密码长度需要在6-20个字符之间，已取消。{M_END}")
                self._reset_passwd()
                return
            self._passwd_new = text
            self._passwd_step = _PW_CONFIRM
            self._log(f"{M_DIM}请再次输入新密码确认：{M_END}")
            self._wants_insert = True
            return
        if self._passwd_step == _PW_CONFIRM:
            if text != self._passwd_new:
                self._log(f"{M_DIM}两次输入的密码不一致，已取消。{M_END}")
                self._reset_passwd()
                return
            # 先触发服务端 pending 流程，再发两次密码
            self.app.send_command('/passwd')
            self.app.send_command(self._passwd_new)
            self.app.send_command(self._passwd_new)
            self._reset_passwd()
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
        if self._passwd_step:
            self._log(f"{M_DIM}已取消修改密码。{M_END}")
            self._reset_passwd()
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

    # ── 改密流程 ──

    def _start_passwd(self):
        self._passwd_step = _PW_NEW
        self._log(f"{M_DIM}请输入新密码（6-20个字符）：{M_END}")
        self._wants_insert = True
        self.show_input_bar()

    def _reset_passwd(self):
        self._passwd_step = _PW_IDLE
        self._passwd_new = ''
        self._wants_insert = False
        self.hide_input_bar()

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
        elif event == 'update_location':
            (location,) = args
            # 进入游戏时自动切换到游戏标签页
            pages = self._get_pages()
            if _PAGE_GAME in pages and self._page != _PAGE_GAME:
                self._page = _PAGE_GAME
                self._game_cursor = 0
                self._game_confirm = ''
                self._game_scroll = 0
            elif _PAGE_GAME not in pages and self._page == _PAGE_GAME:
                self._page = _PAGE_STATUS
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
        st.add_listener(self._on_state_event)
        self._page = st.page
        self._settings_cursor = st.settings_cursor
        if st.player_data:
            self._player_data = st.player_data
            self._render_all()

    def on_unmount(self):
        if self._state_mgr:
            self._state_mgr.status.remove_listener(self._on_state_event)
            st = self._state_mgr.status
            st.page = self._page
            st.settings_cursor = self._settings_cursor
