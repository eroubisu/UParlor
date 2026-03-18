"""开放世界引擎 — 城镇地图移动、建筑进入、NPC交互

per_player=True: 每个玩家独立引擎实例，但位置数据通过类变量共享。
玩家在城镇地图上用 hjkl 移动（支持数字前缀）。
走到门口自动提示可进入，/enter 进入建筑。
"""

from __future__ import annotations

from ...game.protocol import BaseGameEngine
from ...systems.town_map import load_map, move_player
from ...systems.attributes import ensure_attributes
from .movement import MovementMixin, _DIRECTIONS
from .follow import FollowMixin
from .social import SOCIAL_HANDLERS
from .building_handlers import BUILDING_HANDLERS


class WorldEngine(MovementMixin, FollowMixin, BaseGameEngine):
    """开放世界引擎 — 玩家制（每人独立实例，位置共享）"""

    # ── 类变量：所有实例共享 ──
    _positions: dict[str, list[int]] = {}        # {name: [x, y]}
    _maps: dict[str, str] = {}                   # {name: map_id}
    _facings: dict[str, tuple[int, int]] = {}    # {name: (dx, dy)}
    _viewports: dict[str, tuple[int, int]] = {}  # {name: (w, h)}
    _map_players: dict[str, set[str]] = {}       # {map_id: {name, ...}}
    _last_move: dict[str, float] = {}            # {name: timestamp}
    _following: dict[str, str] = {}              # {follower: leader}
    _followers: dict[str, set[str]] = {}         # {leader: {followers}}
    _cooldowns: dict[str, float] = {}            # {name: last_known_cooldown}

    def set_viewport(self, player_name: str, w: int, h: int):
        """设置玩家客户端视口尺寸"""
        WorldEngine._viewports[player_name] = (w, h)

    def _ensure_player(self, player_name: str, player_data: dict):
        """确保玩家有位置状态"""
        if player_name not in WorldEngine._positions:
            world_data = player_data.get('world', {})
            map_id = world_data.get('map', 'starter_town')
            pos = world_data.get('pos')
            map_data = load_map(map_id)
            if pos and map_data:
                WorldEngine._positions[player_name] = list(pos)
            elif map_data:
                WorldEngine._positions[player_name] = list(map_data.get('spawn', [20, 14]))
            else:
                WorldEngine._positions[player_name] = [20, 14]
            WorldEngine._maps[player_name] = map_id
            WorldEngine._facings[player_name] = (0, 1)
            WorldEngine._map_players.setdefault(map_id, set()).add(player_name)

    def _save_world_state(self, player_name: str, player_data: dict):
        """保存位置到 player_data"""
        world = player_data.setdefault('world', {})
        world['map'] = WorldEngine._maps.get(player_name, 'starter_town')
        world['pos'] = WorldEngine._positions.get(player_name, [20, 14])

    # ── GameEngine Protocol ──

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        self._ensure_player(player_name, player_data)
        ensure_attributes(player_data)
        map_id = WorldEngine._maps.get(player_name, 'starter_town')
        map_data = load_map(map_id)

        # 移动指令: /h /j /k /l [步数]
        direction_key = cmd.lstrip('/')
        if direction_key in _DIRECTIONS:
            # 正在跟随别人 → 自动退出跟随
            if player_name in WorldEngine._following:
                self._unfollow(player_name)
            if not self._check_cooldown(player_name, player_data):
                return ""  # 冷却中，静默忽略
            dx, dy = _DIRECTIONS[direction_key]
            steps = 1
            if args:
                try:
                    steps = max(1, min(int(args), 50))
                except ValueError:
                    steps = 1
            old_pos = list(WorldEngine._positions[player_name])
            new_pos, door_name = move_player(map_data, old_pos, dx, dy, steps)
            WorldEngine._positions[player_name] = new_pos
            WorldEngine._facings[player_name] = (dx, dy)
            self._save_world_state(player_name, player_data)

            send_to_players = self._build_player_delta(
                player_name, old_pos, new_pos, map_id)
            # 带动跟随者（每人移到其直接领队的旧位置）
            follower_updates = self._move_followers(player_name, old_pos, map_id)
            for target, msgs in follower_updates.items():
                send_to_players.setdefault(target, []).extend(msgs)

            result = {
                'action': 'world_move',
                'send_to_caller': [self._build_map_update(player_name)],
                'send_to_players': send_to_players,
                'save': True,
            }
            if door_name:
                result['send_to_caller'].append({
                    'type': 'game',
                    'text': f"[{door_name}] 的入口 — 输入 /enter 进入",
                })
            return result

        # 社交/交互指令
        social_handler = SOCIAL_HANDLERS.get(direction_key)
        if social_handler:
            return social_handler(self, lobby, player_name, player_data,
                                  args, map_id, map_data)

        # 建筑子位置指令
        location = lobby.get_player_location(player_name)
        handler = BUILDING_HANDLERS.get(direction_key)
        if handler:
            return handler(lobby, player_name, player_data, args, location)

        return None

    def handle_disconnect(self, lobby, player_name):
        # 清理跟随关系
        self._unfollow(player_name)
        # 释放该玩家的所有跟随者
        for fname in list(WorldEngine._followers.pop(player_name, ())):
            WorldEngine._following.pop(fname, None)
        WorldEngine._cooldowns.pop(player_name, None)
        map_id = WorldEngine._maps.pop(player_name, None)
        old_pos = WorldEngine._positions.pop(player_name, None)
        WorldEngine._facings.pop(player_name, None)
        WorldEngine._viewports.pop(player_name, None)
        WorldEngine._last_move.pop(player_name, None)
        if map_id and map_id in WorldEngine._map_players:
            WorldEngine._map_players[map_id].discard(player_name)
            if not WorldEngine._map_players[map_id]:
                del WorldEngine._map_players[map_id]
        # 通知同地图视口内玩家该玩家离开
        if map_id and old_pos:
            send_to: dict[str, list] = {}
            for name in WorldEngine._map_players.get(map_id, ()):
                vr = self._player_viewport_range(name)
                if vr and self._in_viewport(vr, old_pos[0], old_pos[1]):
                    send_to[name] = [{
                        'type': 'game_event',
                        'game_type': 'world',
                        'event': 'player_left',
                        'data': {'name': player_name},
                    }]
            if send_to:
                return [{'action': 'player_disconnect',
                         'send_to_players': send_to}]
        return []

    def handle_back(self, lobby, player_name, player_data):
        """从建筑子位置返回城镇"""
        location = lobby.get_player_location(player_name)
        # 已在城镇根位置
        if location == 'world_town':
            return "你已经在城镇中了。"
        # 从建筑返回城镇
        lobby.set_player_location(player_name, 'world_town')
        return {
            'action': 'location_update',
            'send_to_caller': [
                self._build_map_update(player_name),
                {'type': 'game', 'text': "回到了城镇。"},
            ],
            'location': 'world_town',
        }

    def handle_quit(self, lobby, player_name, player_data):
        """城镇是根位置，无法退出"""
        return self.handle_back(lobby, player_name, player_data)

    def get_welcome_message(self, player_data):
        player_name = player_data['name']
        self._ensure_player(player_name, player_data)
        ensure_attributes(player_data)
        return {
            'action': 'location_update',
            'send_to_caller': [
                self._build_map_update(player_name),
                {'type': 'game', 'text': "欢迎回来"},
            ],
            'location': 'world_town',
        }

    def get_commands(self, lobby, location, player_name, player_data):
        """动态指令 — 根据位置返回操作指令"""
        if location == 'world_town':
            return [
                {'name': 'enter', 'label': '进入建筑', 'desc': '在门口时进入建筑', 'tab': '操作'},
                {'name': 'talk', 'label': '交谈', 'desc': '与附近的NPC或玩家交谈', 'tab': '操作'},
                {'name': 'user', 'label': '玩家', 'desc': '查看附近玩家', 'tab': '操作'},
                {'name': 'follow', 'label': '跟随', 'desc': '跟随附近玩家', 'tab': '操作'},
                {'name': 'unfollow', 'label': '取消跟随', 'desc': '停止跟随', 'tab': '操作'},
                {'name': 'map', 'label': '地图', 'desc': '刷新当前地图', 'tab': '操作'},
            ]
        # 建筑子位置: 从游戏模块的 commands.json 加载
        from . import _load_json
        local_cmds = _load_json('commands.json')
        return local_cmds.get(location, [])

    def get_status_extras(self, player_name, player_data):
        """状态消息附加: 当前地图名和坐标"""
        map_id = WorldEngine._maps.get(player_name, 'starter_town')
        map_data = load_map(map_id)
        map_name = map_data.get('meta', {}).get('name', '') if map_data else ''
        pos = WorldEngine._positions.get(player_name, [0, 0])
        return {
            'world_map': map_name,
            'world_pos': pos,
        }

    def get_player_room_data(self, player_name):
        """返回地图视图数据"""
        self._ensure_player(player_name, {})
        return self._build_map_update(player_name).get('room_data')
