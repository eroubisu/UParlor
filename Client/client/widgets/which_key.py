"""WhichKeyPanel — vim which-key 风格快捷键提示浮层"""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import Static
from textual.app import ComposeResult
from rich.table import Table

from ..config import COLOR_HINT_TAB_DIM, COLOR_FG_PRIMARY


# ── 菜单定义 ──

_ROOT_ITEMS = [
    ('c', '聊天'),
    ('o', '在线'),
    ('n', '通知'),
    ('g', '游戏'),
    ('s', '设置'),
]

def _render_items(items: list[tuple[str, str]]) -> Table:
    """渲染 key→desc 列表为 Rich Table"""
    table = Table(
        show_header=False, show_edge=False,
        box=None, expand=True, padding=(0, 0), pad_edge=False,
    )
    table.add_column(width=4, no_wrap=True)
    table.add_column(justify="right", no_wrap=True)
    for key, desc in items:
        table.add_row(
            f"[bold {COLOR_FG_PRIMARY}]{key}[/]",
            f"[{COLOR_HINT_TAB_DIM}]{desc}[/]",
        )
    return table


class WhichKeyPanel(Vertical):
    """Space 触发的快捷键提示浮层"""

    def compose(self) -> ComposeResult:
        yield Static("", id="wk-content")

    def show_root(self) -> None:
        """显示根级菜单"""
        self.border_title = "快捷键"
        self.query_one("#wk-content", Static).update(_render_items(_ROOT_ITEMS))
        self.add_class("visible")

    def hide(self) -> None:
        """隐藏浮层"""
        self.remove_class("visible")
