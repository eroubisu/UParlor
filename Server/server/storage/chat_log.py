"""聊天日志管理"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from ..config import CHAT_LOG_DIR, CHAT_HISTORY_DIR, MAINTENANCE_HOUR

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 内存中每频道最大消息数（防止长期运行内存增长）
_MAX_CHANNEL_MESSAGES = 2000


def get_beijing_now():
    """获取北京时间"""
    return datetime.now(BEIJING_TZ)


def get_today_date_str():
    """获取今天的日期字符串（以凌晨4点为分界）"""
    now = get_beijing_now()
    if now.hour < MAINTENANCE_HOUR:
        date = now.date() - timedelta(days=1)
    else:
        date = now.date()
    return date.strftime('%Y-%m-%d')


class ChatLogManager:
    """聊天日志管理器 — 管理聊天记录的加载、保存和归档"""

    def __init__(self):
        self.chat_logs = {1: [], 2: []}
        self.current_date = get_today_date_str()
        self._dirty: set[int] = set()  # 有未写入磁盘的频道
        self._load()

    def _get_log_file(self, channel):
        """获取当前日期的聊天记录文件路径"""
        return os.path.join(CHAT_LOG_DIR, f'channel_{channel}_{self.current_date}.json')

    def _check_and_archive_old(self):
        """启动时检查并归档过期的聊天记录"""
        today = get_today_date_str()
        for filename in os.listdir(CHAT_LOG_DIR):
            if not filename.startswith('channel_') or not filename.endswith('.json'):
                continue
            parts = filename.replace('.json', '').split('_')
            if len(parts) != 3:
                continue
            try:
                file_date = parts[2]
                if file_date != today:
                    channel = int(parts[1])
                    self._archive_file(channel, file_date)
            except Exception:
                continue

    def _archive_file(self, channel, file_date):
        """归档指定日期的聊天记录"""
        log_file = os.path.join(CHAT_LOG_DIR, f'channel_{channel}_{file_date}.json')
        if not os.path.exists(log_file):
            return
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            if messages:
                archive_file = os.path.join(CHAT_HISTORY_DIR, f'{file_date}_channel_{channel}.json')
                with open(archive_file, 'w', encoding='utf-8') as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                logger.info("启动归档 %s 频道%d -> %s", file_date, channel, archive_file)
            os.remove(log_file)
        except Exception:
            logger.exception("启动归档失败 %s", log_file)

    def _load(self):
        """加载当天的聊天记录"""
        self._check_and_archive_old()
        self.current_date = get_today_date_str()
        for channel in [1, 2]:
            log_file = self._get_log_file(channel)
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        self.chat_logs[channel] = json.load(f)
                except Exception:
                    self.chat_logs[channel] = []
            else:
                self.chat_logs[channel] = []
        logger.info("聊天记录已加载: %s", self.current_date)

    def save(self, channel, name, text):
        """保存一条聊天记录（标记脏页，延迟写盘）"""
        now = get_beijing_now()
        msg = {'name': name, 'text': text, 'time': now.strftime('%H:%M')}
        msgs = self.chat_logs[channel]
        msgs.append(msg)
        # 内存截断：仅保留最近 _MAX_CHANNEL_MESSAGES 条
        if len(msgs) > _MAX_CHANNEL_MESSAGES:
            self.chat_logs[channel] = msgs[-_MAX_CHANNEL_MESSAGES:]
        self._dirty.add(channel)
        # 每 50 条消息刷盘一次（减少 IO 频率）
        if len(msgs) % 50 == 0:
            self.flush()

    def flush(self):
        """将脏频道数据写入磁盘"""
        for channel in list(self._dirty):
            log_file = self._get_log_file(channel)
            try:
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(self.chat_logs[channel], f, ensure_ascii=False)
            except Exception:
                logger.exception("刷盘频道 %d 失败", channel)
        self._dirty.clear()

    def archive(self):
        """归档聊天记录到历史文件夹（每日维护时调用）"""
        self.flush()
        yesterday = self.current_date
        logger.info("正在归档 %s 的聊天记录...", yesterday)
        for channel in [1, 2]:
            log_file = self._get_log_file(channel)
            if os.path.exists(log_file) and self.chat_logs[channel]:
                archive_file = os.path.join(CHAT_HISTORY_DIR, f'{yesterday}_channel_{channel}.json')
                try:
                    with open(archive_file, 'w', encoding='utf-8') as f:
                        json.dump(self.chat_logs[channel], f, ensure_ascii=False, indent=2)
                    logger.info("频道%d归档完成: %s", channel, archive_file)
                except Exception:
                    logger.exception("频道%d归档失败", channel)
                try:
                    os.remove(log_file)
                except Exception:
                    logger.warning("旧日志文件删除失败: %s", log_file)
        self.chat_logs = {1: [], 2: []}
        self.current_date = get_today_date_str()
        logger.info("归档完成，新的一天开始: %s", self.current_date)

    def get_history(self, channel, limit=50):
        """获取聊天历史（最近 limit 条）"""
        messages = self.chat_logs.get(channel, [])
        return messages[-limit:] if len(messages) > limit else messages
