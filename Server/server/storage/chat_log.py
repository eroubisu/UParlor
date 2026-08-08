"""聊天日志管理"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

from ..config import CHAT_LOG_DIR, CHAT_HISTORY_DIR, MAINTENANCE_HOUR
from ..msg_types import CHAT

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 内存中每频道最大消息数（防止长期运行内存增长）
_MAX_CHANNEL_MESSAGES = 2000
INITIAL_HISTORY_LIMIT = 16
HISTORY_PAGE_SIZE = 8


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
        self._lock = threading.Lock()
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

    def save(self, channel, name, text) -> dict | None:
        """保存并返回供广播使用的唯一规范记录。"""
        with self._lock:
            now = get_beijing_now()
            today = get_today_date_str()
            if today != self.current_date:
                if not self._archive_locked(today):
                    logger.error(
                        "聊天日界轮转失败，拒绝保存新日期消息: %s",
                        today)
                    return None
            msg = {
                'type': CHAT,
                'id': uuid.uuid4().hex,
                'name': name,
                'text': text,
                'channel': channel,
                'time': now.strftime('%H:%M:%S'),
            }
            msgs = self.chat_logs[channel]
            msgs.append(msg)
            # 内存截断：仅保留最近 _MAX_CHANNEL_MESSAGES 条
            if len(msgs) > _MAX_CHANNEL_MESSAGES:
                self.chat_logs[channel] = msgs[-_MAX_CHANNEL_MESSAGES:]
            self._dirty.add(channel)
            # 每 50 条消息刷盘一次（减少 IO 频率）
            if len(msgs) % 50 == 0:
                self._flush_locked()
        return msg

    def flush(self):
        """将脏频道数据写入磁盘"""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self):
        """内部刷盘（调用方已持锁）"""
        for channel in list(self._dirty):
            log_file = self._get_log_file(channel)
            try:
                with open(log_file, 'w', encoding='utf-8') as f:
                    json.dump(self.chat_logs[channel], f, ensure_ascii=False)
                self._dirty.discard(channel)
            except Exception:
                logger.exception("刷盘频道 %d 失败", channel)

    def archive(self) -> bool:
        """归档聊天记录到历史文件夹（每日维护时调用）"""
        with self._lock:
            return self._archive_locked(get_today_date_str())

    def _archive_locked(self, new_date: str) -> bool:
        """归档当前日志；调用方必须持有管理器锁。"""
        self._flush_locked()
        yesterday = self.current_date
        logger.info("正在归档 %s 的聊天记录...", yesterday)
        failed_channels = []
        for channel in [1, 2]:
            log_file = self._get_log_file(channel)
            if self.chat_logs[channel]:
                archive_file = os.path.join(CHAT_HISTORY_DIR, f'{yesterday}_channel_{channel}.json')
                try:
                    with open(archive_file, 'w', encoding='utf-8') as f:
                        json.dump(self.chat_logs[channel], f, ensure_ascii=False, indent=2)
                    logger.info("频道%d归档完成: %s", channel, archive_file)
                except Exception:
                    logger.exception("频道%d归档失败", channel)
                    failed_channels.append(channel)
                    continue
                if os.path.exists(log_file):
                    try:
                        os.remove(log_file)
                    except Exception:
                        logger.warning("旧日志文件删除失败: %s", log_file)
                self.chat_logs[channel] = []
                self._dirty.discard(channel)
        if failed_channels:
            logger.error(
                "归档未完成，保留频道数据等待重试: %s", failed_channels)
            return False
        self.current_date = new_date
        logger.info("归档完成，新的一天开始: %s", self.current_date)
        return True

    def get_history(self, channel, limit=INITIAL_HISTORY_LIMIT):
        """获取聊天历史（最近 limit 条）"""
        page, _ = self.get_history_page(channel, limit=limit)
        return page

    def get_history_page(
            self, channel: int, *, limit: int,
            before_id: str = '', after_id: str = '') -> tuple[list[dict], bool]:
        """Return a reverse-chronological page bounded by message identities."""
        with self._lock:
            messages = self._history_snapshot_locked(channel)
        start = 0
        if after_id:
            start = next((
                index + 1
                for index, message in enumerate(messages)
                if message.get('id') == after_id
            ), 0)
        end = len(messages)
        if before_id:
            end = next((
                index
                for index, message in enumerate(messages)
                if message.get('id') == before_id
            ), end)
        available = messages[start:end]
        page = available[-limit:]
        return list(page), len(available) > len(page)

    def _history_snapshot_locked(self, channel: int) -> list[dict]:
        """Merge archived days with the active in-memory day."""
        messages = []
        suffix = f'_channel_{channel}.json'
        if os.path.isdir(CHAT_HISTORY_DIR):
            for filename in sorted(os.listdir(CHAT_HISTORY_DIR)):
                if not filename.endswith(suffix):
                    continue
                path = os.path.join(CHAT_HISTORY_DIR, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as file:
                        archived = json.load(file)
                    if isinstance(archived, list):
                        messages.extend(archived)
                    else:
                        logger.error("聊天归档格式错误: %s", path)
                except (OSError, json.JSONDecodeError):
                    logger.exception("聊天归档读取失败: %s", path)
        messages.extend(self.chat_logs.get(channel, []))
        return messages
