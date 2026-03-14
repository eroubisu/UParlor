"""聊天日志管理"""

import os
import json
from datetime import datetime, timedelta, timezone

from ..config import CHAT_LOG_DIR, CHAT_HISTORY_DIR, MAINTENANCE_HOUR

BEIJING_TZ = timezone(timedelta(hours=8))


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
                print(f"[启动归档] {file_date} 频道{channel} -> {archive_file}")
            os.remove(log_file)
        except Exception as e:
            print(f"[启动归档] 归档失败 {log_file}: {e}")

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
        print(f"[聊天记录] 已加载 {self.current_date} 的记录")

    def save(self, channel, name, text):
        """保存一条聊天记录"""
        now = get_beijing_now()
        msg = {'name': name, 'text': text, 'time': now.strftime('%H:%M:%S')}
        self.chat_logs[channel].append(msg)
        log_file = self._get_log_file(channel)
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(self.chat_logs[channel], f, ensure_ascii=False)
        except Exception:
            pass

    def archive(self):
        """归档聊天记录到历史文件夹（每日维护时调用）"""
        yesterday = self.current_date
        print(f"[维护] 正在归档 {yesterday} 的聊天记录...")
        for channel in [1, 2]:
            log_file = self._get_log_file(channel)
            if os.path.exists(log_file) and self.chat_logs[channel]:
                archive_file = os.path.join(CHAT_HISTORY_DIR, f'{yesterday}_channel_{channel}.json')
                try:
                    with open(archive_file, 'w', encoding='utf-8') as f:
                        json.dump(self.chat_logs[channel], f, ensure_ascii=False, indent=2)
                    print(f"[维护] 频道{channel}归档完成: {archive_file}")
                except Exception as e:
                    print(f"[维护] 频道{channel}归档失败: {e}")
                try:
                    os.remove(log_file)
                except Exception:
                    pass
        self.chat_logs = {1: [], 2: []}
        self.current_date = get_today_date_str()
        print(f"[维护] 归档完成，新的一天开始: {self.current_date}")

    def get_history(self, channel, limit=50):
        """获取聊天历史（最近 limit 条）"""
        messages = self.chat_logs.get(channel, [])
        return messages[-limit:] if len(messages) > limit else messages
