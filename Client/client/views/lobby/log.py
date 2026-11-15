"""记录面板 — 只读日志：留着全部记录，默认停在最新一条，聚焦后 ↑ ↓ 逐条回看"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from ...widgets.panel import Panel


class LogPanel(Panel):
    """只读日志面板，显示系统消息和指令反馈。

    顶部这一栏只有一行高，但每条记录都留着：每条恰好占一行（放不下的尾部用省略号收住），
    所以聚焦后按一次 ↑ / ↓ 正好翻一条。回看时新记录不会把你拽走，下边框写 `第几条/共几条`；
    翻回最新一条、或者焦点离开这一栏，就又跟着最新记录走。
    """

    # 缩进放在滚动容器上、文字区不留内边距：带内边距的文字区会把省略号吞掉
    DEFAULT_CSS = """
    LogPanel > VerticalScroll.tab {
        padding: 0 1 0 2;
    }
    LogPanel > VerticalScroll.tab > Static.content {
        padding: 0;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    """

    title = "记录"
    hide_scrollbar = True

    def __init__(self, **kw):
        super().__init__(**kw)
        self._state = None
        self._following = True      # 停在最新一条：新记录一来就跟着走

    def _on_state(self, event: str, *args) -> None:
        del args
        if event in ('add_line', 'clear'):
            self._render_lines()

    def bind_state(self, st) -> None:
        self._state = st
        st.cmd.add_listener(self._on_state)
        self._render_lines()

    def _render_lines(self) -> None:
        lines = self._state.cmd.lines
        # 一条记录一行：夹带换行的多行文字并成一行，否则一次 ↑ 会只翻半条
        self.query_one("#t0 .content", Static).update(
            "\n".join(line.replace("\n", " ") for line in lines))
        self.call_after_refresh(self._after_render)

    def _after_render(self) -> None:
        if self._following:
            self._to_tail()
        self._sync_hint()

    def _scroll(self) -> VerticalScroll:
        return self.query_one("#t0", VerticalScroll)

    def _to_tail(self) -> None:
        self._scroll().scroll_end(animate=False, immediate=True)

    def _sync_hint(self) -> None:
        """回看时在下边框写位置；停在最新一条时什么都不写。"""
        total = len(self._state.cmd.lines) if self._state else 0
        if self._following or not total:
            self.border_subtitle = ""
        else:
            self.border_subtitle = f"{self._scroll().scroll_offset.y + 1}/{total}"

    def _follow_tail(self) -> None:
        self._following = True
        self._to_tail()
        self._sync_hint()

    def nav(self, action: str) -> None:
        if action not in ("up", "down"):
            return
        scroll = self._scroll()
        target = scroll.scroll_offset.y + (-1 if action == "up" else 1)
        target = max(0, min(target, scroll.max_scroll_y))
        scroll.scroll_to(y=target, animate=False, force=True, immediate=True)
        self._following = target >= scroll.max_scroll_y
        self._sync_hint()

    def on_panel_blur(self) -> None:
        if not self._following:
            self._follow_tail()

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._follow_tail()
