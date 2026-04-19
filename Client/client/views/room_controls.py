"""房间操作面板 — 光标选择指令列表 + select_menu 子菜单"""

from __future__ import annotations

from ..config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END,
)
from ..widgets.panel import Panel


class RoomControlsPanel(Panel):
    """操作面板：光标选择 → Enter 发送指令，支持 select_menu 子菜单栈"""

    title = "操作"
    icon_align = True
    follow_focus = True

    # 需要确认的指令前缀
    _CONFIRM_PREFIXES = ('/invite @', '/kick @')

    def __init__(self, **kw):
        super().__init__(**kw)
        self._send = None
        self._items: list[dict] = []   # [{'label', 'desc', 'command'}]
        self._stack: list[tuple[str, list[dict], int]] = []  # [(title, items, cursor)]
        self._confirming: str = ''   # 待确认的指令

    def bind_send(self, send_fn) -> None:
        self._send = send_fn

    # 游戏操作在棋盘内交互，不在右侧面板显示
    _BOARD_COMMANDS = {'/play', '/draw', '/uno', '/pass', '/challenge'}

    def update_commands(self, tabs: list[tuple[str, list]]) -> None:
        """从 get_game_tabs() 结果刷新操作列表（仅在根级别时刷新）"""
        items = []
        for _tab_name, cmds in tabs:
            for cmd in cmds:
                if cmd.type == 'separator':
                    items.append({'type': 'separator'})
                    continue
                if cmd.command in self._BOARD_COMMANDS:
                    continue
                items.append({
                    'label': cmd.label or cmd.command,
                    'desc': cmd.description,
                    'command': cmd.command,
                })
        if self._stack:
            # 在子菜单中，更新底层数据但不刷新显示
            self._items = items
            return
        self._items = items
        self._cursor = min(self._cursor, max(len(items) - 1, 0))
        self._redraw()

    def _is_selectable(self, item: dict) -> bool:
        return item.get('type', 'option') not in ('text', 'separator')

    def _first_selectable(self) -> int:
        for i, item in enumerate(self._items):
            if self._is_selectable(item):
                return i
        return 0

    def _next_selectable(self, start: int, direction: int) -> int:
        idx = start + direction
        while 0 <= idx < len(self._items):
            if self._is_selectable(self._items[idx]):
                return idx
            idx += direction
        return start

    def show_select_menu(self, *, title: str, items: list[dict],
                         empty_msg: str = '') -> None:
        """显示服务端推送的选择菜单（推入子菜单栈）"""
        if not items:
            return
        self._stack.append((self.title, self._items, self._cursor))
        self.title = title
        self._items = items
        self._cursor = self._first_selectable()
        self._redraw()

    def _pop_stack(self) -> bool:
        """弹出子菜单栈，恢复上一级列表。返回 False 表示已在根级。"""
        if not self._stack:
            return False
        self.title, self._items, self._cursor = self._stack.pop()
        self._redraw()
        return True

    def _redraw(self) -> None:
        if self._confirming:
            self._redraw_confirm()
            return
        if not self._items:
            self.update(f"{ICON_INDENT}{M_DIM}暂无可用操作{M_END}")
            return
        lines: list[str] = []
        has_sep = False
        for i, item in enumerate(self._items):
            item_type = item.get('type', 'option')
            if item_type == 'separator':
                lines.append(self._separator_line(COLOR_HINT_TAB_DIM))
                has_sep = True
            elif item_type == 'text':
                lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{item.get('label', '')}[/]")
            elif i == self._cursor:
                lines.append(f"[bold {COLOR_FG_PRIMARY}]> {item['label']}[/]")
            else:
                lines.append(f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{item['label']}[/]")
        self.update("\n".join(lines))
        self._focus_line = self._cursor
        if has_sep and self._content_width() <= 1:
            self.call_after_refresh(self._redraw)

    def _redraw_confirm(self) -> None:
        """绘制确认对话框"""
        cmd = self._confirming
        if cmd == '/back':
            msg = "确认退出房间?"
        elif '@' in cmd:
            name = cmd.split('@', 1)[1].strip()
            if cmd.startswith('/invite'):
                msg = f"确认邀请 {name}?"
            elif cmd.startswith('/kick'):
                msg = f"确认踢出 {name}?"
            else:
                msg = f"确认执行?"
        else:
            msg = f"确认执行?"
        self.update(self._render_confirm(msg))

    def reset_cursor(self) -> None:
        if self._stack:
            self.title, self._items, _ = self._stack[0]
            self._stack.clear()
        super().reset_cursor()
        self._redraw()

    def _needs_confirm(self, cmd: str) -> bool:
        return any(cmd.startswith(prefix) for prefix in self._CONFIRM_PREFIXES)

    def nav(self, action: str) -> None:
        # 确认状态处理
        if self._confirming:
            def _on_yes():
                if self._send:
                    self._send(self._confirming)
                self._confirming = ''
                if self._stack:
                    self.title, self._items, self._cursor = self._stack[0]
                    self._stack.clear()
                self._redraw()
            def _on_dismiss():
                self._confirming = ''
                self._redraw()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._redraw()
            return
        if action == "up":
            nxt = self._next_selectable(self._cursor, -1)
            if nxt != self._cursor:
                self._cursor = nxt
                self._redraw()
        elif action == "down":
            nxt = self._next_selectable(self._cursor, 1)
            if nxt != self._cursor:
                self._cursor = nxt
                self._redraw()
        elif action == "enter":
            if not self._items:
                return
            item = self._items[self._cursor]
            # 子菜单项
            if item.get('sub'):
                self._stack.append((self.title, self._items, self._cursor))
                self.title = item.get('label', '子菜单')
                self._items = item['sub']
                self._cursor = 0
                self._redraw()
                return
            cmd = item.get('command', '')
            if not cmd:
                # 空指令 = 取消/返回上级
                self._pop_stack()
                return
            if cmd and self._needs_confirm(cmd):
                self._confirming = cmd
                self._confirm_cursor = 0
                self._redraw()
                return
            # 普通指令
            if self._send and cmd:
                self._send(cmd)
                # 选中后弹出子菜单栈恢复根列表
                if self._stack:
                    self.title, self._items, self._cursor = self._stack[0]
                    self._stack.clear()
                    self._redraw()
        elif action == "escape":
            self._pop_stack()
