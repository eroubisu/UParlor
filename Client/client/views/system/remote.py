"""网页手柄（uremote）连接窗口 — 二维码、访问地址与配对状态。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from ...widgets.panel import Panel
from ...widgets.window import Window
from ...window_engine import Divider, Option, WindowSpec, register_window
from ...config import (
    COLOR_FG_PRIMARY,
    COLOR_FG_TERTIARY,
    M_DIM, M_BOLD, M_CMD, M_END, M_MUTED, M_ONLINE, M_OFFLINE,
    NF_CHECK, NF_CROSS,
)
from ...remote.qr import render_qr


class RemotePanel(Panel):
    """左侧二维码 + 右侧地址/配对码/状态。"""

    title = "iOS 连接"
    icon_align = True
    hide_scrollbar = True

    class BackRequested(Message):
        """请求关闭连接浮窗，同时保留网页手柄服务。"""

    def compose_content(self) -> ComposeResult:
        with Vertical(id="remote-layout"):
            with Horizontal(id="remote-columns"):
                yield Static("", id="remote-qr")
                with Vertical(id="remote-details"):
                    yield Static("", id="remote-info", markup=True)
            yield Divider()
            yield Static("", id="remote-action", markup=True)

    def on_mount(self) -> None:
        super().on_mount()
        self.set_options((Option("back", "返回"),), "remote")
        self._redraw()

    def nav(self, action: str) -> None:
        selected = self.selection.handle(action)
        self._redraw_action()
        if selected is not None:
            self.post_message(self.BackRequested())

    def reset_cursor(self) -> None:
        super().reset_cursor()
        self._redraw_action()

    def reflow_content(self) -> None:
        self._redraw_action()

    def redraw(self) -> None:
        """宿主在 remote 状态变化时调用的刷新入口。"""
        self._redraw()

    def _redraw(self) -> None:
        remote = getattr(self.app, "remote", None)
        qr = self.query_one("#remote-qr", Static)
        info = self.query_one("#remote-info", Static)
        if remote is None or remote.state == "off":
            qr.update("")
            info.update(
                f"{M_OFFLINE}{NF_CROSS} 连接已关闭{M_END}\n\n"
                f"{M_DIM}请从设置中重新开启 iOS 连接。{M_END}"
            )
            self._redraw_action()
            return
        qr.update(render_qr(remote.url))
        info.update(self._render_info(remote))
        self._redraw_action()

    def _redraw_action(self) -> None:
        action = self.query_one("#remote-action", Static)
        width = max(action.content_region.width, 10)
        action.update(self.render_options(width=width))

    def _render_info(self, remote) -> str:
        if remote.state == "listening":
            return (
                f"{M_MUTED}等待 iPhone 连接{M_END}\n\n"
                f"{M_BOLD}1  扫描左侧二维码{M_END}\n"
                f"{M_DIM}或在 Safari 中打开{M_END}\n"
                f"{M_CMD}{remote.url}{M_END}\n\n"
                f"{M_BOLD}2  核对配对码{M_END}\n"
                f"{M_BOLD}{remote.pair_code}{M_END}"
            )
        return (
            f"{M_ONLINE}{NF_CHECK} iPhone 已连接{M_END}\n\n"
            f"{M_BOLD}遥控器已就绪{M_END}\n"
            f"{M_DIM}可使用方向键、A、B 和功能键操控。{M_END}\n\n"
            f"{M_MUTED}返回后连接仍会保持。{M_END}"
        )


class RemoteWindow(Window):
    """网页手柄连接浮窗。"""

    DEFAULT_CSS = f"""
    RemoteWindow {{
        layer: floating;
        width: 66;
        height: 21;
    }}
    RemoteWindow > #remote-panel {{
        width: 1fr;
        height: 1fr;
    }}
    RemotePanel > #remote-layout {{
        width: 1fr;
        height: 1fr;
    }}
    RemotePanel #remote-columns {{
        width: 1fr;
        height: 1fr;
    }}
    RemotePanel #remote-qr {{
        width: 33;
        height: 17;
        padding: 1 2;
    }}
    RemotePanel #remote-details {{
        width: 1fr;
        height: 1fr;
        padding: 1;
    }}
    RemotePanel #remote-info {{
        width: 1fr;
        height: 1fr;
        color: {COLOR_FG_TERTIARY};
    }}
    RemotePanel #remote-action {{
        width: 1fr;
        height: 1;
        padding: 0 1;
        color: {COLOR_FG_PRIMARY};
    }}
    """

    focus_grid = [["remote-panel"]]

    spec = WindowSpec(
        id="remote-window", title="iOS 连接",
        group="root", order=55,
    )

    def compose(self) -> ComposeResult:
        yield RemotePanel(id="remote-panel")

    def redraw(self) -> None:
        try:
            self.query_one("#remote-panel", RemotePanel).redraw()
        except Exception:
            pass


register_window(RemoteWindow)
