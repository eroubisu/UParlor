"""RemoteController — 网页手柄的本地服务与按键接收。

职责边界：
- 线程安全的状态机（off / listening / connected）
- 在局域网启动一个本地 HTTP 服务，供 iPhone 浏览器打开手柄页面
- 页面通过 GET /status 拉取状态与配对码，通过 POST /key、/confirm 交互
- 校验按键后通过 ``on_key`` 回调交给宿主注入
"""

from __future__ import annotations

import http.server
import json
import random
import socket
import threading
from collections import deque

from .keys import sanitize_text, validate_key
from .page import INDEX_HTML


def _local_ip() -> str:
    """探测本机在局域网内的 IP，失败时回退到回环地址。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class _Handler(http.server.BaseHTTPRequestHandler):
    """手柄页面的 HTTP 处理器。"""

    @property
    def _remote(self) -> "RemoteController":
        return self.server.controller  # type: ignore[attr-defined]

    def log_message(self, fmt, *args) -> None:
        pass  # 静默访问日志

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send_page()
        elif self.path == "/status":
            self._send_json(self._remote.status_dict())
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/key":
            payload = self._read_json()
            key = payload.get("key")
            if isinstance(key, str) and validate_key(key):
                callback = self._remote.on_key
                if callback:
                    callback(key)
                self._send_json({"ok": True})
            else:
                self._send_json(
                    {"ok": False, "error": "invalid key"}, status=400,
                )
        elif self.path == "/text":
            payload = self._read_json()
            text = sanitize_text(payload.get("text") or "")
            if text:
                callback = self._remote.on_text
                if callback:
                    callback(text)
            if payload.get("submit"):
                key_callback = self._remote.on_key
                if key_callback:
                    key_callback("enter")
            self._send_json({"ok": True})
        elif self.path == "/confirm":
            self._remote.confirm()
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, status=404)

    def _send_page(self) -> None:
        data = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except (ValueError, TypeError):
            return {}


class RemoteController:
    """网页手柄连接管理器。线程安全，可在后台线程回调。"""

    STATE_OFF = "off"
    STATE_LISTENING = "listening"
    STATE_CONNECTED = "connected"

    def __init__(self) -> None:
        self._state = self.STATE_OFF
        self._server = None
        self._host = "127.0.0.1"
        self._port = 0
        self._pair_code = ""
        self._records: deque[str] = deque(maxlen=10)
        self._lock = threading.Lock()
        self.on_state_change = None  # callable(state: str)
        self.on_key = None           # callable(key: str)
        self.on_text = None          # callable(text: str)

    # ── 只读属性 ──

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def pair_code(self) -> str:
        with self._lock:
            return self._pair_code

    @property
    def url(self) -> str:
        with self._lock:
            host = self._host
            port = self._port
        return f"http://{host}:{port}" if port else ""

    # ── 状态迁移 ──

    def _set_state(self, state: str) -> None:
        changed = False
        with self._lock:
            if self._state != state:
                self._state = state
                changed = True
        if changed:
            callback = self.on_state_change
            if callback:
                callback(state)

    # ── 生命周期 ──

    def enable(self) -> None:
        """开启：启动本地 HTTP 服务并生成配对码。"""
        if self.state != self.STATE_OFF:
            return
        try:
            server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), _Handler)
        except OSError as exc:
            raise RuntimeError(f"无法启动网页服务: {exc}") from exc
        server.controller = self  # type: ignore[attr-defined]

        with self._lock:
            self._server = server
            self._host = _local_ip()
            self._port = server.server_address[1]
            self._pair_code = f"{random.randint(0, 9999):04d}"
        self._set_state(self.STATE_LISTENING)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def disable(self) -> None:
        """关闭：停止 HTTP 服务。"""
        with self._lock:
            server = self._server
            self._server = None
            self._port = 0
            self._pair_code = ""
            self._records.clear()
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
        self._set_state(self.STATE_OFF)

    def confirm(self) -> None:
        """HTTP 处理器线程调用：确认配对码。"""
        if self.state == self.STATE_LISTENING:
            self._set_state(self.STATE_CONNECTED)

    def record(self, text: str, update_last: bool = False) -> None:
        """记录一条记录面板行，供网页手柄展示（线程安全）。"""
        if self.state == self.STATE_OFF:
            return
        with self._lock:
            if update_last and self._records:
                self._records[-1] = text
            else:
                self._records.append(text)

    def status_dict(self) -> dict:
        """HTTP 处理器线程调用：返回状态、配对码与记录。"""
        with self._lock:
            return {
                "state": self._state,
                "code": self._pair_code,
                "records": list(self._records),
            }
