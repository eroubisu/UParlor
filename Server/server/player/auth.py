"""认证流程 Mixin — 登录、注册、密码验证"""

import re

from .manager import PlayerManager
from ..storage import maintenance
from ..msg_types import FRIEND_REQUEST, LOGIN_PROMPT, LOGIN_SUCCESS, AI_SYNC

_NAME_RE = re.compile(r'^[A-Za-z0-9]+$')


def validate_username(name: str) -> str | None:
    """校验用户名，返回错误信息或 None（合法）"""
    if len(name) < 2 or len(name) > 12:
        return '用户名长度需要在2-12个字符之间。'
    if not _NAME_RE.match(name):
        return '用户名只能包含英文字母和数字。'
    return None


class AuthMixin:
    """处理用户登录/注册的认证流程"""

    def _handle_login(self, client_socket, text):
        if not text:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '用户名不能为空，请重新输入：'})
            return

        name = text
        if not PlayerManager.player_exists(name):
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '该用户名不存在。'})
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
        except Exception as e:
            print(f"[!] 注册失败 {name}: {e}")
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

        if PlayerManager.verify_password(name, text):
            player_data = PlayerManager.load_player_data(name)

            # 检查并授予时间相关头衔
            maintenance.check_and_grant_time_titles(player_data)

            # 记录登录天数
            maintenance.track_login_day(player_data)

            with self.lock:
                self.clients[client_socket]['state'] = 'playing'
                self.clients[client_socket]['data'] = player_data

            self._on_login_success(client_socket, name, player_data, '登录成功！', '登录')
        else:
            self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '密码错误，请重试：'})

    def _on_login_success(self, client_socket, name, player_data, success_text, log_label):
        """登录/注册后的共用流程"""
        self.send_to(client_socket, {'type': LOGIN_SUCCESS, 'text': success_text})
        self.send_player_status(client_socket, player_data)
        self.lobby_engine.register_player(name, player_data)
        self._send_initial_location(client_socket, name)
        # 发送世界欢迎地图
        self._send_world_welcome(client_socket, name, player_data)
        self._send_chat_history(client_socket, 1)
        # 下发 AI 伙伴数据和 token 统计
        ai_data = player_data.get('ai_companions', {})
        token_stats = player_data.get('ai_token_stats', {})
        if ai_data or token_stats:
            self.send_to(client_socket, {
                'type': AI_SYNC,
                'companions': ai_data,
                'token_stats': token_stats,
            })
        self.broadcast_online_users()
        self._send_friend_list(client_socket, player_data)
        self._send_all_users(client_socket)
        self._send_dm_history(client_socket, name)
        # 下发待处理的好友申请
        pending = player_data.get('pending_friend_requests', [])
        if pending:
            self.send_to(client_socket, {
                'type': FRIEND_REQUEST,
                'pending': pending,
            })
        print(f"[+] {name} {log_label}")
