"""
聊天服务器
"""

import socket
import threading
import json
from datetime import datetime

from .config import HOST, PORT
from .player.manager import PlayerManager
from .lobby.engine import LobbyEngine
from .systems.titles import get_title_name
from .systems.items import get_item_info
from .infra.chat_log import ChatLogManager
from .infra import maintenance
from .player.auth import AuthMixin
from .game.result_dispatcher import (
    dispatch_game_result as _dispatch_game_result_impl,
    dispatch_result as _dispatch_result_impl,
    inject_location_path as _inject_location_path_impl,
)
from .msg_types import (
    CHAT, CHAT_HISTORY, GAME, LOGIN_PROMPT, LOCATION_UPDATE,
    ONLINE_USERS, STATUS,
)


class ChatServer(AuthMixin):
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}
        self.lock = threading.Lock()
        
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
        self.maintenance_thread = None
    
    # ── Rich Result 通用分发器 → result_dispatcher.py ──

    def dispatch_game_result(self, result, caller_socket=None, caller_name=None, caller_data=None):
        """Bot 调度器公共 API"""
        _dispatch_game_result_impl(self, result, caller_socket, caller_name, caller_data)

    def _get_player_data(self, player_name):
        """查找在线玩家的 player_data"""
        with self.lock:
            for client, info in self.clients.items():
                if info.get('name') == player_name:
                    return info.get('data')
        return None

    def send_to_player(self, player_name, data):
        """发送消息给指定玩家（Bot调度器回调接口）"""
        with self.lock:
            for client, info in self.clients.items():
                if info.get('name') == player_name:
                    self.send_to(client, data)
                    break

    def _send_invite_notification(self, target_name, invite_data):
        """发送邀请通知给指定玩家"""
        with self.lock:
            for client, info in self.clients.items():
                if info.get('name') == target_name and info.get('state') == 'playing':
                    self.send_to(client, invite_data)
                    break

    def _send_chat_history(self, client_socket, channel):
        """发送聊天历史"""
        self.send_to(client_socket, {
            'type': CHAT_HISTORY,
            'channel': channel,
            'messages': self.log_mgr.get_history(channel)
        })

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
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
            except:
                pass

    def send_to(self, client_socket, message):
        try:
            data = json.dumps(message) + '\n'
            client_socket.send(data.encode('utf-8'))
        except:
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

        with self.lock:
            self.clients[client_socket] = {
                'name': None, 'state': 'login', 'data': None, 'channel': 1
            }
        
        # 登录提示发到指令区
        self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请输入用户名：'})
        
        while self.running:
            try:
                data = client_socket.recv(1024).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                while '\n' in buffer:
                    msg_str, buffer = buffer.split('\n', 1)
                    if msg_str:
                        msg = json.loads(msg_str)
                        self.process_message(client_socket, msg)
            except:
                break
        
        self.remove_client(client_socket)

    def process_message(self, client_socket, msg):
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
            self._handle_login(client_socket, text)
        elif state == 'register_password':
            self._handle_register_password(client_socket, text)
        elif state == 'password':
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

    def _handle_playing(self, client_socket, msg):
        with self.lock:
            name = self.clients[client_socket]['name']
            player_data = self.clients[client_socket]['data']
            client_channel = self.clients[client_socket].get('channel', 1)
        
        msg_type = msg.get('type', 'command')
        text = msg.get('text', '').strip()
        
        if msg_type == 'command':
            try:
                result = self.lobby_engine.process_command(player_data, text)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_to(client_socket, {'type': GAME, 'text': f'[服务器错误] {e}'})
                return
            if result:
                try:
                    _dispatch_result_impl(self, client_socket, name, player_data, result)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    self.send_to(client_socket, {'type': GAME, 'text': f'[服务器错误] {e}'})
            else:
                self.send_to(client_socket, {'type': GAME, 'text': '未知指令。'})
        
        elif msg_type == 'save_layout':
            layout = msg.get('layout')
            if isinstance(layout, dict):
                if self.lobby_engine._validate_layout(layout):
                    player_data['window_layout'] = layout
                    PlayerManager.save_player_data(name, player_data)

        elif msg_type == 'chat':
            channel = msg.get('channel', 1)
            display_name = f"[{player_data['level']}]{name}"
            
            # 记录聊天统计并检查头衔
            maintenance.track_chat_message(name, player_data)
            
            # 保存聊天记录
            self.log_mgr.save(channel, display_name, text)
            
            # 获取当前时间
            current_time = datetime.now().strftime('%H:%M')
            
            # 广播给同频道的人
            chat_msg = {
                'type': CHAT,
                'name': display_name,
                'text': text,
                'channel': channel,
                'time': current_time  # 添加时间戳
            }
            self.broadcast(chat_msg, channel=channel)
            print(f"[CH{channel}][{name}] {text}")

    def send_player_status(self, client_socket, player_data):
        """发送游戏大厅状态"""
        try:
            # 游戏大厅的状态数据
            # 从 displayed 头衔列表取第一个ID，转为显示名
            titles_data = player_data.get('titles', {})
            displayed = titles_data.get('displayed', [])
            title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
            status_data = {
                'name': player_data['name'],
                'level': player_data['level'],
                'gold': player_data['gold'],
                'title': title_display,
                'accessory': player_data.get('accessory'),
                'window_layout': player_data.get('window_layout'),
            }
            # 附带富物品信息供客户端直接渲染
            inv_raw = player_data.get('inventory', {})
            inv_enriched = {}
            for item_id, count in inv_raw.items():
                if count > 0:
                    info = get_item_info(item_id) or {}
                    inv_enriched[item_id] = {
                        'count': count,
                        'name': info.get('name', item_id),
                        'desc': info.get('desc', ''),
                        'use_methods': info.get('use_methods', []),
                    }
            status_data['inventory'] = inv_enriched

            # 全局游戏统计
            gs = player_data.get('game_stats')
            if gs:
                status_data['game_stats'] = gs

            # 查询当前游戏引擎的附加状态
            player_name = player_data.get('name', '')
            location = self.lobby_engine.get_player_location(player_name)
            game_id = self.lobby_engine._get_game_for_location(location)
            extras = {}
            if game_id:
                engine = self.lobby_engine._get_engine(game_id, player_name)
                if engine:
                    extras = engine.get_status_extras(player_name, player_data) or {}
            
            status_msg = {'type': STATUS, 'data': status_data}
            status_msg['location'] = location
            status_msg['location_path'] = self.lobby_engine.get_location_path(location, player_name)
            status_msg.update(extras)
            self.send_to(client_socket, status_msg)
        except:
            pass

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
                except:
                    pass
                
                if name and info.get('state') == 'playing':
                    print(f"[-] {name} 离开")
                    should_broadcast = True
                    
                    # 从游戏引擎中注销玩家（处理判负、段位）并获取通知列表
                    room_notifications = self.lobby_engine.unregister_player(name)
        
        if should_broadcast:
            # 聊天室显示下线消息
            offline_msg = f'{name} 下线了'
            self.log_mgr.save(1, '[SYS]', offline_msg)
            self.broadcast({'type': CHAT, 'name': '[SYS]', 'text': offline_msg, 'channel': 1})
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
            print(f"[用户数据检查] 共 {total} 个用户，已更新 {updated} 个")
        
        # 启动维护检查线程
        self.maintenance_thread = threading.Thread(
            target=maintenance.maintenance_loop, args=(self,))
        self.maintenance_thread.daemon = True
        self.maintenance_thread.start()
        
        ip = self.get_local_ip()
        print("=" * 40)
        print("游戏大厅服务器已启动")
        print(f"地址: {ip}:{PORT}")
        print(f"当前日期: {self.log_mgr.current_date}")
        print(f"维护时间: 每日北京时间 {maintenance.MAINTENANCE_HOUR}:00")
        print("=" * 40)
        
        while self.running:
            try:
                client, addr = self.server.accept()
                thread = threading.Thread(target=self.handle_client, args=(client,))
                thread.daemon = True
                thread.start()
            except:
                break

    def stop(self):
        self.running = False
        self.server.close()
