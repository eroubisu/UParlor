"""Canonical chat persistence and session-only clear semantics."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from rich.cells import cell_len
from rich.markup import render
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from client.net.dispatch.chat import _on_private_chat
from client.net.dispatch.social import _on_friend_request
from client.state import ModuleStateManager
from client.state.chat import ChatEntry
from client.views.chat.content import ChatContentPanel
from client.views.chat.window import ChatWindow
from server.handlers.chat import handle_chat, handle_private_chat
from server.msg_types import SYSTEM
from server.storage.chat_log import ChatLogManager
from server.storage.dm_log import DMLogManager


def test_private_dispatch_updates_state_without_local_files(monkeypatch, tmp_path):
    from client.companion import config as companion_config

    companion_root = tmp_path / "companion"
    monkeypatch.setattr(companion_config, "COMPANION_DIR", companion_root)
    monkeypatch.setattr(
        companion_config, "PLAYERS_DIR", companion_root / "players")
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    screen = SimpleNamespace(update_badges=Mock())
    parsed = SimpleNamespace(
        from_name="bob", to_name="alice", text="hello", time="10:00")

    _on_private_chat(parsed, None, screen, state)

    assert state.chat.dm_entries["bob"] == [
        ChatEntry("bob", "hello", "10:00")]
    assert not companion_root.exists()


def test_friend_request_with_pending_snapshot_reaches_companion(monkeypatch):
    from client.companion.controller import CompanionController

    observe = Mock()
    monkeypatch.setattr(
        CompanionController,
        "instance",
        classmethod(lambda _cls, _state=None: SimpleNamespace(
            observe_event=observe)),
    )
    state = ModuleStateManager()
    screen = SimpleNamespace(update_badges=Mock())
    parsed = SimpleNamespace(from_name="bob", pending=["bob"])

    _on_friend_request(parsed, None, screen, state)

    assert state.notify.friend_requests == [
        {"name": "bob", "status": "pending"}]
    observe.assert_called_once_with("bob 发来好友申请")


def test_ui_clear_sends_nothing_and_blocks_same_state_reload(tmp_path):
    state = ModuleStateManager()
    state.chat.set_player_name("alice")
    state.chat.set_dm_history({
        "bob": [{"from": "bob", "text": "old", "time": "09:00"}],
    })
    sentinel = tmp_path / "server-dm.json"
    sentinel.write_text('{"messages": ["old"]}', encoding="utf-8")
    before = sentinel.read_bytes()

    network = SimpleNamespace(send=Mock())
    content = SimpleNamespace(_current_tab="bob", _render_current=Mock())
    chat_list = SimpleNamespace(_chat_state=state.chat)

    class _Window:
        app = SimpleNamespace(network=network)

        def query_one(self, selector, _type):
            return chat_list if selector == "#chat-list" else content

    event = SimpleNamespace(peer="bob", action="clear", stop=Mock())
    ChatWindow.on_dm_action(_Window(), event)

    class _Content:
        _showing_doc = False
        _chat_state = state.chat
        _active = 0
        tabs = []
        app = SimpleNamespace(network=network)

        def close_doc(self):
            pass

        def switch_tab(self, _index):
            pass

        def _update_title(self):
            pass

        def activate_input_context(self):
            pass

        def _render_current(self):
            pass

    ChatContentPanel.show_conversation(_Content(), "bob")

    network.send.assert_not_called()
    assert state.chat.dm_entries["bob"] == []
    assert "bob" in state.chat.dm_history_hidden
    assert sentinel.read_bytes() == before

    state.chat.set_dm_history({
        "bob": [{"from": "bob", "text": "old", "time": "09:00"}],
    })
    assert state.chat.dm_entries["bob"] == []
    state.chat.add_private_message("bob", "alice", "new", "10:00")
    assert state.chat.dm_entries["bob"] == [
        ChatEntry("bob", "new", "10:00")]


def test_world_handler_broadcasts_exact_saved_record(monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    manager = ChatLogManager()
    server = SimpleNamespace(log_mgr=manager, broadcast=Mock())

    handle_chat(server, object(), "alice", {"level": 3}, {
        "text": "hello", "channel": 1,
    })

    saved = manager.chat_logs[1][-1]
    broadcast = server.broadcast.call_args.args[0]
    assert {k: v for k, v in broadcast.items() if k != "sender"} == saved
    assert broadcast["sender"]["name"] == "alice"
    assert broadcast["sender"]["level"] == 3
    assert saved["id"]
    assert saved["time"]


def test_world_history_uses_latest_sixteen_and_pages_by_eight(
        monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    manager = ChatLogManager()
    manager.chat_logs[1] = [
        {"id": f"m{index}", "text": str(index)}
        for index in range(25)
    ]

    initial = manager.get_history(1)
    page, has_more = manager.get_history_page(
        1, limit=8, before_id="m9")
    bounded, bounded_has_more = manager.get_history_page(
        1, limit=8, before_id="m9", after_id="m4")

    assert [message["id"] for message in initial] == [
        f"m{index}" for index in range(9, 25)]
    assert [message["id"] for message in page] == [
        f"m{index}" for index in range(1, 9)]
    assert has_more
    assert [message["id"] for message in bounded] == [
        f"m{index}" for index in range(5, 9)]
    assert not bounded_has_more


def test_world_history_pages_across_archived_and_active_days(
        monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    (history_dir / "2026-08-05_channel_1.json").write_text(
        json.dumps([
            {"id": f"old-{index}", "text": str(index)}
            for index in range(10)
        ]),
        encoding="utf-8",
    )
    manager = ChatLogManager()
    manager.chat_logs[1] = [
        {"id": f"new-{index}", "text": str(index)}
        for index in range(4)
    ]

    page, has_more = manager.get_history_page(
        1, limit=8, before_id="new-0")

    assert [message["id"] for message in page] == [
        f"old-{index}" for index in range(2, 10)]
    assert has_more


def test_world_clear_marker_survives_new_state_without_deleting_history(
        monkeypatch, tmp_path):
    from client import storage

    config_file = tmp_path / "config.json"
    monkeypatch.setattr(storage, "_FILE", config_file)
    monkeypatch.setattr(storage, "_DIR", tmp_path)
    history = [
        {
            "id": f"m{index}",
            "name": "alice",
            "text": str(index),
            "time": "10:00:00",
        }
        for index in range(25)
    ]
    first = ModuleStateManager()
    first.chat.set_player_name("alice")
    first.chat.set_world_history(history, has_more=True)

    assert len(first.chat.world_messages) == 16
    first.chat.clear_world_messages()
    assert first.chat.world_messages == []
    assert storage.get_world_chat_clear_marker("alice") == "m24"

    restored = ModuleStateManager()
    restored.chat.set_player_name("alice")
    restored.chat.set_world_history([
        *history[-5:],
        {
            "id": "m25",
            "name": "bob",
            "text": "new",
            "time": "10:01:00",
        },
    ], has_more=True)

    assert [entry.message_id for entry in restored.chat.world_messages] == [
        "m25"]
    assert restored.chat.world_has_more

    restored.chat.prepend_world_history([
        {
            "id": "m23",
            "name": "alice",
            "text": "23",
            "time": "10:00:00",
        },
        history[-1],
    ], has_more=False)
    restored.chat.reset_world_projection()

    assert [entry.message_id for entry in restored.chat.world_messages] == [
        "m25"]
    assert restored.chat.world_has_more


def test_cleared_world_chat_can_explicitly_load_hidden_history(
        monkeypatch, tmp_path):
    from client import storage

    monkeypatch.setattr(storage, "_FILE", tmp_path / "config.json")
    monkeypatch.setattr(storage, "_DIR", tmp_path)

    class ChatApp(App):
        def __init__(self):
            super().__init__()
            self.network = SimpleNamespace(send=Mock(return_value=True))
            self.state = ModuleStateManager()

        def compose(self) -> ComposeResult:
            yield ChatWindow(id="chat-window")

    async def verify() -> None:
        app = ChatApp()
        app.state.chat.set_player_name("alice")
        app.state.chat.set_world_history([
            {
                "id": f"m{index}",
                "name": "alice",
                "text": str(index),
                "time": "10:00:00",
            }
            for index in range(16)
        ], has_more=True)
        app.state.chat.clear_world_messages()

        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(ChatWindow)
            window.bind_state(app.state)
            window.show()
            await pilot.pause()
            await pilot.pause()
            panel = app.query_one(ChatContentPanel)

            panel.nav("up")
            panel.nav("up")

            app.network.send.assert_called_once_with({
                "type": "get_chat_history",
                "before_id": "",
                "after_id": "",
            })

    asyncio.run(verify())


def test_hidden_chat_reflows_after_window_becomes_visible():
    class ChatApp(App):
        def __init__(self):
            super().__init__()
            self.network = SimpleNamespace(send=Mock(return_value=True))
            self.state = ModuleStateManager()

        def compose(self) -> ComposeResult:
            yield ChatWindow(id="chat-window")

    async def verify() -> None:
        app = ChatApp()
        app.state.chat.set_world_history([{
            "id": "m1",
            "name": "alice",
            "text": "中文消息用于验证重新打开后的宽度",
            "time": "10:00:00",
        }])
        async with app.run_test(size=(100, 30)) as pilot:
            window = app.query_one(ChatWindow)
            window.bind_state(app.state)
            panel = app.query_one(ChatContentPanel)
            hidden = render(
                str(panel.query_one("#t0 .content").content)).plain

            window.show()
            await pilot.pause()

            visible = render(
                str(panel.query_one("#t0 .content").content)).plain
            width = panel._content_width(0)
            hidden_width = max(
                cell_len(line) for line in hidden.splitlines())
            assert hidden_width <= 14
            assert width > 12
            assert hidden_width < width
            assert max(cell_len(line) for line in visible.splitlines()) == width
            assert panel.tabs == ["聊天", "设置"]

            await pilot.resize_terminal(70, 24)
            await pilot.pause()
            resized = render(
                str(panel.query_one("#t0 .content").content)).plain
            resized_width = panel._content_width(0)
            assert resized_width < width
            assert max(
                cell_len(line) for line in resized.splitlines()
            ) == resized_width

    asyncio.run(verify())


def test_world_history_requires_two_up_actions_at_the_top():
    class ChatApp(App):
        def __init__(self):
            super().__init__()
            self.network = SimpleNamespace(send=Mock(return_value=True))
            self.state = ModuleStateManager()

        def compose(self) -> ComposeResult:
            yield ChatWindow(id="chat-window")

    async def verify() -> None:
        app = ChatApp()
        app.state.chat.set_world_history([
            {
                "id": f"m{index}",
                "name": "alice",
                "text": f"message {index}",
                "time": "10:00:00",
            }
            for index in range(16)
        ], has_more=True)
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(ChatWindow)
            window.bind_state(app.state)
            window.show()
            await pilot.pause()
            await pilot.pause()
            panel = app.query_one(ChatContentPanel)
            scroll = panel.query_one("#t0", VerticalScroll)
            scroll.scroll_home(animate=False)
            await pilot.pause()

            panel.nav("up")
            await pilot.pause()
            content = str(panel.query_one("#t0 .content").content)
            assert "向上加载历史消息" in content
            app.network.send.assert_not_called()

            panel.nav("up")

            app.network.send.assert_called_once_with({
                "type": "get_chat_history",
                "before_id": "m0",
                "after_id": "",
            })
            assert app.state.chat.world_history_loading

    asyncio.run(verify())


def test_empty_world_history_page_immediately_keeps_terminal_prompt():
    class ChatApp(App):
        def __init__(self):
            super().__init__()
            self.network = SimpleNamespace(send=Mock(return_value=True))
            self.state = ModuleStateManager()

        def compose(self) -> ComposeResult:
            yield ChatWindow(id="chat-window")

    async def verify() -> None:
        app = ChatApp()
        app.state.chat.set_world_history([{
            "id": "m0",
            "name": "alice",
            "text": "only",
            "time": "10:00:00",
        }], has_more=True)
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(ChatWindow)
            window.bind_state(app.state)
            window.show()
            await pilot.pause()
            panel = app.query_one(ChatContentPanel)
            panel.query_one(
                "#t0", VerticalScroll).scroll_home(animate=False)

            panel.nav("up")
            panel.nav("up")
            app.state.chat.prepend_world_history([], has_more=False)
            await pilot.pause()

            content = str(panel.query_one("#t0 .content").content)
            assert "没有更早的历史消息" in content

    asyncio.run(verify())


def test_history_response_while_settings_visible_reflows_chat_on_return():
    class ChatApp(App):
        def __init__(self):
            super().__init__()
            self.network = SimpleNamespace(send=Mock(return_value=True))
            self.state = ModuleStateManager()

        def compose(self) -> ComposeResult:
            yield ChatWindow(id="chat-window")

    async def verify() -> None:
        app = ChatApp()
        app.state.chat.set_world_history([{
            "id": "m1",
            "name": "alice",
            "text": "中文消息用于验证标签切换后的真实宽度重排",
            "time": "10:00:00",
        }], has_more=True)
        async with app.run_test(size=(80, 24)) as pilot:
            window = app.query_one(ChatWindow)
            window.bind_state(app.state)
            window.show()
            await pilot.pause()
            panel = app.query_one(ChatContentPanel)

            panel.switch_tab(1)
            await pilot.pause()
            app.state.chat.prepend_world_history([{
                "id": "m0",
                "name": "bob",
                "text": "隐藏聊天标签收到更早的中文记录",
                "time": "09:59:00",
            }], has_more=False)
            panel.switch_tab(0)
            await pilot.pause()

            visible = render(
                str(panel.query_one("#t0 .content").content)).plain
            width = panel._content_width(0)
            assert max(
                cell_len(line) for line in visible.splitlines()
            ) == width

    asyncio.run(verify())


def test_dm_handler_sends_exact_persisted_record(monkeypatch, tmp_path):
    import server.storage.dm_log as dm_log

    log_dir = tmp_path / "dm"
    history_dir = tmp_path / "dm-history"
    monkeypatch.setattr(dm_log, "DM_LOG_DIR", str(log_dir))
    monkeypatch.setattr(dm_log, "DM_HISTORY_DIR", str(history_dir))
    manager = DMLogManager()
    server = SimpleNamespace(
        dm_log_mgr=manager,
        send_to=Mock(),
        send_to_player=Mock(),
    )

    handle_private_chat(
        server, object(), "alice",
        {"level": 3, "friends": ["bob"]},
        {"target": "bob", "text": "hello"},
    )

    sent = server.send_to.call_args.args[1]
    persisted = json.loads(next(log_dir.rglob("*.json")).read_text(
        encoding="utf-8"))[-1]
    assert {k: v for k, v in sent.items() if k != "sender"} == persisted
    assert sent["sender"]["name"] == "alice"
    assert server.send_to_player.call_args.args[1] is sent
    assert sent["id"]
    assert sent["time"]


def test_chat_rotates_at_beijing_0400_under_one_lock(monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    clock = {"now": datetime(2026, 8, 6, 3, 59, tzinfo=chat_log.BEIJING_TZ)}
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    monkeypatch.setattr(chat_log, "get_beijing_now", lambda: clock["now"])
    manager = ChatLogManager()

    class _Lock:
        entered = False
        acquisitions = 0

        def __enter__(self):
            assert not self.entered
            self.entered = True
            self.acquisitions += 1

        def __exit__(self, *_args):
            self.entered = False

    lock = _Lock()
    manager._lock = lock
    manager.save(1, "alice", "day-n")
    clock["now"] = datetime(2026, 8, 6, 4, 0, tzinfo=chat_log.BEIJING_TZ)
    manager.save(1, "alice", "day-n-plus-1")
    manager.flush()

    archived = json.loads(
        (history_dir / "2026-08-05_channel_1.json").read_text("utf-8"))
    active = json.loads(
        (log_dir / "channel_1_2026-08-06.json").read_text("utf-8"))
    assert [message["text"] for message in archived] == ["day-n"]
    assert [message["text"] for message in active] == ["day-n-plus-1"]
    manager.archive()
    assert lock.acquisitions == 4


def test_dm_rotates_at_beijing_0400_under_one_lock(monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log
    import server.storage.dm_log as dm_log

    log_dir = tmp_path / "dm"
    history_dir = tmp_path / "dm-history"
    clock = {"now": datetime(2026, 8, 6, 3, 59, tzinfo=chat_log.BEIJING_TZ)}
    monkeypatch.setattr(dm_log, "DM_LOG_DIR", str(log_dir))
    monkeypatch.setattr(dm_log, "DM_HISTORY_DIR", str(history_dir))
    monkeypatch.setattr(chat_log, "get_beijing_now", lambda: clock["now"])
    monkeypatch.setattr(dm_log, "get_beijing_now", lambda: clock["now"])
    manager = DMLogManager()

    class _Lock:
        entered = False
        acquisitions = 0

        def __enter__(self):
            assert not self.entered
            self.entered = True
            self.acquisitions += 1

        def __exit__(self, *_args):
            self.entered = False

    lock = _Lock()
    manager._lock = lock
    manager.save("alice", "bob", "day-n")
    clock["now"] = datetime(2026, 8, 6, 4, 0, tzinfo=chat_log.BEIJING_TZ)
    manager.save("alice", "bob", "day-n-plus-1")

    archived = json.loads(
        (history_dir / "alice__bob" / "2026-08-05.json").read_text("utf-8"))
    active = json.loads(
        (log_dir / "alice__bob" / "2026-08-06.json").read_text("utf-8"))
    assert [message["text"] for message in archived] == ["day-n"]
    assert [message["text"] for message in active] == ["day-n-plus-1"]
    assert manager.current_date == "2026-08-06"
    manager.archive()
    assert lock.acquisitions == 3


def test_dm_history_merges_archived_and_active_days_before_limit(
        monkeypatch, tmp_path):
    import server.storage.dm_log as dm_log

    log_dir = tmp_path / "dm"
    history_dir = tmp_path / "dm-history"
    active_pair = log_dir / "alice__bob"
    history_pair = history_dir / "alice__bob"
    active_pair.mkdir(parents=True)
    history_pair.mkdir(parents=True)
    monkeypatch.setattr(dm_log, "DM_LOG_DIR", str(log_dir))
    monkeypatch.setattr(dm_log, "DM_HISTORY_DIR", str(history_dir))
    monkeypatch.setattr(dm_log, "get_today_date_str", lambda: "2026-08-06")
    (history_pair / "2026-08-05.json").write_text(json.dumps([
        {"id": "old-1"}, {"id": "old-2"},
    ]), encoding="utf-8")
    (active_pair / "2026-08-06.json").write_text(json.dumps([
        {"id": "new-1"}, {"id": "new-2"},
    ]), encoding="utf-8")
    manager = DMLogManager()

    history = manager.get_history("alice", "bob", limit=3)

    assert [message["id"] for message in history] == [
        "old-2", "new-1", "new-2"]


def test_chat_archive_failure_preserves_source_and_memory(
        monkeypatch, tmp_path, caplog):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    manager = ChatLogManager()
    manager.save(1, "alice", "must survive")
    manager.flush()
    source = log_dir / f"channel_1_{manager.current_date}.json"
    old_date = manager.current_date
    real_open = open

    def fail_archive(path, *args, **kwargs):
        if str(path).startswith(str(history_dir)):
            raise OSError("archive unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(chat_log, "open", fail_archive, raising=False)
    monkeypatch.setattr(chat_log, "get_today_date_str", lambda: "2026-08-07")
    with caplog.at_level("ERROR"):
        manager.archive()

    assert source.exists()
    assert [message["text"] for message in manager.chat_logs[1]] == [
        "must survive"]
    assert manager.current_date == old_date
    assert not (history_dir / f"{old_date}_channel_1.json").exists()
    assert "保留频道数据等待重试" in caplog.text


def test_new_day_chat_is_not_saved_or_broadcast_until_archive_recovers(
        monkeypatch, tmp_path):
    import server.storage.chat_log as chat_log

    log_dir = tmp_path / "chat"
    history_dir = tmp_path / "history"
    log_dir.mkdir()
    history_dir.mkdir()
    clock = {"date": "2026-08-05"}
    monkeypatch.setattr(chat_log, "CHAT_LOG_DIR", str(log_dir))
    monkeypatch.setattr(chat_log, "CHAT_HISTORY_DIR", str(history_dir))
    monkeypatch.setattr(
        chat_log, "get_today_date_str", lambda: clock["date"])
    manager = ChatLogManager()
    manager.save(1, "alice", "old-day")
    manager.flush()
    old_source = log_dir / "channel_1_2026-08-05.json"
    real_open = open
    archive_available = {"value": False}

    def fail_archive(path, *args, **kwargs):
        if (
                str(path).startswith(str(history_dir))
                and not archive_available["value"]):
            raise OSError("archive unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(chat_log, "open", fail_archive, raising=False)
    clock["date"] = "2026-08-06"
    server = SimpleNamespace(
        log_mgr=manager,
        broadcast=Mock(),
        send_to=Mock(),
    )

    handle_chat(server, object(), "alice", {"level": 3}, {
        "text": "new-day", "channel": 1,
    })

    assert old_source.exists()
    assert [message["text"] for message in manager.chat_logs[1]] == [
        "old-day"]
    assert manager.current_date == "2026-08-05"
    assert not (log_dir / "channel_1_2026-08-06.json").exists()
    server.broadcast.assert_not_called()
    assert server.send_to.call_args.args[1]["type"] == SYSTEM

    archive_available["value"] = True
    server.send_to.reset_mock()
    handle_chat(server, object(), "alice", {"level": 3}, {
        "text": "new-day", "channel": 1,
    })
    manager.flush()

    archived = json.loads(
        (history_dir / "2026-08-05_channel_1.json").read_text("utf-8"))
    active = json.loads(
        (log_dir / "channel_1_2026-08-06.json").read_text("utf-8"))
    assert [message["text"] for message in archived] == ["old-day"]
    assert [message["text"] for message in active] == ["new-day"]
    assert server.broadcast.call_count == 1
    broadcast = server.broadcast.call_args.args[0]
    assert {
        key: value for key, value in broadcast.items() if key != "sender"
    } == manager.chat_logs[1][0]
    server.send_to.assert_not_called()
