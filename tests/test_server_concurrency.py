"""Server lock ownership and ordering contracts."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from client.net.connection import NetworkManager
from client.net.dispatch.auth import _on_auth_conflict
from client.net.messages import AuthConflict, parse_server_message
from client.state.auth import AuthState
from client.views.login import LoginPanel
from client.window_engine import InputSession, InputSpec, Option, SelectList
from server.chat_server import ChatServer
from server.handlers.friends import (
    handle_friend_accept, handle_friend_remove, send_friend_request,
)
from server.player.auth import AuthMixin
from server.player.manager import PlayerManager


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.sent = []

    def close(self) -> None:
        self.closed = True

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


class _LockCheckedDict(dict):
    def __init__(self, lock: threading.Lock, *args) -> None:
        self._lock = lock
        super().__init__(*args)

    def __setitem__(self, key, value) -> None:
        assert self._lock.locked()
        super().__setitem__(key, value)

    def pop(self, key, default=None):
        assert self._lock.locked()
        return super().pop(key, default)


def test_remove_client_releases_server_lock_before_lobby_lock(monkeypatch):
    client_socket = _FakeSocket()
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server.clients = {
        client_socket: {
            "name": "alice",
            "state": "playing",
            "data": {"name": "alice"},
        }
    }
    server._name_to_socket = {"alice": client_socket}
    server._cmd_cooldowns = {"alice": 1.0}

    class _Lobby:
        def unregister_player(self, player_name):
            assert player_name == "alice"
            assert server.lock.acquire(blocking=False)
            server.lock.release()
            return []

    server.lobby_engine = _Lobby()
    server.broadcast_online_users = lambda: None
    server.dispatch_game_result = Mock()
    monkeypatch.setattr(PlayerManager, "save_player_data", Mock())

    ChatServer.remove_client(server, client_socket)

    assert client_socket.closed
    assert client_socket not in server.clients
    assert "alice" not in server._name_to_socket


def test_auth_transitions_hold_server_lock(monkeypatch):
    login_socket = _FakeSocket()
    register_socket = _FakeSocket()
    lock = threading.Lock()

    class _Server(AuthMixin):
        def __init__(self):
            self.lock = lock
            self.clients = {
                login_socket: _LockCheckedDict(
                    lock, {"name": None, "state": "login"}),
                register_socket: _LockCheckedDict(
                    lock, {"name": None, "state": "login"}),
            }
            self._name_to_socket = {}
            self.sent = []

        def send_to(self, target, message):
            self.sent.append((target, message))

    server = _Server()
    monkeypatch.setattr(
        PlayerManager, "player_exists", lambda name: name == "alice")

    server._handle_login(login_socket, "alice")
    server._handle_register_name(register_socket, "bob")

    assert server.clients[login_socket] == {
        "name": "alice", "state": "password"}
    assert server.clients[register_socket] == {
        "name": "bob", "state": "register_password"}


class _Lobby:
    def __init__(self):
        self._lock = threading.RLock()
        self.online_players = {}
        self.events = []

    def register_player(self, name, data):
        with self._lock:
            self.online_players[name] = data
            self.events.append(("register", name))

    def unregister_player(self, name):
        with self._lock:
            self.online_players.pop(name, None)
            self.events.append(("unregister", name))
            return [{"detached": name}]


def _make_auth_server(sockets):
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server.clients = {
        client_socket: {
            "name": None, "state": "login", "data": None, "channel": 1,
        }
        for client_socket in sockets
    }
    server._name_to_socket = {}
    server._cmd_cooldowns = {}
    server.lobby_engine = _Lobby()
    server.sent = []
    server.send_to = lambda target, message: server.sent.append((target, message))
    server.send_player_status = Mock()
    server._send_game_list = Mock()
    server._send_room_list = Mock()
    server._send_initial_location = Mock()
    server._send_chat_history = Mock()
    server.broadcast_online_users = Mock()
    server._send_friend_list = Mock()
    server._send_dm_history = Mock()
    server.dispatch_game_result = Mock()
    AuthMixin._login_attempts.clear()
    return server


def test_duplicate_conflict_is_only_disclosed_after_correct_password(monkeypatch):
    old_socket, new_socket = _FakeSocket(), _FakeSocket()
    server = _make_auth_server((old_socket, new_socket))
    server.clients[old_socket].update(
        name="alice", state="playing", data={"name": "alice"})
    server.clients[new_socket].update(name="alice", state="password")
    server._name_to_socket["alice"] = old_socket

    monkeypatch.setattr(PlayerManager, "verify_password", lambda name, password: password == "correct")
    monkeypatch.setattr(
        PlayerManager, "load_player_data", lambda name: {"name": name})

    server._handle_password(new_socket, "wrong")
    assert server.clients[new_socket]["state"] == "password"
    assert all(message["type"] != "auth_conflict" for _, message in server.sent)

    server.sent.clear()
    server._handle_password(new_socket, "correct")
    assert server.clients[new_socket]["state"] == "login_conflict"
    assert server.sent == [(
        new_socket,
        {
            "type": "auth_conflict",
            "text": "该账号已有活动会话，请选择处理方式：",
            "choices": [
                {"id": "takeover", "label": "结束其他会话并登录"},
                {"id": "cancel", "label": "取消登录"},
            ],
        },
    )]


def test_duplicate_login_cancel_resets_username_prompt(monkeypatch):
    client_socket = _FakeSocket()
    server = _make_auth_server((client_socket,))
    server.clients[client_socket].update(
        name="alice", state="login_conflict", data={"name": "alice"})

    server._handle_login_conflict(client_socket, "cancel")

    assert server.clients[client_socket]["state"] == "login"
    assert server.clients[client_socket]["name"] is None
    assert server.clients[client_socket]["data"] is None
    assert server.sent[-1] == (
        client_socket, {"type": "login_prompt", "text": "请输入用户名："})


def test_displaced_login_username_prompt_resets_hidden_input_state():
    class _Input:
        placeholder = "请输入密码"
        password = True
        value = ""
        disabled = True

        def focus(self):
            pass

    input_widget = _Input()
    panel = object.__new__(LoginPanel)
    panel._step = "waiting"
    panel._waiting_for = "password"
    panel._tab = "login"
    panel._auth_state = None
    panel._submitted = True
    panel.update = Mock()
    panel.input_session = InputSession(InputSpec(password=True))
    panel.input_session.mount(input_widget)
    panel.activate_input_context = lambda: panel.input_session.replace(
        LoginPanel.input_spec(panel))

    LoginPanel.add_message(
        panel, "当前会话已由其他客户端结束。\n请输入用户名：")

    assert panel._step == "username"
    assert panel._submitted is False
    assert input_widget.placeholder == "当前会话已由其他客户端结束。"
    assert input_widget.password is False


def test_login_rejects_invalid_and_unknown_usernames(monkeypatch):
    client_socket = _FakeSocket()
    server = _make_auth_server((client_socket,))
    monkeypatch.setattr(PlayerManager, "player_exists", lambda _name: False)

    server._handle_login(client_socket, "!")
    assert server.sent[-1][1]["text"].startswith("用户名格式错误：")
    assert server.clients[client_socket]["state"] == "login"

    server._handle_login(client_socket, "missing")
    assert server.sent[-1][1]["text"] == "用户名错误或不存在，请检查后重试"
    assert server.clients[client_socket]["state"] == "login"


def test_auth_cancel_returns_password_state_to_username():
    client_socket = _FakeSocket()
    server = _make_auth_server((client_socket,))
    server.clients[client_socket].update(name="alice", state="password")

    server.process_message(client_socket, {"type": "auth_cancel"})

    assert server.clients[client_socket]["name"] is None
    assert server.clients[client_socket]["state"] == "login"
    assert server.sent[-1] == (
        client_socket, {"type": "login_prompt", "text": "请输入用户名："})


def test_duplicate_login_takeover_detaches_old_owner(monkeypatch):
    old_socket, new_socket = _FakeSocket(), _FakeSocket()
    server = _make_auth_server((old_socket, new_socket))
    live_data = {"name": "alice", "gold": 123}
    server.clients[old_socket].update(
        name="alice", state="playing", data=live_data)
    server.clients[new_socket].update(
        name="alice", state="login_conflict", data={"name": "alice"})
    server._name_to_socket["alice"] = old_socket
    server.lobby_engine.online_players["alice"] = live_data
    save = Mock()
    monkeypatch.setattr(PlayerManager, "save_player_data", save)

    server._handle_login_conflict(new_socket, "takeover")

    assert server._name_to_socket["alice"] is new_socket
    assert server.clients[new_socket]["state"] == "playing"
    assert server.clients[new_socket]["data"] is live_data
    assert server.clients[old_socket]["state"] == "login"
    assert server.clients[old_socket]["name"] is None
    assert server.lobby_engine.events[-2:] == [
        ("unregister", "alice"), ("register", "alice")]
    assert (old_socket, {
        "type": "action", "action": "session_offline"}) in server.sent
    assert not any(
        target is old_socket and message.get("type") == "login_prompt"
        for target, message in server.sent)
    assert any(
        target is new_socket and message.get("type") == "login_success"
        for target, message in server.sent
    )
    save.assert_called_once_with("alice", live_data)


def test_concurrent_correct_logins_leave_one_owner(monkeypatch):
    first, second = _FakeSocket(), _FakeSocket()
    server = _make_auth_server((first, second))
    for client_socket in (first, second):
        server.clients[client_socket].update(
            name="alice", state="password")
    barrier = threading.Barrier(2)

    def verify(_name, _password):
        barrier.wait()
        return True

    monkeypatch.setattr(PlayerManager, "verify_password", verify)
    monkeypatch.setattr(
        PlayerManager, "load_player_data", lambda name: {"name": name})
    threads = [
        threading.Thread(
            target=server._handle_password, args=(client_socket, "correct"))
        for client_socket in (first, second)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    states = [server.clients[s]["state"] for s in (first, second)]
    assert states.count("playing") == 1
    assert states.count("login_conflict") == 1
    owner = server._name_to_socket["alice"]
    assert server.clients[owner]["state"] == "playing"


def test_old_socket_cleanup_cannot_unregister_replacement(monkeypatch):
    old_socket, new_socket = _FakeSocket(), _FakeSocket()
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server.clients = {
        old_socket: {
            "name": "alice", "state": "playing", "data": {"name": "alice"},
        },
        new_socket: {
            "name": "alice", "state": "playing", "data": {"name": "alice"},
        },
    }
    server._name_to_socket = {"alice": new_socket}
    server._cmd_cooldowns = {}
    server._send_locks = {
        old_socket: threading.Lock(), new_socket: threading.Lock()}
    server.lobby_engine = Mock()
    server.broadcast_online_users = Mock()
    server.dispatch_game_result = Mock()
    monkeypatch.setattr(PlayerManager, "save_player_data", Mock())

    server.remove_client(old_socket)

    assert server._name_to_socket["alice"] is new_socket
    server.lobby_engine.unregister_player.assert_not_called()


def test_concurrent_registration_creates_one_account(monkeypatch, tmp_path: Path):
    from server.player import manager as manager_module

    monkeypatch.setattr(manager_module, "USERS_DIR", str(tmp_path))
    monkeypatch.setattr(
        PlayerManager, "hash_password", lambda password: f"hash:{password}")
    barrier = threading.Barrier(2)
    results = []

    def register():
        barrier.wait()
        results.append(PlayerManager.register_player("alice", "secret"))

    threads = [threading.Thread(target=register) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
    assert PlayerManager.player_exists("alice")


def test_auth_handles_atomic_registration_loss(monkeypatch):
    client_socket = _FakeSocket()
    server = _make_auth_server((client_socket,))
    server.clients[client_socket].update(
        name="alice", state="register_password", temp_password="secret")
    monkeypatch.setattr(
        PlayerManager, "register_player", lambda _name, _password: False)

    server._handle_register(client_socket)

    assert server.clients[client_socket]["state"] == "login"
    assert server.clients[client_socket]["name"] is None
    assert server.sent[-1] == (
        client_socket,
        {
            "type": "login_prompt",
            "text": "该用户名已被占用。\n请输入用户名：",
        },
    )


class _FriendServer:
    def __init__(self, records):
        self.lock = threading.Lock()
        self.clients = {}
        self._name_to_socket = {}
        self.sent = []
        self.lobby_engine = SimpleNamespace(
            _lock=threading.RLock(),
            online_players=records,
        )
        for name, data in records.items():
            client_socket = _FakeSocket()
            self._name_to_socket[name] = client_socket
            self.clients[client_socket] = {
                "name": name, "state": "playing", "data": data,
            }

    def send_to(self, target, message):
        self.sent.append((target, message))

    def _send_friend_list(self, target, data):
        self.send_to(target, {
            "type": "friend_list", "friends": list(data.get("friends", []))})


def test_friend_transactions_preserve_symmetry_and_concurrent_updates(
        monkeypatch, tmp_path: Path):
    from server.player import manager as manager_module

    monkeypatch.setattr(manager_module, "USERS_DIR", str(tmp_path))
    monkeypatch.setattr(
        PlayerManager, "hash_password", lambda password: f"hash:{password}")
    for name in ("alice", "bob", "carol"):
        assert PlayerManager.register_player(name, "secret")
    records = {}
    for name in ("alice", "bob", "carol"):
        data = PlayerManager.load_player_data(name)
        assert data is not None
        records[name] = data
    server = _FriendServer(records)
    barrier = threading.Barrier(2)

    def request(source):
        barrier.wait()
        assert send_friend_request(
            server, source, "bob", records[source]) is None

    threads = [
        threading.Thread(target=request, args=(source,))
        for source in ("alice", "carol")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert set(PlayerManager.load_player_data("bob")[
        "pending_friend_requests"]) == {"alice", "carol"}

    barrier = threading.Barrier(2)

    def accept(source):
        barrier.wait()
        handle_friend_accept(
            server, server._name_to_socket["bob"], "bob", records["bob"],
            {"name": source})

    threads = [
        threading.Thread(target=accept, args=(source,))
        for source in ("alice", "carol")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    persisted = {
        name: PlayerManager.load_player_data(name)
        for name in ("alice", "bob", "carol")
    }
    assert set(persisted["bob"]["friends"]) == {"alice", "carol"}
    assert persisted["alice"]["friends"] == ["bob"]
    assert persisted["carol"]["friends"] == ["bob"]

    barrier = threading.Barrier(2)

    def remove(source):
        barrier.wait()
        handle_friend_remove(
            server, server._name_to_socket["bob"], "bob", records["bob"],
            {"name": source})

    threads = [
        threading.Thread(target=remove, args=(source,))
        for source in ("alice", "carol")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    persisted = {
        name: PlayerManager.load_player_data(name)
        for name in ("alice", "bob", "carol")
    }
    assert persisted["bob"]["friends"] == []
    assert persisted["alice"]["friends"] == []
    assert persisted["carol"]["friends"] == []


def test_friend_transaction_preserves_concurrent_gold_and_profile(
        monkeypatch, tmp_path: Path):
    import server.handlers.friends as friends_module
    from server.player import manager as manager_module

    monkeypatch.setattr(manager_module, "USERS_DIR", str(tmp_path))
    monkeypatch.setattr(
        PlayerManager, "hash_password", lambda password: f"hash:{password}")
    for name in ("alice", "bob"):
        assert PlayerManager.register_player(name, "secret")
    records = {}
    for name in ("alice", "bob"):
        data = PlayerManager.load_player_data(name)
        assert data is not None
        records[name] = data
    server = _FriendServer(records)
    save_started = threading.Event()
    mutation_attempted = threading.Event()
    original_save = friends_module._save_locked_player

    def blocking_friend_save(name, data):
        if name == "bob" and not save_started.is_set():
            save_started.set()
            assert mutation_attempted.wait(timeout=2)
        original_save(name, data)

    monkeypatch.setattr(
        friends_module, "_save_locked_player", blocking_friend_save)

    def mutate_unrelated_fields():
        assert save_started.wait(timeout=2)
        mutation_attempted.set()
        with server.lobby_engine._lock:
            with PlayerManager.lock_players("bob"):
                records["bob"]["gold"] = 777
                records["bob"]["profile_card"]["motto"] = "concurrent"
                PlayerManager.save_player_data("bob", records["bob"])

    mutation = threading.Thread(target=mutate_unrelated_fields)
    mutation.start()
    assert send_friend_request(
        server, "alice", "bob", records["alice"]) is None
    mutation.join(timeout=2)
    assert not mutation.is_alive()

    persisted = PlayerManager.load_player_data("bob")
    assert records["bob"]["pending_friend_requests"] == ["alice"]
    assert records["bob"]["gold"] == 777
    assert records["bob"]["profile_card"]["motto"] == "concurrent"
    assert persisted["pending_friend_requests"] == ["alice"]
    assert persisted["gold"] == 777
    assert persisted["profile_card"]["motto"] == "concurrent"


def test_friend_transaction_rolls_back_before_online_commit(monkeypatch):
    records = {
        "alice": {
            "name": "alice", "friends": [],
            "pending_friend_requests": [],
        },
        "bob": {
            "name": "bob", "friends": [],
            "pending_friend_requests": ["alice"],
        },
    }
    server = _FriendServer(records)
    stored = deepcopy(records)
    failed = False

    def save(name, data):
        nonlocal failed
        if name == "bob" and not failed:
            failed = True
            raise OSError("simulated write failure")
        stored[name] = deepcopy(data)

    monkeypatch.setattr(PlayerManager, "save_player_data", save)

    with pytest.raises(OSError, match="simulated write failure"):
        handle_friend_accept(
            server, server._name_to_socket["bob"], "bob", records["bob"],
            {"name": "alice"})

    assert stored == records
    assert records["bob"]["pending_friend_requests"] == ["alice"]
    assert records["bob"]["friends"] == []
    assert records["alice"]["friends"] == []


class _BlockingSocket(_FakeSocket):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0

    def sendall(self, data):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        self.release.wait(timeout=2)
        self.sent.append(data)
        self.active -= 1

    def send(self, _data):
        raise AssertionError("send() must not be used")


def test_server_socket_writes_use_sendall_and_do_not_overlap():
    client_socket = _BlockingSocket()
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server._send_locks = {client_socket: threading.Lock()}
    threads = [
        threading.Thread(
            target=server.send_to, args=(client_socket, {"index": index}))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    assert client_socket.started.wait(timeout=1)
    time.sleep(0.02)
    client_socket.release.set()
    for thread in threads:
        thread.join()

    assert client_socket.max_active == 1
    assert len(client_socket.sent) == 2


def test_server_lock_is_available_during_blocked_io():
    client_socket = _BlockingSocket()
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server._send_locks = {client_socket: threading.Lock()}
    thread = threading.Thread(
        target=server.send_to, args=(client_socket, {"message": "blocked"}))
    thread.start()
    assert client_socket.started.wait(timeout=1)
    assert server.lock.acquire(blocking=False)
    server.lock.release()
    client_socket.release.set()
    thread.join()


def test_broadcast_snapshots_then_routes_through_send_to():
    first, second = _FakeSocket(), _FakeSocket()
    server = object.__new__(ChatServer)
    server.lock = threading.Lock()
    server.clients = {
        first: {"channel": 1}, second: {"channel": 2},
    }
    sent = []
    server.send_to = lambda target, message: sent.append((target, message))

    server.broadcast({"type": "system"}, channel=1)

    assert sent == [(first, {"type": "system"})]


def test_graceful_stop_clears_under_lock_and_saves_closes_outside(monkeypatch):
    client_socket = _FakeSocket()
    server = object.__new__(ChatServer)
    server.running = True
    server.lock = threading.Lock()
    server.clients = {
        client_socket: {
            "name": "alice", "data": {"name": "alice"}, "state": "playing",
        },
    }
    server._name_to_socket = {"alice": client_socket}
    server._cmd_cooldowns = {"alice": 1.0}
    server._send_locks = {client_socket: threading.Lock()}
    server.log_mgr = Mock()
    server.server = _FakeSocket()

    def save(_name, _data):
        assert server.lock.acquire(blocking=False)
        server.lock.release()

    monkeypatch.setattr(PlayerManager, "save_player_data", save)
    server.graceful_stop()

    assert server.clients == {}
    assert server._name_to_socket == {}
    assert client_socket.closed
    server.log_mgr.flush.assert_called_once()


def test_client_sendall_is_serialized_and_close_waits_for_write():
    sock = _BlockingSocket()
    manager = NetworkManager(1234)
    manager.socket = sock
    manager.connected = True
    threads = [
        threading.Thread(target=manager.send, args=({"index": index},))
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    assert sock.started.wait(timeout=1)
    closer = threading.Thread(target=manager.disconnect)
    closer.start()
    time.sleep(0.02)
    assert not sock.closed
    sock.release.set()
    for thread in threads:
        thread.join()
    closer.join()

    assert sock.max_active == 1
    assert sock.closed


def test_prelogin_conflict_parsing_navigation_and_response():
    parsed = parse_server_message({
        "type": "auth_conflict",
        "text": "请选择",
        "choices": [
            {"id": "takeover", "label": "结束其他会话并登录"},
            {"id": "cancel", "label": "取消登录"},
        ],
    })
    assert isinstance(parsed, AuthConflict)
    assert [choice["label"] for choice in parsed.choices] == [
        "结束其他会话并登录", "取消登录"]

    state = AuthState()
    state.show_conflict(parsed.text, parsed.choices)
    panel = object.__new__(LoginPanel)
    panel._auth_state = state
    panel._submitted = False
    panel.selection = SelectList(
        (Option(choice["id"], choice["label"]) for choice in state.choices),
        "login-auth-conflict",
    )
    sent = []
    panel._send_auth_conflict_response = sent.append

    LoginPanel.nav(panel, "down")
    LoginPanel.nav(panel, "enter")

    assert state.cursor == 1
    assert sent == ["cancel"]


def test_auth_conflict_exits_insert_mode_before_navigation():
    parsed = AuthConflict(
        text="该账号已有活动会话，请选择处理方式：",
        choices=[
            {"id": "takeover", "label": "结束其他会话并登录"},
            {"id": "cancel", "label": "取消登录"},
        ],
    )
    state = AuthState()
    screen = SimpleNamespace(_mode="insert")

    def to_normal():
        screen._mode = "normal"

    screen._to_normal = to_normal

    _on_auth_conflict(parsed, None, screen, SimpleNamespace(auth=state))

    assert screen._mode == "normal"
    assert state.active
