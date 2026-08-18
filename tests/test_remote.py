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
        _post_json(f"{base}/text", {"text": "你好，世界", "submit": True})
        assert texts == ["你好，世界"]
        assert keys == ["enter"]
    finally:
        controller.disable()


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
