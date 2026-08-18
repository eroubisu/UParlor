"""认证流程 Mixin — 登录、注册、密码验证"""

from __future__ import annotations

import logging
import re
import time

from .manager import PlayerManager
from ..config import MAX_LOGIN_ATTEMPTS, LOGIN_COOLDOWN
from ..msg_types import (
    ACTION, AUTH_CONFLICT, FRIEND_REQUEST, GAME_LIST, LOGIN_PROMPT,
    LOGIN_SUCCESS, ROOM_LIST,
)

_NAME_RE = re.compile(r'^[A-Za-z0-9]+$')

logger = logging.getLogger(__name__)

_AUTH_CONFLICT_CHOICES = [
    {'id': 'takeover', 'label': '结束其他会话并登录'},
    {'id': 'cancel', 'label': '取消登录'},
]


def validate_username(name: str) -> str | None:
    """校验用户名，返回错误信息或 None（合法）"""
    if len(name) < 2 or len(name) > 12:
        return '用户名长度需要在2-12个字符之间。'
    if not _NAME_RE.match(name):
        return '用户名只能包含英文字母和数字。'
    return None


class AuthMixin:
    """处理用户登录/注册的认证流程"""

    # name → (fail_count, last_fail_time) — 登录限流
    _login_attempts: dict[str, tuple[int, float]] = {}

    def _handle_login(self, client_socket, text):
        if not text:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '用户名不能为空，请重新输入：'})
            return

        name = text
        err = validate_username(name)
        if err:
            self.send_to(client_socket, {
                'type': LOGIN_PROMPT,
                'text': f'用户名格式错误：{err}',
            })
            return

        if not PlayerManager.player_exists(name):
            self.send_to(client_socket, {
                'type': LOGIN_PROMPT,
                'text': '用户名错误或不存在，请检查后重试',
            })
            return

        with self.lock:
            self.clients[client_socket]['name'] = name
            self.clients[client_socket]['state'] = 'password'
        self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请输入密码：'})

    def _handle_register_name(self, client_socket, text):
        """注册流程 — 用户名阶段：校验格式 + 检查占用"""
        if not text:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '用户名不能为空，请重新输入：'})
            return

        name = text
        err = validate_username(name)
        if err:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': err})
            return

        if PlayerManager.player_exists(name):
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '该用户名已被占用。'})
            return

        with self.lock:
            self.clients[client_socket]['name'] = name
            self.clients[client_socket]['state'] = 'register_password'
        self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请设置密码（至少3个字符）：'})

    def _handle_register(self, client_socket):
        """处理注册"""
        with self.lock:
            name = self.clients[client_socket]['name']
            temp_password = self.clients[client_socket].get('temp_password')

        try:
            registered = PlayerManager.register_player(name, temp_password)
            if not registered:
                self._reset_login(
                    client_socket, '该用户名已被占用。\n请输入用户名：')
                return
            player_data = PlayerManager.load_player_data(name)
            if not player_data:
                raise OSError(f'无法加载新注册账号 {name}')
        except (OSError, ValueError):
            logger.exception("注册失败 %s", name)
            self._reset_login(
                client_socket, '注册失败，请重试。\n请输入用户名：')
            return

        if not self._activate_player(client_socket, name, player_data):
            self._send_auth_conflict(client_socket)
            return

        self._on_login_success(client_socket, name, player_data, '注册成功！', '注册并加入')

    def _handle_register_password(self, client_socket, text):
        """处理注册 - 设置密码"""
        if len(text) < 3:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '密码至少3个字符，请重新输入：'})
            return

        with self.lock:
            self.clients[client_socket]['temp_password'] = text

        # 直接完成注册
        self._handle_register(client_socket)

    def _handle_password(self, client_socket, text):
        with self.lock:
            name = self.clients[client_socket]['name']

        # 登录限流检查
        now = time.monotonic()
        attempts, last_time = self._login_attempts.get(name, (0, 0.0))
        if attempts >= MAX_LOGIN_ATTEMPTS and now - last_time < LOGIN_COOLDOWN:
            remaining = int(LOGIN_COOLDOWN - (now - last_time))
            self.send_to(client_socket, {
                'type': LOGIN_PROMPT,
                'text': f'密码错误次数过多，请 {remaining} 秒后重试。',
            })
            return

        if PlayerManager.verify_password(name, text):
            # 登录成功，清除计数
            self._login_attempts.pop(name, None)

            player_data = PlayerManager.load_player_data(name)
            if not player_data:
                self._reset_login(
                    client_socket, '账号数据加载失败，请重新登录。\n请输入用户名：')
                return

            if self._activate_player(client_socket, name, player_data):
                self._on_login_success(
                    client_socket, name, player_data, '登录成功！', '登录')
            else:
                self._send_auth_conflict(client_socket)
        else:
            # 记录失败次数
            if now - last_time >= LOGIN_COOLDOWN:
                attempts = 0  # 冷却期过后重置
            attempts += 1
            self._login_attempts[name] = (attempts, now)
            if attempts >= MAX_LOGIN_ATTEMPTS:
                logger.warning("登录限流: %s 连续 %d 次密码错误", name, attempts)
                self.send_to(client_socket, {
                    'type': LOGIN_PROMPT,
                    'text': f'密码错误次数过多，请 {LOGIN_COOLDOWN} 秒后重试。',
                })
            else:
                self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '密码错误，请重试'})

    def _activate_player(self, client_socket, name, player_data) -> bool:
        """原子认领账号；大厅锁始终先于 server.lock。"""
        with self.lobby_engine._lock:
            with self.lock:
                info = self.clients.get(client_socket)
                if not info:
                    return False
                existing = self._name_to_socket.get(name)
                if existing is not None and existing is not client_socket:
                    info['state'] = 'login_conflict'
                    info['data'] = player_data
                    return False
                self._name_to_socket[name] = client_socket
                info['name'] = name
                info['state'] = 'playing'
                info['data'] = player_data
                info.pop('temp_password', None)
            self.lobby_engine.register_player(name, player_data)
        return True

    def _send_auth_conflict(self, client_socket) -> None:
        self.send_to(client_socket, {
            'type': AUTH_CONFLICT,
            'text': '该账号已有活动会话，请选择处理方式：',
            'choices': [dict(choice) for choice in _AUTH_CONFLICT_CHOICES],
        })

    def _reset_login(self, client_socket, prompt: str = '请输入用户名：') -> None:
        with self.lock:
            info = self.clients.get(client_socket)
            if not info:
                return
            info['state'] = 'login'
            info['name'] = None
            info['data'] = None
            info.pop('temp_password', None)
        self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': prompt})

    def _handle_login_conflict(self, client_socket, choice: str) -> None:
        if choice == 'cancel':
            self._reset_login(client_socket)
            return
        if choice != 'takeover':
            self._send_auth_conflict(client_socket)
            return

        old_socket = None
        old_data = None
        notifications = []
        with self.lobby_engine._lock:
            with self.lock:
                info = self.clients.get(client_socket)
                if not info or info.get('state') != 'login_conflict':
                    return
                name = info.get('name')
                pending_data = info.get('data')
                if not name or not pending_data:
                    return

                old_socket = self._name_to_socket.get(name)
                old_info = self.clients.get(old_socket) if old_socket else None
                if old_socket is not None and old_socket is not client_socket:
                    if old_info and old_info.get('name') == name:
                        old_data = old_info.get('data')
                        old_info['state'] = 'login'
                        old_info['name'] = None
                        old_info['data'] = None
                    self._cmd_cooldowns.pop(name, None)

                player_data = old_data or pending_data
                self._name_to_socket[name] = client_socket
                info['state'] = 'playing'
                info['data'] = player_data

            if old_socket is not None and old_socket is not client_socket:
                notifications = self.lobby_engine.unregister_player(name)
            self.lobby_engine.register_player(name, player_data)

        if old_data:
            PlayerManager.save_player_data(name, old_data)
        if old_socket is not None and old_socket is not client_socket:
            self.send_to(old_socket, {
                'type': ACTION, 'action': 'session_offline',
            })
        for notification in notifications:
            self.dispatch_game_result(notification)
        self._on_login_success(
            client_socket, name, player_data, '登录成功！', '接管登录')

    def _on_login_success(self, client_socket, name, player_data, success_text, log_label):
        """登录/注册后的共用流程"""
        self.send_to(client_socket, {'type': LOGIN_SUCCESS, 'text': success_text})
        self.send_player_status(client_socket, player_data)
        self._send_game_list(client_socket)
        self._send_room_list(client_socket)
        self._send_initial_location(client_socket, name)
        self._send_chat_history(client_socket, 1)
        self.broadcast_online_users()
        self._send_friend_list(client_socket, player_data)
        self._send_dm_history(client_socket, name)
        # 下发待处理的好友申请
        pending = player_data.get('pending_friend_requests', [])
        if pending:
            self.send_to(client_socket, {
                'type': FRIEND_REQUEST,
                'pending': pending,
            })
        logger.info("%s %s", name, log_label)

    def _send_game_list(self, client_socket):
        """下发可用游戏列表"""
        from ..games import get_all_games
        _SAFE_KEYS = (
            'id', 'name', 'icon', 'description', 'min_players',
            'max_players', 'start_policy', 'room_settings',
        )
        games = [
            {k: info[k] for k in _SAFE_KEYS if k in info}
            for info in get_all_games()
        ]
        self.send_to(client_socket, {'type': GAME_LIST, 'games': games})

    def _send_room_list(self, client_socket):
        """下发当前所有活跃房间列表"""
        rooms = self.lobby_engine.get_all_rooms()
        self.send_to(client_socket, {'type': ROOM_LIST, 'rooms': rooms})
