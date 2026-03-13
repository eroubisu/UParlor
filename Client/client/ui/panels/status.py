"""StatusPanel — 玩家状态面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ...state import ModuleStateManager


class StatusPanel(Widget):
    """状态面板：固定显示玩家基本信息"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="status-content", wrap=True, highlight=True, markup=True, max_lines=500)

    def update_player_info(self, player_data: dict):
        content: RichLog = self.query_one("#status-content", RichLog)
        content.clear()
        name = player_data.get('name', '?')
        level = player_data.get('level', 1)
        gold = player_data.get('gold', 0)
        title = player_data.get('title', '')
        content.write(f"[b]{name}[/b]")
        if title:
            content.write(f"称号  {title}")
        content.write(f"等级  Lv.{level}")
        content.write(f"金币  {gold}G")

    def clear(self):
        content: RichLog = self.query_one("#status-content", RichLog)
        content.clear()

    def restore(self, state: ModuleStateManager):
        st = state.status
        if st.player_data:
            self.update_player_info(st.player_data)
