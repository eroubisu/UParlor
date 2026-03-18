"""维护任务 + 社交追踪"""

import time
from datetime import datetime

from .chat_log import get_beijing_now, get_today_date_str
from ..config import MAINTENANCE_HOUR
from ..player.manager import PlayerManager
from ..systems.titles import grant_title, check_all_titles
from ..msg_types import ACTION, SYSTEM


def check_and_grant_time_titles(player_data):
    """检查并授予所有满足条件的头衔（包括时间、社交、游戏等）"""
    check_all_titles(player_data)


def track_login_day(player_data):
    """记录登录天数并检查头衔"""
    today = datetime.now().strftime('%Y-%m-%d')
    social_stats = player_data.get('social_stats', {})
    last_login = social_stats.get('last_login_date', '')
    if today != last_login:
        social_stats['last_login_date'] = today
        social_stats['login_days'] = social_stats.get('login_days', 0) + 1
        player_data['social_stats'] = social_stats
        check_all_titles(player_data)
        PlayerManager.save_player_data(player_data['name'], player_data)


def track_chat_message(player_name, player_data):
    """记录聊天消息数并检查头衔"""
    social_stats = player_data.get('social_stats', {})
    social_stats['chat_messages'] = social_stats.get('chat_messages', 0) + 1
    player_data['social_stats'] = social_stats
    check_all_titles(player_data)


def maintenance_loop(server):
    """维护检查循环（在独立线程中运行）"""
    while server.running:
        now = get_beijing_now()
        if now.hour == MAINTENANCE_HOUR and now.minute == 0:
            today = get_today_date_str()
            if today != server.log_mgr.current_date:
                do_maintenance(server)
                time.sleep(60)
        time.sleep(30)


def do_maintenance(server):
    """执行每日维护"""
    print("[维护] 系统维护开始...")
    server.broadcast({
        'type': SYSTEM,
        'text': '[sys] 系统维护时间到，请在1分钟内保存数据并退出，服务器即将重置聊天记录...',
        'broadcast': True,
    })
    time.sleep(30)
    server.broadcast({
        'type': SYSTEM,
        'text': '[sys] 系统维护中，正在归档聊天记录...',
        'broadcast': True,
    })
    with server.lock:
        clients_to_close = list(server.clients.keys())
    for client in clients_to_close:
        try:
            server.send_to(client, {'type': ACTION, 'action': 'maintenance'})
        except Exception:
            pass
    time.sleep(5)
    for client in clients_to_close:
        server.remove_client(client)
    server.log_mgr.archive()
    server.dm_log_mgr.archive()
    print("[维护] 系统维护完成，服务器继续运行")
