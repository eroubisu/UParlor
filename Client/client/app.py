"""
UParlorApp — 游戏大厅 TUI 主应用入口
"""

from __future__ import annotations

import json
import time

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

# 注册游戏渲染器和处理器（导入即注册）
from . import games as _games  # noqa: F401


# ── 自定义消息 ──

class ServerMsg(Message):
    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data


class Disconnected(Message):
    pass


# ── UParlorApp — 主应用 ──

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
        self._ping_sent_at: float = 0.0
        self._ai_ticking: bool = False

    def on_mount(self) -> None:
        self.push_screen(GameScreen())
        self.set_interval(60, self._ai_tick)
        self.set_interval(4, self._send_ping)

    # ── 网络 ──

    def connect_to_server(self, ip: str):
        screen = self.screen
        try:
            self.network.connect(ip)
        except Exception as e:
            if isinstance(screen, GameScreen):
                login = screen.get_module('login')
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
                            if msg.get('type') == 'pong':
                                self._handle_pong(msg)
                            else:
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
            board = screen.get_module('game_board')
            if board and hasattr(board, 'clear'):
                board.clear()
            login = screen.get_module('login')
            if isinstance(login, LoginPanel):
                login.add_message(f"{M_DIM}连接已断开{M_END}")
            else:
                screen.state.cmd.add_line(f"{M_DIM}连接已断开{M_END}")
                cmd = screen.get_module('cmd')
                if isinstance(cmd, CommandPanel):
                    cmd.add_message(f"{M_DIM}连接已断开{M_END}")
            try:
                conn = screen.query_one("#connection-status", Static)
                conn.update(" ---- ")
            except Exception:
                pass

    # ── Ping ──

    def _send_ping(self):
        if self.network.connected:
            self._ping_sent_at = time.monotonic()
            self.network.send({"type": "ping", "t": self._ping_sent_at})

    def _handle_pong(self, msg: dict):
        if self._ping_sent_at > 0:
            latency_ms = int((time.monotonic() - self._ping_sent_at) * 1000)
            self._ping_sent_at = 0.0
            self.call_from_thread(self._update_ping_display, latency_ms)

    def _update_ping_display(self, ms: int):
        screen = self.screen
        if isinstance(screen, GameScreen):
            try:
                conn = screen.query_one("#connection-status", Static)
                conn.update(f" {ms}ms ")
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
        from .ui import ime
        ime.on_app_blur()
        self._cleanup_ai()
        self.network.disconnect()
        self.exit()

    def _ai_tick(self):
        """定时器 + 快速通道 — 检查 AI 主动搭话"""
        if self._ai_ticking:
            return
        self._ai_ticking = True
        try:
            screen = self.screen
            if not isinstance(screen, GameScreen):
                return
            panel = screen.get_module('ai')
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
        finally:
            self._ai_ticking = False

    def _cleanup_ai(self):
        screen = self.screen
        if not isinstance(screen, GameScreen):
            return
        try:
            panel = screen.get_module('ai')
            if panel and hasattr(panel, '_service') and panel._service:
                panel._service.on_exit()
        except Exception:
            pass

    # ── 窗口焦点 ──

    def on_app_blur(self) -> None:
        """窗口失去焦点 — 恢复中文 IME，避免切出后停留在英文"""
        from .ui import ime
        ime.on_app_blur()

    def on_app_focus(self) -> None:
        """窗口恢复焦点 — 根据当前 vim 模式恢复 IME"""
        from .ui import ime
        from .ui.vim_mode import Mode
        ime.on_app_focus(self.vim.mode == Mode.NORMAL)


def _uninstall():
    """卸载 uparlor：删除外部数据 + pip uninstall"""
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    data_dir = Path.home() / ".uparlor"
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
        print(f"已删除数据目录: {data_dir}")
    else:
        print("无外部数据需要清理")

    print("卸载 uparlor 包...")
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "uparlor", "-y"])
    print("\n卸载完成。")


def _check_update(current: str | None):
    """启动前查 PyPI 最新版，版本不一致或查询失败均阻止启动（dev 版本跳过）"""
    if current and '.dev' in current:
        return
    import json
    import re
    import sys
    import urllib.request

    def _ver_tuple(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.findall(r'\d+', v.split('.dev')[0]))

    try:
        cur = _ver_tuple(current or '0.0.0')
        req = urllib.request.Request(
            'https://pypi.org/pypi/uparlor/json',
            headers={'Accept': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        latest = data['info']['version']
        lat = _ver_tuple(latest)
        if lat > cur:
            print(f"  ★ 发现新版本 v{latest}（当前 v{current or 'dev'}）")
            print(f"  ★ 更新命令: pip install -U uparlor\n")
            sys.exit(0)
    except Exception:
        print("  ✗ 版本检查失败，无法启动。请检查网络连接。\n")
        sys.exit(1)


def main():
    """CLI 入口点"""
    import sys
    if "--uninstall" in sys.argv:
        _uninstall()
        return
    from .config import VERSION
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"uparlor {VERSION or 'dev'}")
        return
    print(f"uparlor v{VERSION or 'dev'}\n")
    _check_update(VERSION)
    app = UParlorApp()
    app.run()
