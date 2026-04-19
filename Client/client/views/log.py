"""记录面板 — 只读日志，显示服务端推送的消息"""

from __future__ import annotations

from textual.containers import VerticalScroll

from ..widgets.panel import Panel


class LogPanel(Panel):
    """只读日志面板，显示系统消息和指令反馈"""

    title = "记录"
    hide_scrollbar = True

    def append(self, text: str, tab: int | None = None) -> None:
        """追加消息并强制滚动到最新（覆盖父类的 at_bottom 检测）"""
        super().append(text, tab)
        tab = self._active if tab is None else tab
        vs = self.query_one(f"#t{tab}", VerticalScroll)
        vs.scroll_end(animate=False)

    def _on_state(self, event: str, *args):
        match event:
            case 'add_line':
                text, _kw = args
                self.append(text)
            case 'clear':
                self.update("")

    def bind_state(self, st) -> None:
        st.cmd.add_listener(self._on_state)
        # 恢复已有内容
        if st.cmd.lines:
            self.update("\n".join(st.cmd.lines))
