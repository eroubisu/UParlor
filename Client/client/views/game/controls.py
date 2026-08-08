"""房间操作面板 — 光标选择指令列表 + select_menu 子菜单"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ...config import (
    COLOR_FG_PRIMARY, COLOR_HINT_TAB_DIM, ICON_INDENT,
    M_DIM, M_END,
)
from ...widgets.panel import Panel
from ...window_engine import Divider, Option


class RoomControlsPanel(Panel):
    """操作面板：光标选择 → Enter 发送指令，支持 select_menu 子菜单栈"""

    title = "操作"
    icon_align = True
    follow_focus = True

    # 需要确认的指令前缀
    _CONFIRM_PREFIXES = ('/invite @', '/kick @')

    DEFAULT_CSS = """
    RoomControlsPanel > .tab > #control-items {
        width: 1fr;
        height: auto;
    }
    RoomControlsPanel > .tab > #control-items > .control-row {
        width: 1fr;
        height: 1;
        padding: 0;
    }
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self._send = None
        self._items: list[dict] = []   # [{'label', 'desc', 'command'}]
        self._stack: list[tuple[str, list[dict], str | None]] = []
        self._confirming: str = ''   # 待确认的指令
        self._root_signature: tuple[tuple[str, str], ...] = ()

    def bind_send(self, send_fn) -> None:
        self._send = send_fn

    def compose_content(self) -> ComposeResult:
        with VerticalScroll(classes="tab", id="t0"):
            yield Vertical(id="control-items")

    # 游戏操作在棋盘内交互，不在右侧面板显示
    _BOARD_COMMANDS = {'/play', '/draw', '/uno', '/pass', '/challenge', '/roll', '/move', '/forfeit'}

    def update_commands(self, tabs: list[tuple[str, list]]) -> None:
        """从 get_game_tabs() 结果刷新操作列表（仅在根级别时刷新）"""
        items = []
        for _, cmds in tabs:
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
        new_signature = tuple(
            (item.get('type', 'option'), item.get('command', ''))
            for item in items
        )
        self._root_signature = new_signature
        if self._stack:
            # 在子菜单中，更新底层数据但不刷新显示
            self._items = items
            return
        self._items = items
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
            if empty_msg:
                self.app.notify(empty_msg)
            return
        self._stack.append(
            (self.title, self._items, self.selection.selected_id))
        self.title = title
        self._items = self._with_return_option(items)
        self._redraw()

    @staticmethod
    def _with_return_option(items: list[dict]) -> list[dict]:
        if any(
            item.get("type") == "return"
            or (
                item.get("label") == "返回"
                and not item.get("command")
            )
            for item in items
        ):
            return items
        return [
            *items,
            {"type": "return", "label": "返回", "command": ""},
        ]

    def _pop_stack(self) -> bool:
        """弹出子菜单栈，恢复上一级列表。返回 False 表示已在根级。"""
        if not self._stack:
            return False
        self.title, self._items, selected_id = self._stack.pop()
        self._redraw()
        if selected_id:
            self.selection.select(selected_id)
            self._redraw()
        return True

    def _selection_context(self) -> str:
        if self._stack:
            return f"room-controls:{len(self._stack)}:{self.title}"
        return f"room-controls:root:{self._root_signature}"

    def _sync_options(self) -> None:
        options = []
        for index, item in enumerate(self._items):
            item_type = item.get("type", "option")
            option_id = (
                item.get("command")
                or f"{item_type}:{item.get('label', '')}:{index}"
            )
            options.append(Option(
                option_id,
                item.get("label", ""),
                "",
                enabled=self._is_selectable(item),
                data=item,
            ))
        self.set_options(options, self._selection_context())

    def _redraw(self) -> None:
        if self._confirming:
            self._redraw_confirm()
            return
        if not self._items:
            self._replace_rows([
                f"{ICON_INDENT}{M_DIM}暂无可用操作{M_END}",
            ])
            return
        self._sync_options()
        rows: list[str | None] = []
        for index, item in enumerate(self._items):
            item_type = item.get('type', 'option')
            if item_type == 'separator':
                rows.append(None)
            else:
                rows.extend(self.selection.render_option(
                    self.selection.options[index],
                    self._content_width(),
                    idle_prefix=ICON_INDENT,
                    selected_style=f"bold {COLOR_FG_PRIMARY}",
                    idle_style=COLOR_HINT_TAB_DIM,
                    disabled_style=COLOR_HINT_TAB_DIM,
                ))
        self._replace_rows(rows)
        self._focus_line = self.selected_line()
        self.call_after_refresh(self._scroll_to_cursor)

    def _replace_rows(self, rows: list[str | None]) -> None:
        container = self.query_one("#control-items", Vertical)
        children = list(container.children)
        structure_matches = len(children) == len(rows) and all(
            isinstance(child, Divider) == (row is None)
            for child, row in zip(children, rows)
        )
        if structure_matches:
            for child, row in zip(children, rows):
                if row is not None:
                    child.update(row)
            return
        container.remove_children()
        widgets = [
            Divider() if row is None else Static(
                row, classes="control-row", markup=True)
            for row in rows
        ]
        if widgets:
            container.mount(*widgets)

    def _scroll_to_cursor(self) -> None:
        self.query_one("#t0", VerticalScroll).scroll_to(
            y=max(self._focus_line, 0), animate=False)

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
        if not self.confirmation.is_open:
            self.confirmation.open(
                msg, context_id=f"room-control-confirm:{cmd}")
        self._replace_rows([
            f"[{COLOR_HINT_TAB_DIM}]{ICON_INDENT}{msg}[/]",
            None,
            *self.confirmation.selection.render(
                self._content_width(),
                idle_prefix=ICON_INDENT,
                selected_style=f"bold {COLOR_FG_PRIMARY}",
                idle_style=COLOR_HINT_TAB_DIM,
            ).splitlines(),
        ])

    def reset_cursor(self) -> None:
        if self._stack:
            self.title, self._items, _ = self._stack[0]
            self._stack.clear()
        super().reset_cursor()
        self._redraw()

    def reflow_content(self) -> None:
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
                    self.title, self._items, _ = self._stack[0]
                    self._stack.clear()
                self._redraw()
            def _on_dismiss():
                self._confirming = ''
                self._redraw()
            self._nav_confirm(action, _on_yes, _on_dismiss)
            self._redraw()
            return
        self._sync_options()
        selected = self.selection.handle(action)
        if action in ("up", "down"):
            self._redraw()
        elif selected is not None:
            item = selected.data
            # 子菜单项
            if item.get('sub'):
                self._stack.append(
                    (self.title, self._items, selected.id))
                self.title = item.get('label', '子菜单')
                self._items = self._with_return_option(item['sub'])
                self._redraw()
                return
            cmd = item.get('command', '')
            if not cmd:
                # 空指令 = 取消/返回上级
                self._pop_stack()
                return
            if cmd and self._needs_confirm(cmd):
                self._confirming = cmd

                self._redraw()
                return
            # 普通指令
            if self._send and cmd:
                self._send(cmd)
                # 选中后弹出子菜单栈恢复根列表
                if self._stack:
                    self.title, self._items, _ = self._stack[0]
                    self._stack.clear()
                    self._redraw()
