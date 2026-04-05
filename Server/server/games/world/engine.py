"""开放世界引擎 — 城镇地图移动、建筑进入、NPC交互

per_player=True: 每个玩家独立引擎实例，但位置数据通过类变量共享。
玩家在城镇地图上用 hjkl 移动（支持数字前缀）。
走到门口自动提示可进入，enter 进入建筑。
"""

from __future__ import annotations

import time

from ...core.protocol import BaseGameEngine
from ...config import DEFAULT_LOCATION, DEFAULT_MAP
from .town_map import load_map, move_player, get_door, get_teleport, move_npcs_if_due, get_tile_damage, cleanup_map_runtime
from .fishing import cancel_fishing as _cancel_fishing
from .recall import cancel_recall as _cancel_recall, is_recalling, cleanup_player as _cleanup_recall
from ...systems.attributes import ensure_attributes, damage_hp, get_max_hp, heal_hp
from .movement import MovementMixin, _DIRECTIONS
from .follow import FollowMixin
from .social import SOCIAL_HANDLERS
from .building_handlers import BUILDING_HANDLERS


def _door_enter_label(door: dict) -> str:
    """根据目标地图的 map_type 返回操作标签"""
    target = load_map(door.get('building_id', ''))
    mt = target.get('meta', {}).get('map_type', '') if target else ''
    if mt == 'building':
        return '进入建筑'
    if mt == 'site':
        return '进入场所'
    if mt in ('world', 'road'):
        return f"前往{door.get('name', '')}"
    return '进入'


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
    _env_damage_last: dict[str, float] = {}      # {name: last_env_damage_time}

    def set_viewport(self, player_name: str, w: int, h: int):
        """设置玩家客户端视口尺寸"""
        WorldEngine._viewports[player_name] = (w, h)

    def _ensure_player(self, player_name: str, player_data: dict):
        """确保玩家有位置状态"""
        if player_name not in WorldEngine._positions:
            world_data = player_data.get('world', {})
            map_id = world_data.get('map', DEFAULT_MAP)
            pos = world_data.get('pos')
            map_data = load_map(map_id)
            if not map_data:
                # 存档中的地图不存在，回退到默认地图
                map_id = DEFAULT_MAP
                pos = None
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

    def _save_world_state(self, player_name: str, player_data: dict,
                          location: str | None = None):
        """保存位置到 player_data"""
        world = player_data.setdefault('world', {})
        world['map'] = WorldEngine._maps.get(player_name, DEFAULT_MAP)
        world['pos'] = WorldEngine._positions.get(player_name, [20, 14])
        if location is not None:
            world['location'] = location

    def _switch_map(self, player_name: str, new_map_id: str, spawn: list[int]) -> dict[str, list]:
        """切换玩家所在地图，返回需通知的 player_left + player_entered 消息"""
        old_map = WorldEngine._maps.get(player_name)
        old_pos = WorldEngine._positions.get(player_name)
        # 从旧地图移除
        if old_map and old_map in WorldEngine._map_players:
            WorldEngine._map_players[old_map].discard(player_name)
            if not WorldEngine._map_players[old_map]:
                del WorldEngine._map_players[old_map]
                cleanup_map_runtime(old_map)
        # 设置新地图
        WorldEngine._maps[player_name] = new_map_id
        WorldEngine._positions[player_name] = list(spawn)
        WorldEngine._map_players.setdefault(new_map_id, set()).add(player_name)
        # 通知旧地图视口内玩家该玩家离开
        send_to: dict[str, list] = {}
        if old_map and old_pos:
            for name in WorldEngine._map_players.get(old_map, ()):
                vr = self._player_viewport_range(name)
                if vr and self._in_viewport(vr, old_pos[0], old_pos[1]):
                    send_to.setdefault(name, []).append({
                        'type': 'game_event',
                        'game_type': 'world',
                        'event': 'player_left',
                        'data': {'name': player_name},
                    })
        # 通知新地图视口内玩家该玩家出现
        entered = self._notify_entered(player_name)
        for name, msgs in entered.items():
            send_to.setdefault(name, []).extend(msgs)
        return send_to

    # ── GameEngine Protocol ──

    def handle_command(self, lobby, player_name, player_data, cmd, args):
        self._ensure_player(player_name, player_data)
        ensure_attributes(player_data)
        map_id = WorldEngine._maps.get(player_name, DEFAULT_MAP)
        map_data = load_map(map_id)

        # 移动指令: /h /j /k /l [步数]
        direction_key = cmd.lstrip('/')
        if direction_key in _DIRECTIONS:
            return self._cmd_move(lobby, player_name, player_data,
                                  direction_key, map_id, map_data)

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

    def _cmd_move(self, lobby, player_name, player_data,
                  direction_key, map_id, map_data):
        """处理 hjkl 移动指令"""
        was_following = player_name in WorldEngine._following
        if was_following:
            self._unfollow(player_name)
        _cancel_fishing(player_name)
        was_recalling = _cancel_recall(player_name)
        if not self._check_cooldown(player_name, player_data,
                                       map_data, list(WorldEngine._positions[player_name])):
            return ""
        dx, dy = _DIRECTIONS[direction_key]
        old_pos = list(WorldEngine._positions[player_name])
        new_pos, door_name = move_player(map_data, old_pos, dx, dy, 1)
        WorldEngine._positions[player_name] = new_pos
        WorldEngine._facings[player_name] = (dx, dy)
        self._save_world_state(player_name, player_data)

        send_to_players = self._build_player_delta(
            player_name, old_pos, new_pos, map_id)
        follower_updates = self._move_followers(player_name, old_pos, map_id)
        for target, msgs in follower_updates.items():
            send_to_players.setdefault(target, []).extend(msgs)

        result = {
            'action': 'world_move',
            'send_to_caller': [self._build_map_update(player_name)],
            'send_to_players': send_to_players,
            'save': True,
            'refresh_commands': True,
        }
        if was_following:
            result['send_to_caller'].append({
                'type': 'game_event', 'game_type': 'world',
                'event': 'follow_cancelled', 'data': {},
            })
        if was_recalling:
            result['send_to_caller'].append({
                'type': 'game', 'text': '移动打断了回城。',
            })
        if door_name:
            result['send_to_caller'].append({
                'type': 'game',
                'text': f"\\[{door_name}] enter 通过",
            })
        # 传送点自动提示
        tp = get_teleport(map_data, new_pos[0], new_pos[1])
        if tp:
            result['send_to_caller'].append({
                'type': 'game', 'text': "\\[传送阵] interact 使用",
            })

        # 地块伤害
        tile_dmg = get_tile_damage(map_data, new_pos[0], new_pos[1])
        if tile_dmg > 0:
            actual = damage_hp(player_data, tile_dmg)
            if actual > 0:
                hp = player_data.get('attributes', {}).get('current_hp', 0)
                result['send_to_caller'].append({
                    'type': 'game',
                    'text': f"你受到了 {actual} 点地形伤害 (HP: {hp})",
                })

        # 环境伤害（地图级，按时间间隔触发）
        env_dmg = map_data.get('meta', {}).get('env_damage')
        if env_dmg:
            now = time.monotonic()
            last = WorldEngine._env_damage_last.get(player_name, 0.0)
            interval = env_dmg.get('interval', 10)
            if now - last >= interval:
                WorldEngine._env_damage_last[player_name] = now
                amount = env_dmg.get('amount', 1)
                actual = damage_hp(player_data, amount)
                if actual > 0:
                    hp = player_data.get('attributes', {}).get('current_hp', 0)
                    dmg_type = env_dmg.get('type', '环境')
                    result['send_to_caller'].append({
                        'type': 'game',
                        'text': f"你受到了 {actual} 点{dmg_type}伤害 (HP: {hp})",
                    })

        # 死亡惩罚: HP=0 时扣金币、降级、传送至出生点
        current_hp = player_data.get('attributes', {}).get('current_hp', 1)
        if current_hp <= 0:
            death_result = self._handle_death(
                lobby, player_name, player_data, map_id, map_data, result)
            if death_result:
                return death_result

        # NPC 巡逻（搭便车）
        npc_moves = move_npcs_if_due(map_id, map_data, WorldEngine._positions)
        if npc_moves:
            npc_event = {
                'type': 'game_event', 'game_type': 'world',
                'event': 'npc_moved',
                'data': [{'id': m['id'], 'old': m['old'], 'new': m['new'],
                           'char': m['char'], 'color': m['color'],
                           'name': m['name']} for m in npc_moves],
            }
            # 广播给同地图所有玩家（包括自己）
            result['send_to_caller'].append(npc_event)
            for name in WorldEngine._map_players.get(map_id, ()):
                if name != player_name:
                    send_to_players.setdefault(name, []).append(npc_event)

        return result

    def _handle_death(self, lobby, player_name, player_data, map_id, map_data, result):
        """死亡惩罚: 扣 0-50% 金币、降1级、传送至当前地图出生点、恢复满HP"""
        import random
        msgs = result.get('send_to_caller', [])
        send_to_players = result.get('send_to_players', {})

        # 扣金币 (0-50%)
        gold = player_data.get('gold', 0)
        if gold > 0:
            loss_pct = random.randint(0, 50)
            gold_loss = gold * loss_pct // 100
            if gold_loss > 0:
                player_data['gold'] = gold - gold_loss
                msgs.append({'type': 'game', 'text': f"你失去了 {gold_loss} 金币..."})

        # 降级 (最低1级)
        level = player_data.get('level', 1)
        if level > 1:
            player_data['level'] = level - 1
            player_data['exp'] = 0
            msgs.append({'type': 'game', 'text': f"等级降低至 {level - 1}..."})

        # 恢复满 HP
        max_hp = get_max_hp(player_data)
        player_data.setdefault('attributes', {})['current_hp'] = max_hp

        # 传送至当前地图出生点
        spawn = list(map_data.get('spawn', [20, 14]))
        old_pos = list(WorldEngine._positions[player_name])
        WorldEngine._positions[player_name] = spawn
        self._save_world_state(player_name, player_data)

        # 通知其他玩家位置变化
        delta = self._build_player_delta(player_name, old_pos, spawn, map_id)
        for target, m in delta.items():
            send_to_players.setdefault(target, []).extend(m)

        msgs.append({'type': 'game', 'text': '你倒下了... 在出生点苏醒。'})
        msgs.append(self._build_map_update(player_name))

        return {
            'action': 'world_move',
            'send_to_caller': msgs,
            'send_to_players': send_to_players,
            'save': True,
            'refresh_commands': True,
        }

    def handle_disconnect(self, lobby, player_name):
        # 清理钓鱼/回城状态
        _cancel_fishing(player_name)
        _cleanup_recall(player_name)
        # 清理跟随关系
        self._unfollow(player_name)
        # 释放该玩家的所有跟随者
        for fname in list(WorldEngine._followers.pop(player_name, ())):
            WorldEngine._following.pop(fname, None)
        WorldEngine._cooldowns.pop(player_name, None)
        WorldEngine._env_damage_last.pop(player_name, None)
        map_id = WorldEngine._maps.pop(player_name, None)
        old_pos = WorldEngine._positions.pop(player_name, None)
        WorldEngine._facings.pop(player_name, None)
        WorldEngine._viewports.pop(player_name, None)
        WorldEngine._last_move.pop(player_name, None)
        if map_id and map_id in WorldEngine._map_players:
            WorldEngine._map_players[map_id].discard(player_name)
            if not WorldEngine._map_players[map_id]:
                del WorldEngine._map_players[map_id]
                cleanup_map_runtime(map_id)
        send_to: dict[str, list] = {}
        # 通知同地图视口内玩家该玩家离开
        if map_id and old_pos:
            for name in WorldEngine._map_players.get(map_id, ()):
                vr = self._player_viewport_range(name)
                if vr and self._in_viewport(vr, old_pos[0], old_pos[1]):
                    send_to.setdefault(name, []).append({
                        'type': 'game_event',
                        'game_type': 'world',
                        'event': 'player_left',
                        'data': {'name': player_name},
                    })
        if send_to:
            return [{'action': 'player_disconnect',
                     'send_to_players': send_to}]
        return []

    def handle_back(self, lobby, player_name, player_data):
        """禁止传送 — 所有位置必须物理移动"""
        location = lobby.get_player_location(player_name)
        if location.startswith('world_'):
            return "请通过道路前往其他区域。"
        return "请通过门离开。"

    def handle_quit(self, lobby, player_name, player_data):
        """城镇是根位置，无法退出"""
        return self.handle_back(lobby, player_name, player_data)

    def get_welcome_message(self, player_data):
        player_name = player_data['name']
        self._ensure_player(player_name, player_data)
        ensure_attributes(player_data)
        location = player_data.get('world', {}).get('location', DEFAULT_LOCATION)
        # 通知同地图视口内玩家该玩家出现
        notify = self._notify_entered(player_name)
        result = {
            'action': 'location_update',
            'send_to_caller': [
                self._build_map_update(player_name),
                {'type': 'game', 'text': "欢迎回来"},
            ],
            'location': location,
        }
        if notify:
            result['send_to_players'] = notify
        return result

    def _notify_entered(self, player_name: str) -> dict[str, list]:
        """构建 player_entered 通知给同地图视口内的其他玩家"""
        map_id = WorldEngine._maps.get(player_name)
        pos = WorldEngine._positions.get(player_name)
        if not map_id or not pos:
            return {}
        send_to: dict[str, list] = {}
        for name in WorldEngine._map_players.get(map_id, ()):
            if name == player_name:
                continue
            vr = self._player_viewport_range(name)
            if vr and self._in_viewport(vr, pos[0], pos[1]):
                obs_pos = WorldEngine._positions.get(name, [0, 0])
                obs_vp = WorldEngine._viewports.get(name, (0, 0))
                obs_ox = obs_pos[0] - obs_vp[0] // 2
                obs_oy = obs_pos[1] - obs_vp[1] // 2
                send_to.setdefault(name, []).append({
                    'type': 'game_event',
                    'game_type': 'world',
                    'event': 'player_entered',
                    'data': {
                        'name': player_name,
                        'x': pos[0] - obs_ox,
                        'y': pos[1] - obs_oy,
                    },
                })
        return send_to

    def get_commands(self, lobby, location, player_name, player_data):
        """动态指令 — 根据位置和玩家状态返回可用操作指令"""
        if location.startswith('world_'):
            cmds = [
                {'name': 'interact', 'label': '交互', 'desc': '查看附近告示牌或传送点', 'tab': '操作'},
                {'name': 'talk', 'label': '交谈', 'desc': '与附近的NPC或玩家交谈', 'tab': '操作'},
                {'name': 'user', 'label': '玩家', 'desc': '查看附近玩家', 'tab': '操作'},
            ]
            # 仅当站在门上时显示 /enter
            pos = WorldEngine._positions.get(player_name)
            if pos:
                from .social import _check_on_door
                map_id = WorldEngine._maps.get(player_name, DEFAULT_MAP)
                map_data = load_map(map_id)
                if map_data and _check_on_door(map_data, pos):
                    door = get_door(map_data, pos[0], pos[1])
                    label = _door_enter_label(door) if door else '进入'
                    cmds.insert(0, {'name': 'enter', 'label': label,
                                    'desc': f'通过门 — {label}', 'tab': '操作'})
                if map_data:
                    # 钓鱼指令
                    from .fishing import is_fishing, has_fishing_rod, is_near_water_check
                    if is_fishing(player_name):
                        cmds.append({'name': 'pull', 'label': '收杆',
                                     'desc': '拉起鱼线', 'tab': '操作'})
                    elif (has_fishing_rod(player_data)
                          and is_near_water_check(map_data, pos)):
                        cmds.append({'name': 'fish', 'label': '钓鱼',
                                     'desc': '在水边钓鱼', 'tab': '操作'})
                    # 回城指令
                    if not is_recalling(player_name):
                        cmds.append({'name': 'recall', 'label': '回城',
                                     'desc': '吟唱4秒传送至出生点', 'tab': '操作'})
            return cmds
        # 建筑/场所: commands.json 特定指令 + 通用室内指令
        from . import _load_json
        local_cmds = _load_json('commands.json')
        cmds = [
            {'name': 'talk', 'label': '交谈', 'desc': '与NPC交谈', 'tab': '操作'},
        ]
        cmds.extend(local_cmds.get(location, []))
        # 站在出口门上时显示 /enter（标签显示"离开"）
        pos = WorldEngine._positions.get(player_name)
        if pos:
            from .social import _check_on_door
            map_id = WorldEngine._maps.get(player_name, DEFAULT_MAP)
            map_data = load_map(map_id)
            if map_data and _check_on_door(map_data, pos):
                cmds.insert(0, {'name': 'enter', 'label': '离开',
                                'desc': '从门口离开', 'tab': '操作'})
        return cmds

    def get_status_extras(self, player_name, player_data):
        """状态消息附加: 当前地图名和坐标"""
        map_id = WorldEngine._maps.get(player_name, DEFAULT_MAP)
        map_data = load_map(map_id)
        map_name = map_data.get('meta', {}).get('name', '') if map_data else ''
        pos = WorldEngine._positions.get(player_name, [0, 0])
        # 城镇地图名称（建筑内时取 town_map，城镇时取当前）
        world = player_data.get('world', {}) if player_data else {}
        town_map_id = world.get('town_map', map_id)
        if town_map_id == map_id:
            town_name = map_name
        else:
            td = load_map(town_map_id)
            town_name = td.get('meta', {}).get('name', '') if td else map_name
        return {
            'world_map': map_name,
            'world_pos': pos,
            'town_map_name': town_name,
        }

    def get_player_room_data(self, player_name):
        """返回地图视图数据"""
        self._ensure_player(player_name, {})
        return self._build_map_update(player_name).get('room_data')
