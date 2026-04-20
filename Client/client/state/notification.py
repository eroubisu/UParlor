"""通知状态 — 系统通知 + 好友申请 + 游戏邀请"""

from __future__ import annotations

import time

from .base import BaseState


class NotificationState(BaseState):
    """通知面板的全部状态 — 系统通知 + 好友申请 + 游戏邀请"""

    _MAX_NOTIFICATIONS = 200

    def __init__(self):
        super().__init__()
        self.system_notifications: list[str] = []
        # 好友申请: [{name, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.friend_requests: list[dict] = []
        # 游戏邀请: [{from, game, room_id, status}]  status = 'pending' | 'accepted' | 'rejected'
        self.game_invites: list[dict] = []
        self.tab: str = "system"
        self.cursor: int = 0
        self.badge_seen: bool = False  # 打开通知面板后标记为已读

    def set_friend_requests(self, names: list[str]):
        """设置完整的好友申请列表（服务端推送的待处理列表）"""
        self.badge_seen = False
        # 保留已处理的记录，更新 pending 列表
        existing = {r['name']: r for r in self.friend_requests}
        new_list = []
        for name in names:
            if name in existing:
                # 已存在的保持原状态
                new_list.append(existing[name])
            else:
                new_list.append({'name': name, 'status': 'pending'})
        # 保留已处理但不在新 pending 列表中的记录
        for r in self.friend_requests:
            if r['status'] != 'pending' and r['name'] not in names:
                new_list.append(r)
        self.friend_requests = new_list
        self._notify('update_friend_requests')

    def add_friend_request(self, from_name: str):
        """新增一条好友申请"""
        self.badge_seen = False
        for r in self.friend_requests:
            if r['name'] == from_name:
                # 如果已存在，重置为 pending
                r['status'] = 'pending'
                self._notify('update_friend_requests')
                return
        self.friend_requests.append({'name': from_name, 'status': 'pending'})
        self._notify('update_friend_requests')

    @property
    def unread_count(self) -> int:
        """未读(pending)好友申请数量"""
        return sum(1 for r in self.friend_requests if r['status'] == 'pending')

    # ── 游戏邀请 ──

    def add_game_invite(self, from_name: str, game: str, room_id: str,
                        expires_in: int = 300):
        """新增游戏邀请（同一游戏同一人只保留最新）"""
        self.badge_seen = False
        self.game_invites = [
            inv for inv in self.game_invites
            if not (inv['from'] == from_name and inv['game'] == game)
        ]
        self.game_invites.append({
            'from': from_name, 'game': game,
            'room_id': room_id, 'status': 'pending',
            'expires_at': time.time() + expires_in,
        })
        self._notify('update_game_invites')

    def mark_game_invite(self, from_name: str, game: str, status: str):
        """标记游戏邀请状态: 'accepted' | 'rejected'"""
        for inv in self.game_invites:
            if inv['from'] == from_name and inv['game'] == game:
                inv['status'] = status
                break
        self._notify('update_game_invites')

    def remove_game_invite(self, from_name: str, game: str):
        """删除游戏邀请记录"""
        self.game_invites = [
            inv for inv in self.game_invites
            if not (inv['from'] == from_name and inv['game'] == game)
        ]
        self._notify('update_game_invites')

    @property
    def unread_game_count(self) -> int:
        """未读(pending且未过期)游戏邀请数量"""
        now = time.time()
        return sum(
            1 for inv in self.game_invites
            if inv['status'] == 'pending' and inv.get('expires_at', 0) > now
        )

    def add_system_notification(self, text: str):
        self.system_notifications.append(text)
        if len(self.system_notifications) > self._MAX_NOTIFICATIONS:
            self.system_notifications = self.system_notifications[-self._MAX_NOTIFICATIONS:]
        self._notify('add_system_notification', text)

    def mark_badge_seen(self):
        """标记通知已读"""
        self.badge_seen = True
        self._notify('badge_seen')
