"""
UParlorApp — 游戏大厅 TUI 主应用入口
"""

from __future__ import annotations

import json

from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static
from textual import work

from .config import (
    PORT, M_DIM, M_END,
    COLOR_FG_PRIMARY, COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    COLOR_ACCENT, COLOR_BORDER, COLOR_BORDER_LIGHT,
)
from .net.connection import NetworkManager
from .ui.vim_mode import VimMode
from .ui.screen import GameScreen
from .panels import LoginPanel, CommandPanel
from .net.dispatch import dispatch_server_message

try:
    from .config import VERSION
except ImportError:
    VERSION = None


# ═══════════════════════════════════════════════════════
#  自定义消息
# ═══════════════════════════════════════════════════════

class ServerMsg(Message):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data


class Disconnected(Message):
    pass


# ═══════════════════════════════════════════════════════
#  UParlorApp — 主应用
# ═══════════════════════════════════════════════════════

class UParlorApp(App):
    """UParlor — 终端游戏厅 TUI 客户端"""

    TITLE = "UParlor"
    CSS_PATH = "theme.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", show=True, priority=True),
    ]

    def get_css_variables(self) -> dict[str, str]:
        variables = super().get_css_variables()
        variables.update({
            "color-fg-primary": COLOR_FG_PRIMARY,
            "color-fg-secondary": COLOR_FG_SECONDARY,
            "color-fg-tertiary": COLOR_FG_TERTIARY,
            "color-accent": COLOR_ACCENT,
            "color-border": COLOR_BORDER,
            "color-border-light": COLOR_BORDER_LIGHT,
        })
        return variables

    def __init__(self, **kw):
        super().__init__(ansi_color=True, **kw)
        self.network = NetworkManager(PORT)
        self.vim = VimMode()
        self.player_data: dict = {}
        self._pending_messages: list[dict] = []
        self._current_channel = 1
        self._saved_layout: dict | None = None

    def on_mount(self) -> None:
        self.push_screen(GameScreen())
        self.set_interval(60, self._ai_tick)

    # ── 网络 ──

    def connect_to_server(self, ip: str):
        screen = self.screen
        try:
            self.network.connect(ip)
        except Exception as e:
            if isinstance(screen, GameScreen):
                login = screen._get_module('login')
                if isinstance(login, LoginPanel):
                    login.add_message(f"{M_DIM}连接失败: {e}{M_END}")
            return

        self._start_receive_worker()

        for msg in self._pending_messages:
            self.post_message(ServerMsg(msg))
        self._pending_messages.clear()

    @work(thread=True)
    def _start_receive_worker(self):
        buffer = ""
        while self.network.connected:
            try:
                data = self.network.socket.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    msg_str, buffer = buffer.split("\n", 1)
                    if msg_str:
                        try:
                            msg = json.loads(msg_str)
                            self.post_message(ServerMsg(msg))
                        except Exception:
                            pass
            except Exception:
                break

        self.network.connected = False
        self.post_message(Disconnected())

    def on_disconnected(self, _msg: Disconnected) -> None:
        screen = self.screen
        if isinstance(screen, GameScreen):
            screen.state.game_board.clear()
            board = screen._get_module('game_board')
            if board and hasattr(board, 'clear'):
                board.clear()
            login = screen._get_module('login')
            if isinstance(login, LoginPanel):
                login.add_message(f"{M_DIM}连接已断开{M_END}")
            else:
                screen.state.cmd.add_line(f"{M_DIM}连接已断开{M_END}")
                cmd = screen._get_module('cmd')
                if isinstance(cmd, CommandPanel):
                    cmd.add_message(f"{M_DIM}连接已断开{M_END}")
            try:
                conn = screen.query_one("#connection-status", Static)
                conn.update("已断开")
            except Exception:
                pass

    # ── 消息处理 ──

    def on_server_msg(self, event: ServerMsg) -> None:
        screen = self.screen
        if not isinstance(screen, GameScreen):
            self._pending_messages.append(event.data)
            return
        dispatch_server_message(self, screen, event.data)

    # ── 发送 ──

    def send_command(self, text: str):
        self.network.send({"type": "command", "text": text})

    def send_chat(self, text: str, channel: int):
        self.network.send({"type": "chat", "text": text, "channel": channel})

    def switch_channel(self, channel_id: int):
        self._current_channel = channel_id
        self.network.send({"type": "switch_channel", "channel": channel_id})

    # ── 退出 ──

    def action_quit(self) -> None:
        self._cleanup_ai()
        self.network.disconnect()
        self.exit()

    def _ai_tick(self):
        """60s 定时器 — 检查 AI 主动搭话"""
        screen = self.screen
        if not isinstance(screen, GameScreen):
            return
        try:
            panel = screen._get_module('ai')
            if not panel or not hasattr(panel, '_service'):
                return
            if not getattr(panel, '_panel_active', False):
                return
            svc = panel._service
            if not svc:
                return
            reason = svc.tick()
            if reason:
                import asyncio
                asyncio.create_task(panel.handle_proactive(reason))
        except Exception:
            pass

    def _cleanup_ai(self):
        screen = self.screen
        if not isinstance(screen, GameScreen):
            return
        try:
            panel = screen._get_module('ai')
            if panel and hasattr(panel, '_service') and panel._service:
                panel._service.on_exit()
        except Exception:
            pass


def _check_version() -> bool:
    """检查是否最新版，返回 True 表示可以启动"""
    current = VERSION or "0.0.0"
    print(f"uparlor v{current}")
    print("正在检查更新...")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://pypi.org/pypi/uparlor/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            latest = json.loads(resp.read().decode())["info"]["version"]
        cur = tuple(int(x) for x in current.split("."))
        lat = tuple(int(x) for x in latest.split("."))
        if lat > cur:
            print(f"\n发现新版本 v{latest}（当前 v{current}），请更新后启动:\n")
            print(f"  pip install --upgrade uparlor\n")
            return False
        else:
            print("已是最新版本\n")
    except Exception:
        pass
    return True


def main():
    """CLI 入口点"""
    if not _check_version():
        return
    app = UParlorApp()
    app.run()
