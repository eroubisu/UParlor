"""StatusPanel — 玩家状态面板"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.widget import Widget

from ..config import MAX_LINES_STATUS, M_BOLD, M_END
from ..state import ModuleStateManager


class StatusPanel(Widget):
    """状态面板：固定显示玩家基本信息"""

    def compose(self) -> ComposeResult:
        yield RichLog(id="status-content", wrap=True, highlight=True, markup=True, max_lines=MAX_LINES_STATUS)

    def _render_player_info(self, player_data: dict):
        try:
            content: RichLog = self.query_one("#status-content", RichLog)
        except Exception:
            return
        content.clear()
        name = player_data.get('name', '?')
        level = player_data.get('level', 1)
        gold = player_data.get('gold', 0)
        title = player_data.get('title', '')
        content.write(f"{M_BOLD}{name}{M_END}")
        if title:
            content.write(f"称号  {title}")
        content.write(f"等级  Lv.{level}")
        content.write(f"金币  {gold}G")

    # ── State listener ──

    def _on_state_event(self, event: str, *args):
        if event == 'update_player_info':
            (player_data,) = args
            self._render_player_info(player_data)
        elif event == 'clear':
            try:
                content: RichLog = self.query_one("#status-content", RichLog)
                content.clear()
            except Exception:
                pass

    def restore(self, state: ModuleStateManager):
        st = state.status
        st.set_listener(self._on_state_event)
        if st.player_data:
            self._render_player_info(st.player_data)
