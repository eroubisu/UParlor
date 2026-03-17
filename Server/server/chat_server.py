"""
聊天服务器
"""

import os
import socket
import threading
import json
from datetime import datetime

from .config import HOST, PORT, USERS_DIR
from .player.manager import PlayerManager
from .lobby.engine import LobbyEngine
from .systems.titles import get_title_name
from .systems.items import get_item_info
from .infra.chat_log import ChatLogManager
from .infra.dm_log import DMLogManager
from .infra import maintenance
from .player.auth import AuthMixin
from .game.result_dispatcher import (
    dispatch_game_result as _dispatch_game_result_impl,
    dispatch_result as _dispatch_result_impl,
    inject_location_path as _inject_location_path_impl,
)
from .msg_types import (
    ACTION, ALL_USERS, CHAT, CHAT_HISTORY, DM_HISTORY, FRIEND_LIST, FRIEND_REQUEST, GAME, LOGIN_PROMPT,
    LOCATION_UPDATE, ONLINE_USERS, PRIVATE_CHAT, PROFILE_CARD, STATUS, SYSTEM,
)


class ChatServer(AuthMixin):
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients = {}
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

    def _send_friend_list(self, client_socket, player_data):
        """向指定客户端发送好友列表"""
        friends = player_data.get('friends', [])
        self.send_to(client_socket, {'type': FRIEND_LIST, 'friends': friends})

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
                while '\n' in buffer:
                    msg_str, buffer = buffer.split('\n', 1)
                    if msg_str:
                        msg = json.loads(msg_str)
                        self.process_message(client_socket, msg)
            except:
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

        elif msg_type == 'ai_sync_up':
            companions = msg.get('companions')
            if isinstance(companions, dict):
                player_data['ai_companions'] = companions
            token_stats = msg.get('token_stats')
            if isinstance(token_stats, dict):
                saved = player_data.get('ai_token_stats', {})
                if token_stats.get('today') == saved.get('today', ''):
                    # 按模型取较大值
                    r_models = token_stats.get('models', {})
                    s_models = saved.get('models', {})
                    merged = {}
                    for k in set(r_models) | set(s_models):
                        merged[k] = max(r_models.get(k, 0), s_models.get(k, 0))
                    token_stats['models'] = merged
                player_data['ai_token_stats'] = token_stats
            PlayerManager.save_player_data(name, player_data)

        elif msg_type == 'ai_gift_consume':
            item_id = msg.get('item_id', '')
            qty = msg.get('qty', 1)
            quality = msg.get('quality', 0)
            if isinstance(item_id, str) and item_id and isinstance(qty, int) and 0 < qty <= 99:
                from server.systems.items import inv_get, inv_sub
                inventory = player_data.get('inventory', {})
                cur = inv_get(inventory, item_id, quality)
                if cur >= qty:
                    inv_sub(inventory, item_id, quality, qty)
                    PlayerManager.save_player_data(name, player_data)
                    self.send_player_status(client_socket, player_data)

        elif msg_type == 'delete_account':
            password = msg.get('password', '')
            if not isinstance(password, str) or not password:
                self.send_to(client_socket, {'type': GAME, 'text': '密码不能为空。'})
                return
            from server.lobby.profile import do_delete_account
            result = do_delete_account(self.lobby_engine, name, password)
            if isinstance(result, dict) and result.get('action') == 'account_deleted':
                self.send_to(client_socket, {'type': GAME, 'text': result.get('message', '')})
                # 重置为登录状态，而非断开连接
                with self.lock:
                    self.clients[client_socket]['state'] = 'login'
                    self.clients[client_socket]['name'] = None
                    self.clients[client_socket]['data'] = None
                self.broadcast_online_users()
                self.send_to(client_socket, {'type': ACTION, 'action': 'return_to_login'})
                self.send_to(client_socket, {'type': LOGIN_PROMPT, 'text': '请输入用户名：'})
            else:
                self.send_to(client_socket, {'type': GAME, 'text': result if isinstance(result, str) else '删除失败。'})

        elif msg_type == 'get_profile_card':
            target = msg.get('target', '').strip()
            if target and PlayerManager.player_exists(target):
                target_data = PlayerManager.load_player_data(target)
                if target_data:
                    pc = target_data.get('profile_card', {})
                    pattern_id = pc.get('pattern_id', 'pattern_default')
                    pattern_info = get_item_info(pattern_id) or {}
                    titles_data = target_data.get('titles', {})
                    displayed = titles_data.get('displayed', [])
                    title_display = ' | '.join(get_title_name(t) for t in displayed) if displayed else ''
                    card = {
                        'name': target_data.get('name', target),
                        'level': target_data.get('level', 1),
                        'gold': target_data.get('gold', 0),
                        'title': title_display,
                        'motto': pc.get('motto', ''),
                        'name_color': pc.get('name_color', '#ffffff'),
                        'motto_color': pc.get('motto_color', '#b3b3b3'),
                        'border_color': pc.get('border_color', '#5a5a5a'),
                        'pattern': pattern_info.get('pattern', {'chars': '.', 'colors': ['#505050']}),
                        'card_fields': pc.get('card_fields', ['level', 'gold', 'games', 'created']),
                        'created_at': target_data.get('created_at', ''),
                        'game_stats': target_data.get('game_stats', {}),
                        'social_stats': target_data.get('social_stats', {}),
                        'friends_count': len(target_data.get('friends', [])),
                    }
                    self.send_to(client_socket, {'type': PROFILE_CARD, 'data': card})

        elif msg_type == 'update_profile_card':
            updates = msg.get('data', {})
            pc = player_data.setdefault('profile_card', {})
            allowed = ('motto', 'pattern_id', 'name_color', 'motto_color', 'border_color')
            for k in allowed:
                if k in updates:
                    val = updates[k]
                    if isinstance(val, str) and len(val) <= 200:
                        if k == 'pattern_id':
                            inv = player_data.get('inventory', {})
                            if val not in inv or (isinstance(inv.get(val), int) and inv[val] <= 0):
                                continue
                        pc[k] = val
            # card_fields: list of field IDs (max 4)
            if 'card_fields' in updates:
                valid_ids = {'level', 'gold', 'friends', 'games', 'days', 'created'}
                raw = updates['card_fields']
                if isinstance(raw, list) and len(raw) <= 4:
                    filtered = [f for f in raw if isinstance(f, str) and f in valid_ids]
                    pc['card_fields'] = filtered
            PlayerManager.save_player_data(name, player_data)
            self.send_player_status(client_socket, player_data)

        elif msg_type == 'friend_request':
            target = msg.get('name', '').strip()
            if target and target != name and PlayerManager.player_exists(target):
                # 检查是否已经是好友
                friends = player_data.get('friends', [])
                if target in friends:
                    return
                # 在目标玩家的 pending_friend_requests 中添加
                target_data = PlayerManager.load_player_data(target)
                if target_data:
                    pending = target_data.setdefault('pending_friend_requests', [])
                    if name not in pending:
                        pending.append(name)
                        PlayerManager.save_player_data(target, target_data)
                    # 通知目标玩家（如果在线），同时同步内存缓存
                    with self.lock:
                        for client, info in self.clients.items():
                            if info.get('name') == target and info.get('state') == 'playing':
                                # 同步 pending 到内存缓存
                                info['data'].setdefault('pending_friend_requests', [])
                                if name not in info['data']['pending_friend_requests']:
                                    info['data']['pending_friend_requests'].append(name)
                                self.send_to(client, {
                                    'type': FRIEND_REQUEST,
                                    'from': name,
                                    'pending': info['data'].get('pending_friend_requests', []),
                                })

        elif msg_type == 'friend_accept':
            target = msg.get('name', '').strip()
            if target and target != name:
                # 从自己的 pending 中移除
                pending = player_data.get('pending_friend_requests', [])
                if target in pending:
                    pending.remove(target)
                    # 双方互加好友
                    friends = player_data.setdefault('friends', [])
                    if target not in friends:
                        friends.append(target)
                    PlayerManager.save_player_data(name, player_data)
                    # 对方也加好友
                    target_data = PlayerManager.load_player_data(target)
                    if target_data:
                        t_friends = target_data.setdefault('friends', [])
                        if name not in t_friends:
                            t_friends.append(name)
                            PlayerManager.save_player_data(target, target_data)
                        # 通知对方更新好友列表
                        with self.lock:
                            for client, info in self.clients.items():
                                if info.get('name') == target and info.get('state') == 'playing':
                                    self._send_friend_list(client, target_data)
                self._send_friend_list(client_socket, player_data)
                # 发送更新后的 pending 列表
                self.send_to(client_socket, {
                    'type': FRIEND_REQUEST,
                    'pending': player_data.get('pending_friend_requests', []),
                })

        elif msg_type == 'friend_reject':
            target = msg.get('name', '').strip()
            if target:
                pending = player_data.get('pending_friend_requests', [])
                if target in pending:
                    pending.remove(target)
                    PlayerManager.save_player_data(name, player_data)
                # 发送更新后的 pending 列表
                self.send_to(client_socket, {
                    'type': FRIEND_REQUEST,
                    'pending': player_data.get('pending_friend_requests', []),
                })

        elif msg_type == 'friend_remove':
            target = msg.get('name', '').strip()
            friends = player_data.get('friends', [])
            if target in friends:
                friends.remove(target)
                PlayerManager.save_player_data(name, player_data)
                # 双向移除：从对方好友列表中也移除自己
                target_data = PlayerManager.load_player_data(target)
                if target_data:
                    t_friends = target_data.get('friends', [])
                    if name in t_friends:
                        t_friends.remove(name)
                        PlayerManager.save_player_data(target, target_data)
                    # 通知对方更新好友列表
                    with self.lock:
                        for client, info in self.clients.items():
                            if info.get('name') == target and info.get('state') == 'playing':
                                self._send_friend_list(client, target_data)
            self._send_friend_list(client_socket, player_data)

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

        elif msg_type == 'private_chat':
            target = msg.get('target', '').strip()
            if not target or not text:
                return
            # 仅好友之间可以私聊
            friends = player_data.get('friends', [])
            if target not in friends:
                self.send_to(client_socket, {
                    'type': SYSTEM,
                    'text': '只能向好友发送私聊消息。',
                })
                return
            display_name = f"[{player_data['level']}]{name}"
            current_time = datetime.now().strftime('%H:%M')
            dm_msg = {
                'type': PRIVATE_CHAT,
                'from': name,
                'from_display': display_name,
                'to': target,
                'text': text,
                'time': current_time,
            }
            # 持久化私聊消息（无论目标是否在线）
            self.dm_log_mgr.save(name, target, text)
            # 发送给目标玩家的所有连接 + 发送者的所有连接（多设备同步）
            with self.lock:
                for client, info in self.clients.items():
                    cname = info.get('name')
                    if info.get('state') != 'playing':
                        continue
                    if cname == target or cname == name:
                        self.send_to(client, dm_msg)
            print(f"[DM][{name} → {target}] {text}")

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
            # 名片数据
            pc = player_data.get('profile_card', {})
            pattern_id = pc.get('pattern_id', 'pattern_default')
            pattern_info = get_item_info(pattern_id) or {}
            status_data['profile_card'] = {
                'motto': pc.get('motto', ''),
                'name_color': pc.get('name_color', '#ffffff'),
                'motto_color': pc.get('motto_color', '#b3b3b3'),
                'border_color': pc.get('border_color', '#5a5a5a'),
                'pattern': pattern_info.get('pattern', {'chars': '.', 'colors': ['#505050']}),
                'pattern_id': pattern_id,
                'card_fields': pc.get('card_fields', ['level', 'gold', 'games', 'created']),
            }
            status_data['created_at'] = player_data.get('created_at', '')
            status_data['friends_count'] = len(player_data.get('friends', []))
            # 附带富物品信息供客户端直接渲染
            inv_raw = player_data.get('inventory', {})
            inv_list = []
            for item_id, val in inv_raw.items():
                info = get_item_info(item_id) or {}
                if isinstance(val, int):
                    # 兼容旧格式: 纯数量 → quality 0
                    if val > 0:
                        entry = {
                            'id': item_id,
                            'quality': 0,
                            'count': val,
                            'name': info.get('name', item_id),
                            'desc': info.get('desc', ''),
                            'category': info.get('category', ''),
                            'use_methods': info.get('use_methods', []),
                        }
                        if info.get('pattern'):
                            entry['pattern'] = info['pattern']
                        inv_list.append(entry)
                elif isinstance(val, dict):
                    for q_str, count in sorted(val.items()):
                        if isinstance(count, int) and count > 0:
                            entry = {
                                'id': item_id,
                                'quality': int(q_str),
                                'count': count,
                                'name': info.get('name', item_id),
                                'desc': info.get('desc', ''),
                                'category': info.get('category', ''),
                                'use_methods': info.get('use_methods', []),
                            }
                            if info.get('pattern'):
                                entry['pattern'] = info['pattern']
                            inv_list.append(entry)
            status_data['inventory'] = inv_list

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
