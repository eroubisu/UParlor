"""网页手柄（uremote）按键协议与控制器测试。"""

import asyncio
import json
import time
import urllib.error
import urllib.request

import pytest

from client.remote import (
    ALLOWED_KEYS,
    RemoteController,
    key_event_args,
    render_qr,
    sanitize_text,
    validate_key,
)


def test_validate_key_accepts_all_control_keys():
    for key in (
        "h", "j", "k", "l",
        "H", "J", "K", "L",
        "i", "I",
        "enter", "escape", "space",
    ):
        assert validate_key(key), key


def test_validate_key_rejects_unknown_keys():
    for key in ("x", "q", "a", "w", "s", "d", "W", "ctrl+c", "shift+h", "",
                "z", "backspace", " "):
        assert not validate_key(key), key


def test_sanitize_text_takes_first_line_and_truncates():
    assert sanitize_text("你好世界") == "你好世界"
    assert sanitize_text("第一行\n第二行") == "第一行"
    assert sanitize_text("a" * 600) == "a" * 500
    assert sanitize_text("") == ""


def test_allowlist_matches_expected_controls():
    assert ALLOWED_KEYS == frozenset({
        "h", "j", "k", "l",
        "H", "J", "K", "L",
        "i", "I",
        "enter", "escape", "space",
    })


def test_key_event_args_single_char():
    assert key_event_args("h") == ("h", "h")
    assert key_event_args("H") == ("H", "H")


def test_key_event_args_named_keys_have_no_character():
    assert key_event_args("enter") == ("enter", None)
    assert key_event_args("escape") == ("escape", None)
    assert key_event_args("space") == ("space", None)


def test_remote_controller_starts_off():
    controller = RemoteController()
    assert controller.state == RemoteController.STATE_OFF
    assert controller.pair_code == ""
    assert controller.url == ""


def _get_json(url: str) -> dict:
    last: Exception | None = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                return json.loads(resp.read())
        except OSError as exc:
            last = exc
            time.sleep(0.1)
    raise last or RuntimeError("无法连接网页服务")


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def test_remote_controller_serves_page_pairing_and_keys():
    keys: list[str] = []
    controller = RemoteController()
    controller.on_key = keys.append
    controller.enable()
    try:
        base = controller.url
        assert controller.state == RemoteController.STATE_LISTENING
        assert len(controller.pair_code) == 4

        status = _get_json(f"{base}/status")
        assert status["state"] == RemoteController.STATE_LISTENING
        assert status["code"] == controller.pair_code

        _post_json(f"{base}/confirm", {})
        status = _get_json(f"{base}/status")
        assert status["state"] == RemoteController.STATE_CONNECTED

        _post_json(f"{base}/key", {"key": "h"})
        assert keys == ["h"]

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _post_json(f"{base}/key", {"key": "ctrl+c"})
        assert exc_info.value.code == 400
        assert keys == ["h"]
    finally:
        controller.disable()
    assert controller.state == RemoteController.STATE_OFF
    assert controller.url == ""


def test_render_qr_returns_halfblock_text():
    qr = render_qr("http://192.168.1.23:3358")
    assert qr
    lines = qr.split("\n")
    assert len(lines) >= 5
    widths = {len(line) for line in lines}
    assert len(widths) == 1
    assert any(ch in qr for ch in ("█", "▀", "▄"))


def test_remote_qr_block_is_white_and_not_clipped():
    """二维码必须是实心白底黑字且完整显示。

    theme.tcss 的 ``Static { background: transparent }`` 会覆盖窗口
    DEFAULT_CSS 里的背景，使二维码变成黑底黑块；窗口尺寸不足还会截掉
    底部静默区。两者都让二维码无法扫描。
    """
    from pathlib import Path

    from textual.app import App, ComposeResult
    from textual.color import ColorTriplet

    from client.config import (
        COLOR_ACCENT, COLOR_BORDER, COLOR_BORDER_LIGHT, COLOR_FG_PRIMARY,
        COLOR_FG_SECONDARY, COLOR_FG_TERTIARY,
    )
    from client.views.system.remote import RemotePanel, RemoteWindow

    theme_path = (
        Path(__file__).resolve().parent.parent / "Client" / "client" / "theme.tcss"
    )

    class _App(App):
        CSS_PATH = str(theme_path)

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

        def compose(self) -> ComposeResult:
            yield RemoteWindow(id="remote-window")

    def _rendered_lines(widget) -> list[str]:
        return [
            "".join(segment.text for segment in widget.render_line(y))
            for y in range(widget.size.height)
        ]

    def _assert_qr_visible(app, qr, controller) -> None:
        lines = render_qr(controller.url).split("\n")

        # 完整显示：二维码文本必须放得进内容区（尺寸随地址长度变化）
        assert len(lines) <= qr.content_region.height
        assert max(len(line) for line in lines) <= qr.content_region.width

        # 实心白底黑字，且每一行都覆盖到
        for y in range(qr.size.height):
            for segment in qr.render_line(y):
                assert segment.style.bgcolor.triplet == ColorTriplet(
                    255, 255, 255)
                assert segment.style.color.triplet == ColorTriplet(0, 0, 0)

        # 二维码的每个非空行都真的画出来了
        drawn = {line.rstrip() for line in _rendered_lines(qr)}
        for line in lines:
            if line.strip():
                assert line.rstrip() in drawn

        # 浏览器里要手输的地址不能被截断
        info_text = "".join(_rendered_lines(app.query_one("#remote-info")))
        assert controller.url in info_text

    async def verify() -> None:
        app = _App()
        async with app.run_test(size=(88, 32)) as pilot:
            controller = RemoteController()
            app.remote = controller
            controller.enable()
            try:
                window = app.query_one("#remote-window", RemoteWindow)
                window.show()
                await pilot.pause()
                panel = app.query_one("#remote-panel", RemotePanel)
                panel.redraw()
                await pilot.pause()

                qr = app.query_one("#remote-qr")
                _assert_qr_visible(app, qr, controller)

                # 中转地址比局域网地址长，二维码会变大：必须跟着放大窗口
                lan_size = qr.content_region.size
                controller.set_relay_url(
                    "http://112.126.80.53:5555/r/kzDGw1674Xm29-dUwFxX3g/")
                window.redraw()
                await pilot.pause()
                _assert_qr_visible(app, qr, controller)
                assert qr.content_region.width > lan_size.width
            finally:
                controller.disable()

    asyncio.run(verify())


def test_remote_record_feeds_status_when_enabled():
    controller = RemoteController()
    controller.record("不该出现")  # off 状态被忽略
    controller.enable()
    try:
        controller.record("第一条记录")
        status = controller.status_dict()
        assert status["records"] == ["第一条记录"]
        controller.record("第二条记录")
        controller.record("覆盖最后一条", update_last=True)
        status = controller.status_dict()
        assert status["records"] == ["第一条记录", "覆盖最后一条"]
    finally:
        controller.disable()


def test_remote_text_endpoint_pastes_and_submits():
    texts: list[str] = []
    keys: list[str] = []
    controller = RemoteController()
    controller.on_text = texts.append
    controller.on_key = keys.append
    controller.enable()
    try:
        base = controller.url
        _post_json(f"{base}/confirm", {})
        _post_json(f"{base}/text", {"text": "你好，世界", "submit": True})
        assert texts == ["你好，世界"]
        assert keys == ["enter"]
    finally:
        controller.disable()


def test_remote_handle_rejects_keys_before_pairing():
    """未确认配对码前，页面不能向游戏注入任何按键。"""
    keys: list[str] = []
    controller = RemoteController()
    controller.on_key = keys.append
    controller.enable()
    try:
        base = controller.url
        for path, payload in (("/key", {"key": "h"}),
                              ("/text", {"text": "hi", "submit": True})):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                _post_json(f"{base}{path}", payload)
            assert exc_info.value.code == 403
        assert keys == []

        _post_json(f"{base}/confirm", {})
        _post_json(f"{base}/key", {"key": "h"})
        assert keys == ["h"]
    finally:
        controller.disable()


def test_remote_url_prefers_relay_and_resets_with_lifecycle():
    controller = RemoteController()
    controller.enable()
    try:
        assert controller.relay_available is False
        assert controller.url.startswith("http://")
        assert "/r/" not in controller.url

        controller.set_relay_url("http://203.0.113.9:5555/r/token123/")
        assert controller.url == "http://203.0.113.9:5555/r/token123/"

        controller.clear_relay_url()
        assert "/r/" not in controller.url
    finally:
        controller.disable()
    assert controller.url == ""


def test_remote_proxy_request_uses_local_handle():
    """中转请求交给本机手柄服务处理：未配对 403，配对后可注入按键。"""
    import base64

    keys: list[str] = []
    controller = RemoteController()
    controller.on_key = keys.append
    controller.enable()
    try:
        status = controller.proxy_request("GET", "/status", "")
        assert status["status"] == 200
        body = json.loads(base64.b64decode(status["body"]))
        assert body["state"] == RemoteController.STATE_LISTENING
        assert body["code"] == controller.pair_code

        denied = controller.proxy_request("POST", "/key", _b64({"key": "h"}))
        assert denied["status"] == 403

        paired = controller.proxy_request("POST", "/confirm", _b64({}))
        assert paired["status"] == 200

        allowed = controller.proxy_request("POST", "/key", _b64({"key": "h"}))
        assert allowed["status"] == 200
        assert keys == ["h"]
    finally:
        controller.disable()


def _b64(payload: dict) -> str:
    import base64
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_remote_rejected_post_reads_the_body_before_replying(monkeypatch):
    """未配对被拒的 POST 也要先读完请求体。

    早退时把请求体留在缓冲里，close() 会被系统变成 RST，
    公网中转就只能看到连接中断，把本该有的 403 变成 502「手柄不可用」。
    """
    from client.remote import manager as manager_module

    read_paths: list[str] = []
    original = manager_module._Handler._read_json

    def spy(self):
        read_paths.append(self.path)
        return original(self)

    monkeypatch.setattr(manager_module._Handler, "_read_json", spy)
    controller = RemoteController()
    controller.enable()
    try:
        denied = controller.proxy_request("POST", "/key", _b64({"key": "h"}))
        assert denied["status"] == 403
        assert read_paths == ["/key"]
    finally:
        controller.disable()


def test_remote_handler_rejects_oversized_request_body(monkeypatch):
    """声明超长 Content-Length 时回 413，且必须先把请求体读干净（否则会被 RST）。"""
    import io

    from client.remote import manager as manager_module

    class _Stub:
        def __init__(self, length: int, data: bytes) -> None:
            self.headers = {"Content-Length": str(length)}
            self.rfile = io.BytesIO(data)

        _drain = manager_module._Handler._drain

    oversized = b"x" * (manager_module.MAX_REQUEST_BODY + 4096)
    stub = _Stub(len(oversized), oversized)
    payload, oversize = manager_module._Handler._read_json(stub)
    assert payload == {} and oversize is True
    assert stub.rfile.tell() == len(oversized)      # 读干净，不留残余字节

    payload = b'{"key": "h"}'
    stub = _Stub(len(payload), payload)
    assert manager_module._Handler._read_json(stub) == ({"key": "h"}, False)
    assert stub.rfile.tell() == len(payload)


def test_remote_handler_answers_413_for_an_oversized_body():
    """超限请求要在做任何事之前就被 413 拒掉（中转才能把状态码带给手机）。"""
    import io

    from client.remote import manager as manager_module

    size = manager_module.MAX_REQUEST_BODY + 8

    class _Stub:
        path = "/key"
        headers = {"Content-Length": str(size)}
        rfile = io.BytesIO(b"x" * size)

        def __init__(self) -> None:
            self.sent = []

        _read_json = manager_module._Handler._read_json
        _drain = manager_module._Handler._drain

        def _send_json(self, obj, status: int = 200) -> None:
            self.sent.append((obj, status))

    stub = _Stub()
    manager_module._Handler.do_POST(stub)
    assert stub.sent == [({"ok": False, "error": "payload too large"}, 413)]


def test_remote_relay_parses_session_paths():
    from server.core.http_relay import split_token

    assert split_token("/r/abc123/status") == ("abc123", "/status")
    assert split_token("/r/abc123/") == ("abc123", "/")
    assert split_token("/r/abc123") == ("abc123", "/")
    assert split_token("/status") == ("", "/status")
    assert split_token("/r/") == ("", "/r/")


def test_remote_relay_recognises_http_and_parses_request():
    import socket
    from server.core.http_relay import (
        looks_like_http, read_request,
    )

    server_side, peer = socket.socketpair()

    def feed(data: bytes) -> None:
        peer.sendall(data)

    try:
        feed(b"GET /r/tok/status HTTP/1.1\r\nHost: x\r\n\r\n")
        assert looks_like_http(server_side, timeout=1.0)
        request = read_request(server_side)
        assert request.method == "GET"
        assert request.target == "/r/tok/status"
        assert request.headers["host"] == "x"
        assert request.body == b""

        feed(b'{"type": "ping", "t": 0}\n')
        assert not looks_like_http(server_side, timeout=1.0)
    finally:
        server_side.close()
        peer.close()


def test_remote_relay_parses_post_body_and_rejects_oversized():
    import socket
    from server.core.http_relay import read_request

    server_side, peer = socket.socketpair()
    try:
        body = b'{"key": "h"}'
        peer.sendall(
            b"POST /key HTTP/1.1\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        request = read_request(server_side)
        assert request.method == "POST"
        assert request.body == body

        peer.sendall(b"POST /key HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n")
        assert read_request(server_side) is None
    finally:
        server_side.close()
        peer.close()


def test_remote_relay_drops_unknown_session_tokens():
    from unittest.mock import Mock

    from server.core.http_relay import RemoteRelay

    relay = RemoteRelay(lambda _socket, _message: None)
    assert relay.has_session("nope") is False
    assert relay.forward("nope", Mock()) is None
    relay.shutdown()


def test_client_greets_server_so_protocol_detection_is_immediate():
    """客户端连上即发问候包：服务器无需等待超时就能判定是游戏连接。"""
    import socket
    from client.net.connection import NetworkManager

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    network = NetworkManager(port)
    try:
        network.connect("127.0.0.1")
        accepted, _ = listener.accept()
        accepted.settimeout(2)
        assert json.loads(accepted.recv(256).decode("utf-8")) == {
            "type": "ping", "t": 0,
        }
        assert network.host == "127.0.0.1"
    finally:
        network.disconnect()
        listener.close()


def test_app_requests_relay_session_only_when_supported_and_online():
    """中转会话申请的开关条件：服务器支持 + 连接在线。"""
    from types import SimpleNamespace

    from client.app import UParlorApp

    app = object.__new__(UParlorApp)
    app.remote = RemoteController()
    sent: list[dict] = []
    app.network = SimpleNamespace(connected=True, send=sent.append)

    UParlorApp._request_remote_relay(app, "open")          # 服务器不支持
    assert sent == []

    app.remote.set_relay_available(True)
    UParlorApp._request_remote_relay(app, "open")
    assert sent == [{"type": "remote_session", "action": "open"}]

    sent.clear()
    app.network.connected = False
    UParlorApp.request_remote_relay(app)
    assert sent == []

    sent.clear()
    app.network.connected = True
    UParlorApp._request_remote_relay(app, "close")
    assert sent == [{"type": "remote_session", "action": "close"}]


def test_remote_relay_message_wiring(monkeypatch):
    """分发层接线：会话令牌 → 中转地址；中转请求 → 本机手柄响应。"""
    import base64
    import types

    from client.net.dispatch import dispatch_server_message

    keys: list[str] = []
    controller = RemoteController()
    controller.on_key = keys.append
    controller.enable()
    sent: list[dict] = []

    app = types.SimpleNamespace(
        remote=controller,
        network=types.SimpleNamespace(
            host="203.0.113.9", port=5555, send=sent.append, connected=True,
        ),
        refresh_remote_window=lambda: None,
    )
    screen = types.SimpleNamespace(state=types.SimpleNamespace())
    try:
        dispatch_server_message(app, screen, {
            "type": "remote_session_opened", "token": "tok123",
        })
        assert controller.url == "http://203.0.113.9:5555/r/tok123/"

        body = base64.b64encode(json.dumps({"key": "h"}).encode()).decode()
        dispatch_server_message(app, screen, {
            "type": "remote_http", "id": 7, "method": "POST",
            "target": "/confirm", "body": base64.b64encode(b"{}").decode(),
        })
        for _ in range(100):
            if sent:
                break
            time.sleep(0.05)
        assert sent[0]["type"] == "remote_http_response"
        assert sent[0]["id"] == 7
        assert sent[0]["status"] == 200

        sent.clear()
        dispatch_server_message(app, screen, {
            "type": "remote_http", "id": 8, "method": "POST",
            "target": "/key", "body": body,
        })
        for _ in range(100):
            if sent:
                break
            time.sleep(0.05)
        assert sent[0]["status"] == 200
        assert keys == ["h"]
    finally:
        controller.disable()


def test_remote_relay_forwards_browser_requests_to_client(monkeypatch):
    """端到端：浏览器 → 游戏服务器 HTTP → 客户端本机手柄 → 原路返回。"""
    import socket
    import threading
    from unittest.mock import Mock

    from server import chat_server as chat_server_module

    monkeypatch.setattr(chat_server_module, "ChatLogManager", Mock)
    monkeypatch.setattr(chat_server_module, "DMLogManager", Mock)
    server = chat_server_module.ChatServer()

    server.server.bind(("127.0.0.1", 0))
    server.server.listen(5)
    port = server.server.getsockname()[1]
    server.running = True
    stopping = threading.Event()

    def accept_loop() -> None:
        while not stopping.is_set():
            try:
                client_socket, _ = server.server.accept()
            except OSError:
                return
            threading.Thread(
                target=server.handle_client, args=(client_socket,),
                daemon=True,
            ).start()

    threading.Thread(target=accept_loop, daemon=True).start()

    controller = RemoteController()
    controller.enable()
    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    stream = client.makefile("rwb")

    def send(message: dict) -> None:
        client.sendall(json.dumps(message).encode("utf-8") + b"\n")

    try:
        # 登录状态置位：登录流程不在本用例范围
        send({"type": "ping", "t": 0})   # 与真实客户端一致：先问候
        for _ in range(300):
            with server.lock:
                if server.clients:
                    break
            time.sleep(0.01)
        else:
            raise AssertionError("服务器未注册客户端连接")
        with server.lock:
            server_socket = next(iter(server.clients))
            server.clients[server_socket]["state"] = "playing"
            server.clients[server_socket]["name"] = "tester"

        send({"type": "remote_session", "action": "open"})
        token = ""
        while not token:
            message = json.loads(stream.readline())
            if message.get("type") == "remote_session_opened":
                token = message["token"]
        assert token

        def serve_relay_requests() -> None:
            while not stopping.is_set():
                try:
                    line = stream.readline()
                except OSError:
                    return
                if not line:
                    return
                message = json.loads(line)
                if message.get("type") != "remote_http":
                    continue
                response = controller.proxy_request(
                    message["method"], message["target"], message["body"],
                )
                send({"type": "remote_http_response",
                      "id": message["id"], **response})

        threading.Thread(target=serve_relay_requests, daemon=True).start()

        status = _get_json(f"http://127.0.0.1:{port}/r/{token}/status")
        assert status["state"] == RemoteController.STATE_LISTENING
        assert status["code"] == controller.pair_code

        _post_json(f"http://127.0.0.1:{port}/r/{token}/confirm", {})
        assert _get_json(f"http://127.0.0.1:{port}/r/{token}/status")[
            "state"] == RemoteController.STATE_CONNECTED

        # 令牌失效后给出来访者提示页
        expired = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/r/deadbeef/", timeout=5,
        )
        assert "连接已失效" in expired.read().decode("utf-8")
    finally:
        stopping.set()
        controller.disable()
        client.close()
        server.server.close()


def test_remote_window_has_working_back_action():
    from textual.app import App, ComposeResult

    from client.views.system.remote import RemotePanel, RemoteWindow
    from client.window_engine import Divider

    class _App(App):
        back_requested = False

        def compose(self) -> ComposeResult:
            yield RemoteWindow(id="remote-window")

        def on_remote_panel_back_requested(
            self, event: RemotePanel.BackRequested,
        ) -> None:
            event.stop()
            self.back_requested = True

    async def verify() -> None:
        app = _App()
        async with app.run_test() as pilot:
            window = app.query_one("#remote-window", RemoteWindow)
            window.show()
            await pilot.pause()
            panel = app.query_one("#remote-panel", RemotePanel)
            assert window.focused_panel is panel
            assert panel.selected_option is not None
            assert panel.selected_option.id == "back"
            assert panel.selected_option.label == "返回"
            divider = panel.query_one(Divider)
            layout = panel.query_one("#remote-layout")
            assert divider.parent is layout
            assert divider.region.width == layout.content_region.width
            window.nav("up")
            window.nav("down")
            window.focus_move("k")
            window.nav("enter")
            await pilot.pause()
            assert app.back_requested

    asyncio.run(verify())
