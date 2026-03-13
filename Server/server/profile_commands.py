"""个人资料页面指令 + 账号操作（rename / password / delete）"""

from .player_manager import PlayerManager
from .config import COMMAND_TABLE
from games import GAMES


def _build_profile_actions() -> str:
    """从 commands.json 自动生成个人资料页可用操作列表"""
    from .text_utils import pad_left
    cmds = COMMAND_TABLE.get('profile', [])
    # 也包含全局指令中常用的
    extras = [c for c in COMMAND_TABLE.get('*', [])
              if c.get('name') in ('back', 'home')]
    # 也包含大厅指令中与个人中心相关的
    personal = [c for c in COMMAND_TABLE.get('lobby', [])
                if c.get('name') in ('mytitle', 'alltitle')]
    all_cmds = personal + cmds + extras
    lines = []
    for c in all_cmds:
        lines.append(f"  {pad_left(c['name'], 14)} - {c['desc']}")
    return '\n'.join(lines)


def get_profile(lobby, player_data):
    """获取个人资料并进入profile页面"""
    player_name = player_data['name']
    inventory = player_data.get('inventory', {})
    rename_cards = inventory.get('rename_card', 0)

    lobby.set_player_location(player_name, 'profile')

    from .title_system import get_title_name
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    displayed = titles.get('displayed', [])
    displayed_names = ' | '.join(get_title_name(t) for t in displayed) if displayed else '(无)'

    # 从各游戏引擎收集资料附加行
    profile_extras = []
    for game_id in GAMES:
        engine = lobby._get_engine(game_id, player_name)
        if engine:
            line = engine.get_profile_extras(player_data)
            if line:
                profile_extras.append(line)
    extras_text = '\n'.join(f"{line}" for line in profile_extras)
    if extras_text:
        extras_text += '\n'

    return {
        'action': 'location_update',
        'message': (
            f"\n========== 个人资料 ==========\n"
            f"昵称: {player_data['name']}\n"
            f"等级: Lv.{player_data.get('level', 1)}\n"
            f"金币: {player_data.get('gold', 0)}G\n"
            f"{extras_text}"
            f"头衔: 【{displayed_names}】\n"
            f"饰品: {player_data.get('accessory', '无')}\n"
            f"改名卡: {rename_cards}张\n"
            f"注册时间: {player_data.get('created_at', '未知')}\n"
            f"\n==============================\n\n"
            f"【可用操作】\n{_build_profile_actions()}\n"
        )
    }


def handle_profile_command(lobby, player_name, player_data, cmd, args):
    """处理个人资料页面的指令（rename/password/delete）"""
    if cmd == '/rename':
        if not args:
            return "用法: rename <新用户名>"
        new_name = args
        rename_cards = player_data.get('inventory', {}).get('rename_card', 0)
        if rename_cards <= 0:
            return "你没有改名卡了。"
        if len(new_name) < 2 or len(new_name) > 12:
            return "用户名长度需要在2-12个字符之间。"
        if PlayerManager.player_exists(new_name):
            return f"用户名 '{new_name}' 已被使用。"
        lobby.pending_confirms[player_name] = {
            'type': 'rename',
            'data': new_name
        }
        return f"确定要将用户名改为 '{new_name}' 吗？（消耗1张改名卡）\n输入 y 确认，其他任意键取消。"

    if cmd == '/password':
        lobby.pending_confirms[player_name] = {'type': 'password_start'}
        return "请输入新密码（6-20个字符）："

    if cmd == '/delete':
        lobby.pending_confirms[player_name] = {'type': 'delete_start'}
        return "警告：删除账号不可恢复！\n请输入你的用户名以确认："

    return None


def do_rename(lobby, player_name, player_data, new_name):
    """执行改名"""
    if PlayerManager.player_exists(new_name):
        return f"用户名 '{new_name}' 已被使用。"

    inventory = player_data.get('inventory', {})
    rename_cards = inventory.get('rename_card', 0)

    old_name = player_name
    success = PlayerManager.rename_player(old_name, new_name)
    if not success:
        return '改名失败，请稍后重试。'

    inventory['rename_card'] = rename_cards - 1
    player_data['inventory'] = inventory
    player_data['name'] = new_name

    if old_name in lobby.online_players:
        lobby.online_players[new_name] = lobby.online_players.pop(old_name)
    location = lobby.player_locations.pop(old_name, 'lobby')
    lobby.player_locations[new_name] = location

    PlayerManager.save_player_data(new_name, player_data)

    return {
        'action': 'rename_success',
        'old_name': old_name,
        'new_name': new_name,
        'message': f"用户名已改为 '{new_name}'！\n剩余改名卡: {rename_cards - 1}张"
    }


def do_change_password(player_name, new_password):
    """执行修改密码"""
    success = PlayerManager.change_password(player_name, new_password)
    if success:
        return '密码修改成功！'
    return '密码修改失败，请稍后重试。'


def do_delete_account(lobby, player_name, password):
    """执行删除账号"""
    if not PlayerManager.verify_password(player_name, password):
        return '密码错误。账号删除已取消。'

    for game_id, engine in lobby.game_engines.items():
        if engine.get_player_room(player_name):
            engine.leave_room(player_name)

    success = PlayerManager.delete_player(player_name)
    if success:
        lobby.online_players.pop(player_name, None)
        lobby.player_locations.pop(player_name, None)
        return {'action': 'account_deleted', 'message': '账号已删除。再见！'}
    return '删除账号失败，请稍后重试。'
