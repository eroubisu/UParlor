"""账号操作工具函数（rename / password / delete）"""

from ..player.manager import PlayerManager
from ..systems.items import inv_get, inv_sub


def do_rename(lobby, player_name, player_data, new_name, quality=0):
    """执行改名"""
    if PlayerManager.player_exists(new_name):
        return f"用户名 '{new_name}' 已被使用。"

    inventory = player_data.get('inventory', {})

    old_name = player_name
    success = PlayerManager.rename_player(old_name, new_name)
    if not success:
        return '改名失败，请稍后重试。'

    inv_sub(inventory, 'rename_card', quality)
    player_data['inventory'] = inventory
    player_data['name'] = new_name

    if old_name in lobby.online_players:
        lobby.online_players[new_name] = lobby.online_players.pop(old_name)
    location = lobby.player_locations.pop(old_name, 'lobby')
    lobby.player_locations[new_name] = location

    PlayerManager.save_player_data(new_name, player_data)

    remaining = inv_get(inventory, 'rename_card', quality)
    return {
        'action': 'rename_success',
        'old_name': old_name,
        'new_name': new_name,
        'message': f"用户名已改为 '{new_name}'！\n剩余改名卡: {remaining}张"
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
