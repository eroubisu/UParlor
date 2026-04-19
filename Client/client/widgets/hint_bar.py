"""CommandHintBar — 指令菜单（p 键触发 / select_menu 自动弹出）"""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Static
from textual.app import ComposeResult

from .tab_menu import TabMenuBase
from ..config import COLOR_HINT_TAB_ACTIVE


class CommandHintBar(TabMenuBase):
    """标签式指令选择菜单 — 继承 TabMenuBase。

    两种来源：
      1. 位置指令（p 键手动打开）— update_commands() 写入
      2. select_menu（服务端推送自动弹出）— show_select_menu() 写入
    """

    _tabs_widget_id = "hint-tabs"
    _content_widget_id = "hint-content"

    class Opened(Message):
        """hint bar 需要打开（请求 Screen 切换到 hint 模式）"""

    class Selected(Message):
        """用户选中了一条指令"""
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    class Closed(Message):
        """hint bar 关闭"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._command_tabs: list[tuple[str, list]] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="hint-tabs")
        yield Static("", id="hint-content")

    # ── 数据源 ──

    def update_commands(self, tabs: list[tuple[str, list]]) -> None:
        """更新位置指令标签页（不自动打开）"""
        self._command_tabs = tabs
        # 如果当前在根级别（没有导航栈），刷新显示
        if not self._nav_stack:
            self.update_tabs(tabs)

    def show_select_menu(self, *, title: str, items: list[dict],
                         empty_msg: str = '') -> None:
        """显示服务端推送的选择菜单（自动弹出）"""
        if not items:
            return
        # 保存当前状态，推入选择菜单
        self._push_stack()
        self._tabs = [(title, items)]
        self._active_tab = 0
        self._selected_idx = 0
        self._scroll_offset = 0
        self._refresh_display()
        self.add_class('visible')
        self.post_message(self.Opened())

    def close(self) -> None:
        """关闭 hint bar，重置到根菜单。"""
        self.remove_class('visible')
        self._nav_stack.clear()
        self.update_tabs(self._command_tabs)
        self.post_message(self.Closed())

    # ── 选择 ──

    def select(self) -> None:
        """Enter 键：选中当前项（或进入子菜单）"""
        item = self.enter()  # TabMenuBase 处理子菜单钻入
        if item is None:
            return  # 进入了子菜单
        command = item.get('command', '') if isinstance(item, dict) else item.command
        if command:
            self.post_message(self.Selected(command))

    def go_back(self) -> bool:
        """Backspace：返回上级子菜单。返回 False 表示已在根级。"""
        return self.back()

    # ── TabMenuBase 钩子 ──

    def _item_name(self, item) -> str:
        if isinstance(item, dict):
            return item.get('label', '')
        return f"[bold {COLOR_HINT_TAB_ACTIVE}]{item.label}[/]" if item.label else item.command

    def _item_desc(self, item) -> str:
        if isinstance(item, dict):
            return item.get('desc', '')
        return item.description

    def _item_sub(self, item) -> list | None:
        if isinstance(item, dict):
            return item.get('sub', None)
        return item.sub

    def _make_sub_tab(self, item) -> tuple[str, list]:
        if isinstance(item, dict):
            label = item.get('label', '子菜单')
            return (label, item.get('sub', []))
        return (item.label or '子菜单', item.sub or [])
