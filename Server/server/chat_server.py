"""
聊天服务器
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time

from .config import HOST, PORT, USERS_DIR
from .config import MAX_BUFFER_SIZE
from .player.manager import PlayerManager
from .lobby.engine import LobbyEngine
from .storage.chat_log import ChatLogManager
from .storage.dm_log import DMLogManager
from .storage import maintenance
from .player.auth import AuthMixin
from .core.result_dispatcher import (
    dispatch_game_result as _dispatch_game_result_impl,
    dispatch_result as _dispatch_result_impl,
    inject_location_path as _inject_location_path_impl,
)
from .msg_types import (
    ALL_USERS, CHAT_HISTORY, DM_HISTORY, FRIEND_LIST, GAME, LOGIN_PROMPT,
    LOCATION_UPDATE, ONLINE_USERS,
)

# 触发消息处理器注册
from .handlers import client_state, friends, profile, chat, game_invite  # noqa: F401

logger = logging.getLogger(__name__)


class ChatServer(AuthMixin):
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}
        self._name_to_socket: dict[str, socket.socket] = {}  # O(1) 玩家查找索引
        self._cmd_cooldowns: dict[str, float] = {}  # 玩家名→上次指令时间戳（限流）
        self.lock = threading.Lock()
        
        from .config import CLIENT_VERSION
        self._client_version = CLIENT_VERSION
        
        # 游戏大厅引擎
        self.lobby_engine = LobbyEngine()
        # 设置邀请通知回调
        self.lobby_engine.set_invite_callback(self._send_invite_notification)
        
        # Bot 调度器泛化注册：从 GAME_INFO 自动创建
        from .games import GAMES
        self.bot_schedulers = {}
        for _gid, _mod in GAMES.items():
            _info = getattr(_mod, 'GAME_INFO', {})
            _create = _info.get('create_bot_scheduler')
            if _create:
                self.bot_schedulers[_gid] = _create(self)
        
        self.running = False
        self.log_mgr = ChatLogManager()
        self.dm_log_mgr = DMLogManager()
        self.maintenance_thread = None
    
    # ── Rich Result 通用分发器 → result_dispatcher.py ──

    def dispatch_game_result(self, result, caller_socket=None, caller_name=None, caller_data=None):
        """Bot 调度器公共 API"""
        _dispatch_game_result_impl(self, result, caller_socket, caller_name, caller_data)

    def _register_player_socket(self, player_name: str, client_socket):
        """注册玩家名→socket 映射（登录成功时调用）"""
        self._name_to_socket[player_name] = client_socket

    def _unregister_player_socket(self, player_name: str):
        """注销玩家名→socket 映射（下线时调用）"""
        self._name_to_socket.pop(player_name, None)

    def _get_player_data(self, player_name):
        """查找在线玩家的 player_data — O(1)"""
        cs = self._name_to_socket.get(player_name)
        if cs:
            info = self.clients.get(cs)
            if info:
                return info.get('data')
        return None

    def send_to_player(self, player_name, data):
        """发送消息给指定玩家 — O(1)"""
        cs = self._name_to_socket.get(player_name)
        if cs:
            self.send_to(cs, data)

    def _send_invite_notification(self, target_name, invite_data):
        """发送邀请通知给指定玩家 — O(1)"""
        cs = self._name_to_socket.get(target_name)
        if cs:
            info = self.clients.get(cs)
            if info and info.get('state') == 'playing':
                self.send_to(cs, invite_data)

    def _send_chat_history(self, client_socket, channel):
        """发送聊天历史"""
        self.send_to(client_socket, {
            'type': CHAT_HISTORY,
            'channel': channel,
            'messages': self.log_mgr.get_history(channel)
        })

    def _send_dm_history(self, client_socket, player_name):
        """发送私聊历史（登录时下发所有对话）"""
        conversations = self.dm_log_mgr.get_conversations(player_name)
        if conversations:
            self.send_to(client_socket, {
                'type': DM_HISTORY,
                'conversations': conversations,
            })

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    def broadcast(self, message, exclude=None, channel=None):
        with self.lock:
            if channel:
                clients_to_send = [
                    c for c, info in self.clients.items() 
                    if c != exclude and info.get('channel') == channel
                ]
            else:
                clients_to_send = [c for c in self.clients.keys() if c != exclude]
        
        data = json.dumps(message) + '\n'
        for client in clients_to_send:
            try:
                client.send(data.encode('utf-8'))
            except OSError:
                pass

    def send_to(self, client_socket, message):
        try:
            data = json.dumps(message) + '\n'
            client_socket.sendall(data.encode('utf-8'))
        except OSError:
            pass

    def broadcast_online_users(self):
        counts: dict[str, dict] = {}
        with self.lock:
            for info in self.clients.values():
                if info.get('state') == 'playing' and info.get('name'):
                    name = info['name']
                    if name in counts:
                        counts[name]['count'] += 1
                    else:
                        counts[name] = {
                            'name': name,
                            'channel': info.get('channel', 1),
                            'count': 1,
                        }
        users = list(counts.values())
        self.broadcast({'type': ONLINE_USERS, 'users': users})

    def _send_friend_list(self, client_socket, player_data):
        """向指定客户端发送好友列表"""
        friend_list = player_data.get('friends', [])
        self.send_to(client_socket, {'type': FRIEND_LIST, 'friends': friend_list})

    def _send_all_users(self, client_socket):
        """向指定客户端发送所有注册用户名"""
        names = self._get_all_user_names()
        self.send_to(client_socket, {'type': ALL_USERS, 'users': names})

    def _get_all_user_names(self) -> list[str]:
        """返回所有已注册用户名"""
        names = []
        if os.path.isdir(USERS_DIR):
            for entry in os.listdir(USERS_DIR):
                path = os.path.join(USERS_DIR, entry)
                if os.path.isdir(path):
                    names.append(entry)
                elif entry.endswith('.json'):
                    names.append(entry[:-5])
        return sorted(set(names))

    def handle_client(self, client_socket):
        buffer = ""

        # 启用 TCP Keepalive 保活
        try:
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
        except (OSError, AttributeError):
            pass

        # 发送超时防止慢客户端阻塞游戏循环
        try:
            client_socket.settimeout(5.0)
        except OSError:
            pass

        with self.lock:
            self.clients[client_socket] = {
                'name': None, 'state': 'login', 'data': None, 'channel': 1
            }
        
        # 登录提示发到指令区
        self.send_to(client_socket, {'type': 'client_version', 'latest': self._client_version})
        self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请输入用户名：'})
        
        while self.running:
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                # 缓冲区溢出保护
                if len(buffer) > MAX_BUFFER_SIZE:
                    logger.warning("客户端缓冲区溢出，断开连接")
                    break
                while '\n' in buffer:
                    msg_str, buffer = buffer.split('\n', 1)
                    if msg_str:
                        try:
                            msg = json.loads(msg_str)
                        except json.JSONDecodeError:
                            logger.warning("收到无效 JSON，忽略")
                            continue
                        self.process_message(client_socket, msg)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                break
            except OSError:
                break
            except Exception:
                logger.exception("handle_client 意外异常")
                break
        
        self.remove_client(client_socket)

    def process_message(self, client_socket, msg):
        # ping/pong 不需要认证，立即回复
        if msg.get('type') == 'ping':
            self.send_to(client_socket, {'type': 'pong', 't': msg.get('t', 0)})
            return

        with self.lock:
            client_info = self.clients.get(client_socket)
        
        if not client_info:
            return
        
        state = client_info['state']
        msg_type = msg.get('type', 'command')
        text = msg.get('text', '').strip()
        
        if msg_type == 'switch_channel':
            channel = msg.get('channel', 1)
            with self.lock:
                self.clients[client_socket]['channel'] = channel
            # 发送该频道的聊天历史
            self._send_chat_history(client_socket, channel)
            self.broadcast_online_users()
            return
        
        if state == 'login':
            if msg_type == 'register':
                self._handle_register_name(client_socket, text)
            else:
                self._handle_login(client_socket, text)
        elif state == 'register_password':
            if msg_type == 'login':
                # 用户切换到登录标签，重置状态
                with self.lock:
                    self.clients[client_socket]['state'] = 'login'
                    self.clients[client_socket]['name'] = None
                self._handle_login(client_socket, text)
            else:
                self._handle_register_password(client_socket, text)
        elif state == 'password':
            if msg_type == 'register':
                # 用户切换到注册标签，重置状态
                with self.lock:
                    self.clients[client_socket]['state'] = 'login'
                    self.clients[client_socket]['name'] = None
                self._handle_register_name(client_socket, text)
            else:
                self._handle_password(client_socket, text)
        elif state == 'playing':
            self._handle_playing(client_socket, msg)

    # ── 认证流程由 AuthMixin 提供 ──

    def _send_initial_location(self, client_socket, name):
        """登录成功后下发初始位置（含指令列表）"""
        loc = self.lobby_engine.get_player_location(name)
        with self.lock:
            player_data = self.clients.get(client_socket, {}).get('data')
        msg = {
            'type': LOCATION_UPDATE,
            'location': loc,
            'location_path': self.lobby_engine.get_location_path(loc, name),
        }
        _inject_location_path_impl(msg, self.lobby_engine, player_data)
        self.send_to(client_socket, msg)

    def _send_world_welcome(self, client_socket, name, player_data):
        """登录后发送世界地图初始画面"""
        engine = self.lobby_engine._get_engine('world', name)
        if engine:
            result = engine.get_welcome_message(player_data)
            if isinstance(result, dict):
                for m in result.get('send_to_caller', []):
                    self.send_to(client_socket, m)
                for target, messages in result.get('send_to_players', {}).items():
                    for m in messages:
                        self.send_to_player(target, m)

    def _handle_playing(self, client_socket, msg):
        with self.lock:
            name = self.clients[client_socket]['name']
            player_data = self.clients[client_socket]['data']
        
        msg_type = msg.get('type', 'command')
        text = msg.get('text', '').strip()

        # ── 限流: 每玩家最小 0.15 秒间隔 ──
        now = time.monotonic()
        last = self._cmd_cooldowns.get(name, 0.0)
        if now - last < 0.15:
            return
        self._cmd_cooldowns[name] = now
        
        # command 由 lobby_engine 处理
        if msg_type == 'command':
            try:
                result = self.lobby_engine.process_command(player_data, text)
            except Exception:
                logger.exception("process_command 异常: player=%s cmd=%s", name, text)
                self.send_to(client_socket, {'type': GAME, 'text': '[服务器错误]'})
                return
            if result:
                try:
                    _dispatch_result_impl(self, client_socket, name, player_data, result)
                except Exception:
                    logger.exception("dispatch_result 异常: player=%s", name)
                    self.send_to(client_socket, {'type': GAME, 'text': '[服务器错误]'})
            elif result is None:
                self.send_to(client_socket, {'type': GAME, 'text': '未知指令。'})
        
        else:
            from .handlers import dispatch_playing
            try:
                dispatch_playing(self, client_socket, name, player_data, msg)
            except Exception:
                logger.exception("dispatch_playing 异常: player=%s type=%s",
                                 name, msg_type)
                self.send_to(client_socket, {'type': GAME, 'text': '[服务器错误]'})

    def send_player_status(self, client_socket, player_data):
        """发送游戏大厅状态"""
        try:
            from .player.status_builder import build_status_message
            msg = build_status_message(self, player_data)
            self.send_to(client_socket, msg)
        except Exception:
            logger.exception("build_status_message 异常")

    def remove_client(self, client_socket):
        name = None
        should_broadcast = False
        room_notifications = None
        
        with self.lock:
            if client_socket in self.clients:
                info = self.clients[client_socket]
                name = info.get('name')
                
                if info.get('data'):
                    PlayerManager.save_player_data(name, info['data'])
                
                del self.clients[client_socket]
                
                try:
                    client_socket.close()
                except OSError:
                    pass
                
                if name and info.get('state') == 'playing':
                    logger.info("%s 离开", name)
                    self._unregister_player_socket(name)
                    self._cmd_cooldowns.pop(name, None)
                    should_broadcast = True
                    
                    # 从游戏引擎中注销玩家（处理判负、段位）并获取通知列表
                    room_notifications = self.lobby_engine.unregister_player(name)
        
        if should_broadcast:
            self.broadcast_online_users()
            
            # 通知房间内其他玩家
            for notif in (room_notifications or []):
                self.dispatch_game_result(notif)

    def start(self):
        self.running = True
        self.server.bind((HOST, PORT))
        self.server.listen(10)
        
        # 启动时升级所有用户数据到最新模板
        from .player.manager import PlayerManager
        total, updated = PlayerManager.upgrade_all_users()
        if total > 0:
            logger.info("用户数据检查: 共 %d 个用户，已更新 %d 个", total, updated)
        
        # 启动维护检查线程
        self.maintenance_thread = threading.Thread(
            target=maintenance.maintenance_loop, args=(self,))
        self.maintenance_thread.daemon = True
        self.maintenance_thread.start()
        
        ip = self.get_local_ip()
        logger.info("游戏大厅服务器已启动 — %s:%d", ip, PORT)
        logger.info("当前日期: %s | 维护时间: 每日 %d:00",
                    self.log_mgr.current_date, maintenance.MAINTENANCE_HOUR)
        
        while self.running:
            try:
                client, addr = self.server.accept()
                thread = threading.Thread(target=self.handle_client, args=(client,))
                thread.daemon = True
                thread.start()
            except OSError:
                break

    def stop(self):
        self.running = False
        try:
            self.server.close()
        except OSError:
            pass

    def graceful_stop(self):
        """优雅关闭：保存所有在线玩家数据，刷盘日志，关闭连接"""
        self.running = False
        # 保存所有在线玩家数据
        with self.lock:
            for cs, info in list(self.clients.items()):
                name = info.get('name')
                data = info.get('data')
                if name and data:
                    try:
                        PlayerManager.save_player_data(name, data)
                    except Exception:
                        logger.exception("关闭时保存 %s 数据失败", name)
                try:
                    cs.close()
                except OSError:
                    pass
            self.clients.clear()
            self._name_to_socket.clear()
        # 刷盘聊天日志
        try:
            self.log_mgr.flush()
        except Exception:
            logger.exception("关闭时刷盘聊天日志失败")
        try:
            self.server.close()
        except OSError:
            pass
        logger.info("服务器已优雅关闭")
