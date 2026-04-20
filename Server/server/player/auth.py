"""认证流程 Mixin — 登录、注册、密码验证"""

from __future__ import annotations

import logging
import re
import time

from .manager import PlayerManager
from ..config import MAX_LOGIN_ATTEMPTS, LOGIN_COOLDOWN
from ..msg_types import FRIEND_REQUEST, LOGIN_PROMPT, LOGIN_SUCCESS, GAME_LIST, ROOM_LIST

_NAME_RE = re.compile(r'^[A-Za-z0-9]+$')

logger = logging.getLogger(__name__)


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
        if not PlayerManager.player_exists(name):
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '该用户名不存在。'})
            return

        # 防止多端登录：用户名阶段即拒绝
        existing = self._name_to_socket.get(name)
        if existing and existing != client_socket:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '该账号已在线，无法重复登录。'})
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
            PlayerManager.register_player(name, temp_password)
            player_data = PlayerManager.load_player_data(name)
        except Exception:
            logger.exception("注册失败 %s", name)
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '注册失败，请重试。\n请输入用户名：'})
            with self.lock:
                self.clients[client_socket]['state'] = 'login'
                self.clients[client_socket]['name'] = None
            return

        with self.lock:
            self.clients[client_socket]['state'] = 'playing'
            self.clients[client_socket]['data'] = player_data
            if 'temp_password' in self.clients[client_socket]:
                del self.clients[client_socket]['temp_password']

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

            with self.lock:
                self.clients[client_socket]['state'] = 'playing'
                self.clients[client_socket]['data'] = player_data

            self._on_login_success(client_socket, name, player_data, '登录成功！', '登录')
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
                self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '密码错误，请重试：'})

    def _on_login_success(self, client_socket, name, player_data, success_text, log_label):
        """登录/注册后的共用流程"""
        self._register_player_socket(name, client_socket)
        self.send_to(client_socket, {'type': LOGIN_SUCCESS, 'text': success_text})
        self.send_player_status(client_socket, player_data)
        self.lobby_engine.register_player(name, player_data)
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
        _SAFE_KEYS = ('id', 'name', 'icon', 'description', 'min_players', 'max_players', 'room_settings')
        games = [
            {k: info[k] for k in _SAFE_KEYS if k in info}
            for info in get_all_games()
        ]
        self.send_to(client_socket, {'type': GAME_LIST, 'games': games})

    def _send_room_list(self, client_socket):
        """下发当前所有活跃房间列表"""
        rooms = self.lobby_engine.get_all_rooms()
        self.send_to(client_socket, {'type': ROOM_LIST, 'rooms': rooms})
