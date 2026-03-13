"""
GameLobbyApp — 游戏大厅 TUI 主应用入口
"""

from __future__ import annotations

import json

from textual.app import App
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static
from textual import work

from .config import PORT
from .network import NetworkManager
from .vim_mode import VimMode
from .ui.screen import GameScreen
from .ui.panels import LoginPanel, CommandPanel
from .msg_dispatch import dispatch_server_message

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
#  GameLobbyApp — 主应用
# ═══════════════════════════════════════════════════════

class GameLobbyApp(App):
    """游戏大厅 TUI 客户端"""

    TITLE = "游戏大厅"
    CSS_PATH = "theme.tcss"

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出", show=True, priority=True),
    ]

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

    # ── 网络 ──

    def connect_to_server(self, ip: str):
        screen = self.screen
        try:
            self.network.connect(ip)
        except Exception as e:
            if isinstance(screen, GameScreen):
                login = screen._get_module('login')
                if isinstance(login, LoginPanel):
                    login.add_message(f"[dim]连接失败: {e}[/]")
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
                login.add_message("[dim]连接已断开[/]")
            else:
                screen.state.cmd.add_line("[dim]连接已断开[/]")
                cmd = screen._get_module('cmd')
                if isinstance(cmd, CommandPanel):
                    cmd.add_message("[dim]连接已断开[/]")
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
        self.network.disconnect()
        self.exit()


def _check_version() -> bool:
    """检查是否最新版，返回 True 表示可以启动"""
    current = VERSION or "0.0.0"
    print(f"gamelobby v{current}")
    print("正在检查更新...")
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://pypi.org/pypi/gamelobby/json",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            latest = json.loads(resp.read().decode())["info"]["version"]
        cur = tuple(int(x) for x in current.split("."))
        lat = tuple(int(x) for x in latest.split("."))
        if lat > cur:
            print(f"\n发现新版本 v{latest}（当前 v{current}）")
            print(f"请运行以下命令更新:\n")
            print(f"  pip install --upgrade gamelobby\n")
    except Exception:
        pass
    print()
    return True


def main():
    """CLI 入口点"""
    if not _check_version():
        return
    app = GameLobbyApp()
    app.run()
