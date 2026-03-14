"""InventoryPanel — 物品栏面板

状态机:
  BROWSE   — j/k 移动物品光标，Enter 打开操作菜单
  ACTION   — j/k 在四个固定操作间移动，Enter 执行
  USE_SUB  — 物品有多种使用方式时的子菜单，Enter 执行
  DETAIL   — 显示物品描述
  INPUT    — 需要文字输入的操作（如改名卡），进入 INSERT 模式
  GIFT     — 赠送物品时选择在线玩家
  CONFIRM  — 丢弃物品的确认提示

导航: Backspace 返回上一级，Esc 直接回到 BROWSE
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static
from textual.widget import Widget

from ..config import (
    COLOR_FG_PRIMARY,
    COLOR_FG_SECONDARY,
    COLOR_FG_TERTIARY,
    COLOR_ACCENT,
    COLOR_BORDER_LIGHT,
)
from ..state import ModuleStateManager
from ..widgets.input_bar import InputBar

# 四个固定操作（每个物品都有）
_BASE_ACTIONS: list[tuple[str, str]] = [
    ('use',  '使用'),
    ('gift', '赠送'),
    ('info', '详情'),
    ('drop', '丢弃'),
]

_MODE_BROWSE  = 'browse'
_MODE_ACTION  = 'action'
_MODE_USE_SUB = 'use_sub'
_MODE_DETAIL  = 'detail'
_MODE_INPUT   = 'input'
_MODE_GIFT    = 'gift'
_MODE_CONFIRM = 'confirm'


class InventoryPanel(Widget):
    """物品栏面板：Space 菜单打开，j/k 导航，Enter 操作，Esc 返回"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._mode: str = _MODE_BROWSE
        self._cursor: int = 0
        self._items: list[dict] = []
        self._gold: int = 0
        # ACTION 模式
        self._action_cursor: int = 0
        # USE_SUB 模式
        self._use_methods: list[dict] = []
        self._use_cursor: int = 0
        # INPUT 模式（需要文字输入的操作）
        self._wants_insert: bool = False
        self._pending_cmds: list[str] = []
        self._input_label: str = ''
        # GIFT 模式（赠送选择玩家）
        self._gift_item_id: str = ''
        self._gift_cursor: int = 0
        # CONFIRM 模式（通用确认：丢弃、改名卡等）
        self._confirm_label: str = ''
        self._confirm_cmds: list[str] = []
        # 状态管理器引用（用于获取在线玩家列表）
        self._state_mgr: ModuleStateManager | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="inventory-content")
        yield InputBar("inventory-prompt", id="inventory-input-bar")

    # ── 属性 ──

    @property
    def wants_insert(self) -> bool:
        """keyboard mixin 在 nav_enter 后检查此属性，决定是否进入 INSERT 模式"""
        return self._wants_insert

    # ── 面板导航接口（keyboard mixin 调用）──

    def nav_down(self):
        if self._mode == _MODE_BROWSE:
            if self._items:
                self._cursor = (self._cursor + 1) % len(self._items)
        elif self._mode == _MODE_ACTION:
            self._action_cursor = (self._action_cursor + 1) % len(_BASE_ACTIONS)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor + 1) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            players = self._get_online_players()
            if players:
                self._gift_cursor = (self._gift_cursor + 1) % len(players)
        self._refresh_content()

    def nav_up(self):
        if self._mode == _MODE_BROWSE:
            if self._items:
                self._cursor = (self._cursor - 1) % len(self._items)
        elif self._mode == _MODE_ACTION:
            self._action_cursor = (self._action_cursor - 1) % len(_BASE_ACTIONS)
        elif self._mode == _MODE_USE_SUB:
            if self._use_methods:
                self._use_cursor = (self._use_cursor - 1) % len(self._use_methods)
        elif self._mode == _MODE_GIFT:
            players = self._get_online_players()
            if players:
                self._gift_cursor = (self._gift_cursor - 1) % len(players)
        self._refresh_content()

    def nav_enter(self):
        if self._mode == _MODE_BROWSE:
            if self._items:
                self._action_cursor = 0
                self._mode = _MODE_ACTION
        elif self._mode == _MODE_ACTION:
            self._execute_base_action()
        elif self._mode == _MODE_USE_SUB:
            self._execute_use_method()
        elif self._mode == _MODE_GIFT:
            self._execute_gift()
        elif self._mode == _MODE_CONFIRM:
            self._execute_confirm()
        # DETAIL / INPUT 模式下 Enter 无额外动作
        self._refresh_content()

    def nav_back(self) -> bool:
        """Backspace: 返回上一级。True=已处理，False=已在最顶层。"""
        if self._mode == _MODE_INPUT:
            # INSERT 模式下 backspace 由键盘 mixin 处理，不在此处理
            return False
        if self._mode == _MODE_USE_SUB:
            self._mode = _MODE_ACTION
            self._refresh_content()
            return True
        if self._mode in (_MODE_GIFT, _MODE_CONFIRM):
            self._mode = _MODE_ACTION
            self._refresh_content()
            return True
        if self._mode == _MODE_ACTION:
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode == _MODE_DETAIL:
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        return False

    def nav_escape(self) -> bool:
        """Esc: 直接回到 BROWSE 最顶层。True=已处理，False=已在最顶层。"""
        if self._mode == _MODE_INPUT:
            # INSERT 模式下 Esc 由 action_enter_normal → cancel_input 处理
            self._wants_insert = False
            self._pending_cmds = []
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        if self._mode != _MODE_BROWSE:
            self._mode = _MODE_BROWSE
            self._refresh_content()
            return True
        return False

    # ── 操作执行 ──

    def _execute_base_action(self):
        if not self._items or self._cursor >= len(self._items):
            return
        item = self._items[self._cursor]
        action_id, _ = _BASE_ACTIONS[self._action_cursor]

        if action_id == 'use':
            use_methods = item.get('use_methods', [])
            if not use_methods:
                # 无使用方式 → 显示提示后留在 ACTION
                self._use_methods = []
                self._use_cursor = 0
                self._mode = _MODE_USE_SUB
            else:
                # 不管几种都进子菜单，让玩家看到怎么用
                self._use_methods = use_methods
                self._use_cursor = 0
                self._mode = _MODE_USE_SUB
        elif action_id == 'gift':
            self._gift_item_id = item['id']
            self._gift_cursor = 0
            self._mode = _MODE_GIFT
        elif action_id == 'info':
            self._mode = _MODE_DETAIL
        elif action_id == 'drop':
            self._confirm_label = f"确认丢弃 {item.get('name', item['id'])} x1？"
            self._confirm_cmds = [f"/drop {item['id']}", '/y']
            self._mode = _MODE_CONFIRM

    def _execute_use_method(self):
        if not self._use_methods or not self._items:
            return
        item = self._items[self._cursor]
        method = self._use_methods[self._use_cursor]
        input_prompt = method.get('input_prompt')
        if input_prompt:
            # 需要文字输入（如改名卡）→ 进入 INPUT 模式
            self._pending_cmds = [f"/use {item['id']} {method['id']}"]
            self._input_label = input_prompt
            self._wants_insert = True
            self._mode = _MODE_INPUT
        else:
            self._send_command(f"/use {item['id']} {method['id']}")
            self._mode = _MODE_BROWSE

    def _execute_gift(self):
        players = self._get_online_players()
        if not players:
            self._mode = _MODE_ACTION
            return
        target = players[self._gift_cursor]
        self._send_command(f"/gift {self._gift_item_id}")
        self._send_command(target)
        self._mode = _MODE_BROWSE

    def _execute_confirm(self):
        for cmd in self._confirm_cmds:
            self._send_command(cmd)
        self._confirm_cmds = []
        self._confirm_label = ''
        self._mode = _MODE_BROWSE

    def _send_command(self, cmd: str):
        try:
            self.app.send_command(cmd)
        except Exception:
            pass

    def _get_online_players(self) -> list[str]:
        """从在线状态中获取玩家名列表"""
        if not self._state_mgr:
            return []
        names = []
        for u in self._state_mgr.online.users:
            if isinstance(u, dict):
                names.append(u.get('name', str(u)))
            else:
                names.append(str(u))
        return names

    # ── INSERT 模式接口（screen / keyboard mixin 调用）──

    def show_prompt(self, text: str = ""):
        bar = self._input_bar()
        if bar:
            bar.add_class("visible")
            bar.show_prompt(text)

    def update_prompt(self, text: str):
        bar = self._input_bar()
        if bar:
            bar.update_prompt(text)

    def hide_prompt(self):
        bar = self._input_bar()
        if bar:
            bar.hide_prompt()
            bar.remove_class("visible")

    def cancel_input(self):
        """从 INSERT 模式取消回到 USE_SUB（由 action_enter_normal 调用）"""
        if self._mode == _MODE_INPUT:
            self._wants_insert = False
            self._pending_cmds = []
            self._mode = _MODE_USE_SUB
            self._refresh_content()

    def on_input_submit(self, text: str):
        """INSERT 模式下 Enter 提交（由 _submit_input 调用）"""
        if self._mode != _MODE_INPUT:
            return
        self._wants_insert = False
        # 进入 CONFIRM 模式，让用户在物品栏内确认
        self._confirm_label = f"{self._input_label} '{text}'"
        self._confirm_cmds = list(self._pending_cmds) + [text, '/y']
        self._pending_cmds = []
        self._mode = _MODE_CONFIRM
        self._refresh_content()

    def _input_bar(self):
        try:
            return self.query_one("#inventory-input-bar", InputBar)
        except Exception:
            return None

    # ── 渲染 ──

    def _refresh_content(self):
        try:
            content: Static = self.query_one("#inventory-content", Static)
        except Exception:
            return

        if not self._items:
            content.update(
                f"[{COLOR_FG_SECONDARY}]金币  {self._gold}G[/]\n\n"
                f"[{COLOR_FG_TERTIARY}](背包空空如也)[/]"
            )
            return

        lines = [
            f"[{COLOR_FG_SECONDARY}]金币  {self._gold}G[/]",
            f"[{COLOR_BORDER_LIGHT}]{'─' * 20}[/]",
        ]

        for i, item in enumerate(self._items):
            selected = (i == self._cursor)
            name = item.get('name', item['id'])
            count = item.get('count', 0)

            if selected:
                marker = f"[{COLOR_ACCENT}]●[/]"
                text = f"[bold {COLOR_FG_PRIMARY}]{name}[/]  [{COLOR_FG_SECONDARY}]x{count}[/]"
            else:
                marker = " "
                text = f"[{COLOR_FG_SECONDARY}]{name}[/]  [{COLOR_FG_TERTIARY}]x{count}[/]"

            lines.append(f" {marker} {text}")

            # 选中项下方展开子内容
            if not selected:
                continue

            if self._mode == _MODE_ACTION:
                for ai, (_, label) in enumerate(_BASE_ACTIONS):
                    if ai == self._action_cursor:
                        lines.append(f"     [{COLOR_ACCENT}]●[/] [b]{label}[/b]")
                    else:
                        lines.append(f"       [{COLOR_FG_SECONDARY}]{label}[/]")

            elif self._mode == _MODE_USE_SUB:
                if not self._use_methods:
                    lines.append(f"     [{COLOR_FG_TERTIARY}]此物品无法使用[/]")
                else:
                    for ui, method in enumerate(self._use_methods):
                        if ui == self._use_cursor:
                            lines.append(f"       [{COLOR_ACCENT}]●[/] [b]{method['name']}[/b]")
                        else:
                            lines.append(f"         [{COLOR_FG_SECONDARY}]{method['name']}[/]")

            elif self._mode == _MODE_INPUT:
                lines.append(f"     [{COLOR_FG_SECONDARY}]{self._input_label}[/]")

            elif self._mode == _MODE_GIFT:
                players = self._get_online_players()
                if not players:
                    lines.append(f"     [{COLOR_FG_TERTIARY}]无在线玩家[/]")
                else:
                    for pi, pname in enumerate(players):
                        if pi == self._gift_cursor:
                            lines.append(f"     [{COLOR_ACCENT}]●[/] [b]{pname}[/b]")
                        else:
                            lines.append(f"       [{COLOR_FG_SECONDARY}]{pname}[/]")

            elif self._mode == _MODE_CONFIRM:
                lines.append(f"     [{COLOR_FG_SECONDARY}]{self._confirm_label}[/]")
                lines.append(f"     [{COLOR_FG_TERTIARY}]Enter 确认 / Esc 取消[/]")

            elif self._mode == _MODE_DETAIL:
                desc = item.get('desc') or '无描述'
                lines.append(f"     [{COLOR_FG_SECONDARY}]{desc}[/]")

        content.update("\n".join(lines))

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_inventory':
            self._sync_from_state()

    def _sync_from_state(self):
        """从 InventoryState 同步数据"""
        st = self._state
        self._items = list(st.items)
        self._gold = st.gold
        if self._cursor >= len(self._items):
            self._cursor = max(0, len(self._items) - 1)
        self._mode = _MODE_BROWSE
        self.call_after_refresh(self._refresh_content)

    def restore(self, state: ModuleStateManager):
        self._state_mgr = state
        self._state = state.inventory
        self._state.set_listener(self._on_state_event)
        self._sync_from_state()
