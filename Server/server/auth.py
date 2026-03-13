"""认证流程 Mixin — 登录、注册、密码验证"""

from .player_manager import PlayerManager
from . import maintenance


class AuthMixin:
    """处理用户登录/注册的认证流程"""

    def _handle_login(self, client_socket, text):
        if not text:
            self.send_to(client_socket, {'type': 'login_prompt', 'text': '用户名不能为空，请重新输入：'})
            return

        name = text
        exists = PlayerManager.player_exists(name)

        with self.lock:
            self.clients[client_socket]['name'] = name

        if exists:
            self.clients[client_socket]['state'] = 'password'
            self.send_to(client_socket, {'type': 'login_prompt', 'text': '请输入密码：'})
        else:
            self.clients[client_socket]['state'] = 'register_password'
            self.send_to(client_socket, {'type': 'login_prompt', 'text': '请设置密码（至少3个字符）：'})

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
            self.send_to(client_socket, {'type': 'login_prompt', 'text': f'注册失败，请重试。\n请输入用户名：'})
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
            self.send_to(client_socket, {'type': 'login_prompt', 'text': '密码至少3个字符，请重新输入：'})
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
            self.send_to(client_socket, {'type': 'login_prompt', 'text': '密码错误，请重试：'})

    def _on_login_success(self, client_socket, name, player_data, success_text, log_label):
        """登录/注册后的共用流程"""
        self.send_to(client_socket, {'type': 'login_success', 'text': success_text})
        self.send_player_status(client_socket, player_data)
        self.lobby_engine.register_player(name, player_data)
        self._send_initial_location(client_socket, name)
        self._send_chat_history(client_socket, 1)
        online_msg = f'{name} 上线了'
        self.log_mgr.save(1, '[SYS]', online_msg)
        self.broadcast({'type': 'chat', 'name': '[SYS]', 'text': online_msg, 'channel': 1})
        self.broadcast_online_users()
        print(f"[+] {name} {log_label}")
