"""私聊日志管理 — 持久化存储私信记录，支持多设备历史同步"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid

from ..config import DM_LOG_DIR, DM_HISTORY_DIR
from ..msg_types import PRIVATE_CHAT
from .chat_log import get_beijing_now, get_today_date_str

logger = logging.getLogger(__name__)


def _pair_key(name_a: str, name_b: str) -> str:
    """生成双方对话的唯一目录名（字母排序 + 双下划线分隔）"""
    a, b = sorted([name_a.lower(), name_b.lower()])
    return f"{a}__{b}"


class DMLogManager:
    """私聊日志管理器 — 管理私信记录的保存、加载和归档

    存储结构：
      data/dm_logs/{pair_key}/{YYYY-MM-DD}.json
      data/dm_logs/history/{pair_key}/{YYYY-MM-DD}.json
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.current_date = get_today_date_str()
        # 内存缓存：{pair_key: [msg, ...]}
        self._cache: dict[str, list[dict]] = {}
        self._ensure_dirs()
        self._check_and_archive_old()

    def _ensure_dirs(self):
        os.makedirs(DM_LOG_DIR, exist_ok=True)
        os.makedirs(DM_HISTORY_DIR, exist_ok=True)

    def _log_dir(self, pair: str) -> str:
        return os.path.join(DM_LOG_DIR, pair)

    def _log_file(self, pair: str, date: str | None = None) -> str:
        d = date or self.current_date
        return os.path.join(self._log_dir(pair), f"{d}.json")

    def _load_pair(self, pair: str) -> list[dict]:
        """加载某对话今天的消息到缓存"""
        path = self._log_file(pair)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save(
        self, from_name: str, to_name: str, text: str,
    ) -> dict:
        """保存并返回供双方发送的唯一规范记录。"""
        pair = _pair_key(from_name, to_name)
        with self._lock:
            now = get_beijing_now()
            today = get_today_date_str()
            if today != self.current_date:
                self._archive_locked(today)
            msg = {
                'type': PRIVATE_CHAT,
                'id': uuid.uuid4().hex,
                'from': from_name,
                'to': to_name,
                'text': text,
                'time': now.strftime('%H:%M:%S'),
            }
            if pair not in self._cache:
                self._cache[pair] = self._load_pair(pair)
            self._cache[pair].append(msg)
            # 刷盘
            pair_dir = self._log_dir(pair)
            os.makedirs(pair_dir, exist_ok=True)
            path = self._log_file(pair)
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self._cache[pair], f, ensure_ascii=False)
            except Exception:
                logger.exception("私聊日志写入失败: %s", path)
        return msg

    def get_history(self, name_a: str, name_b: str, limit: int = 50) -> list[dict]:
        """获取两人之间的最近 limit 条私聊消息（跨天合并）"""
        pair = _pair_key(name_a, name_b)
        with self._lock:
            files = []
            pair_dirs = (
                (0, os.path.join(DM_HISTORY_DIR, pair)),
                (1, self._log_dir(pair)),
            )
            for source_order, pair_dir in pair_dirs:
                if not os.path.isdir(pair_dir):
                    continue
                for fn in os.listdir(pair_dir):
                    if fn.endswith('.json'):
                        files.append((
                            fn[:-5], source_order, os.path.join(pair_dir, fn)))

            messages = []
            for file_info in sorted(files):
                path = file_info[2]
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        day_msgs = json.load(f)
                    messages.extend(day_msgs)
                except Exception:
                    continue
            return messages[-limit:]

    def get_all_peers(self, player_name: str) -> list[str]:
        """获取某玩家有过私聊的所有对方名字"""
        peers = []
        if not os.path.isdir(DM_LOG_DIR):
            return peers
        lower_name = player_name.lower()
        for entry in os.listdir(DM_LOG_DIR):
            pair_dir = os.path.join(DM_LOG_DIR, entry)
            if not os.path.isdir(pair_dir) or '__' not in entry:
                continue
            parts = entry.split('__')
            if len(parts) != 2:
                continue
            if lower_name in parts:
                # 找到对方名字（原始大小写需要从消息中恢复）
                other = parts[1] if parts[0] == lower_name else parts[0]
                peers.append(other)
        # 也检查归档目录
        if os.path.isdir(DM_HISTORY_DIR):
            for entry in os.listdir(DM_HISTORY_DIR):
                hist_dir = os.path.join(DM_HISTORY_DIR, entry)
                if not os.path.isdir(hist_dir) or '__' not in entry:
                    continue
                parts = entry.split('__')
                if len(parts) != 2:
                    continue
                if lower_name in parts:
                    other = parts[1] if parts[0] == lower_name else parts[0]
                    if other not in peers:
                        peers.append(other)
        return peers

    def get_dm_peer_names(self, player_name: str) -> list[str]:
        """获取所有私聊 peer 的显示名（原始大小写）"""
        peers = self.get_all_peers(player_name)
        result = []
        for peer_lower in peers:
            msgs = self.get_history(player_name, peer_lower, limit=1)
            if not msgs:
                continue
            display = peer_lower
            for m in msgs:
                if m.get('from', '').lower() == peer_lower:
                    display = m['from']
                    break
                if m.get('to', '').lower() == peer_lower:
                    display = m['to']
                    break
            result.append(display)
        return result

    def archive(self):
        """归档旧日志（每日维护时调用）"""
        with self._lock:
            self._archive_locked(get_today_date_str())

    def _archive_locked(self, new_date: str):
        """归档旧日志；调用方必须持有管理器锁。"""
        yesterday = self.current_date
        logger.info("正在归档 %s 的私聊记录...", yesterday)
        archived = 0
        if os.path.isdir(DM_LOG_DIR):
            for entry in os.listdir(DM_LOG_DIR):
                pair_dir = os.path.join(DM_LOG_DIR, entry)
                if not os.path.isdir(pair_dir) or '__' not in entry:
                    continue
                for fn in os.listdir(pair_dir):
                    if not fn.endswith('.json'):
                        continue
                    file_date = fn.replace('.json', '')
                    if file_date == new_date:
                        continue
                    src = os.path.join(pair_dir, fn)
                    hist_pair_dir = os.path.join(DM_HISTORY_DIR, entry)
                    os.makedirs(hist_pair_dir, exist_ok=True)
                    dst = os.path.join(hist_pair_dir, fn)
                    try:
                        os.rename(src, dst)
                        archived += 1
                    except Exception:
                        logger.exception("私聊归档失败 %s", src)
            for entry in os.listdir(DM_LOG_DIR):
                pair_dir = os.path.join(DM_LOG_DIR, entry)
                if os.path.isdir(pair_dir) and '__' in entry:
                    try:
                        if not os.listdir(pair_dir):
                            os.rmdir(pair_dir)
                    except Exception:
                        pass
        self._cache.clear()
        self.current_date = new_date
        if archived:
            logger.info("私聊归档完成: %d 个文件", archived)

    def _check_and_archive_old(self):
        """启动时检查并归档过期的私聊记录"""
        with self._lock:
            self._archive_locked(get_today_date_str())
