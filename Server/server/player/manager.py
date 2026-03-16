"""
玩家数据管理 — 多文件存储

目录结构:
  data/users/{name}/
    auth.json       — name, password_hash, created_at
    profile.json    — level, exp, gold, accessory, social_stats
    game_stats.json — game_stats
    inventory.json  — inventory
    titles.json     — titles
    layout.json     — window_layout
    ai.json         — ai_companions
    games/
      {game_id}.json — 游戏专属数据
"""

import os
import json
import shutil
from werkzeug.security import generate_password_hash, check_password_hash
from ..config import USERS_DIR
from .schema import get_default_user_template, ensure_user_schema


# ── 模块映射：固定 key → 文件名 ──

_MODULE_MAP = {
    'auth':       ('name', 'password_hash', 'created_at'),
    'profile':    ('level', 'exp', 'gold', 'accessory', 'social_stats', 'friends'),
    'game_stats': ('game_stats',),
    'inventory':  ('inventory',),
    'titles':     ('titles',),
    'layout':     ('window_layout',),
    'ai':         ('ai_companions',),
}

_KEY_TO_MODULE = {}
for _mod, _keys in _MODULE_MAP.items():
    for _k in _keys:
        _KEY_TO_MODULE[_k] = _mod

_ALL_KNOWN_KEYS = set(_KEY_TO_MODULE)


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class PlayerManager:
    """玩家数据管理 - 注册、登录、存档"""

    @staticmethod
    def hash_password(password):
        return generate_password_hash(password)

    @staticmethod
    def _verify_hash(stored_hash, password):
        if stored_hash and len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash):
            import hashlib
            return stored_hash == hashlib.sha256(password.encode()).hexdigest()
        return check_password_hash(stored_hash, password)

    # ── 路径 ──

    @staticmethod
    def _get_user_dir(name):
        return os.path.join(USERS_DIR, name)

    @staticmethod
    def _get_legacy_file(name):
        return os.path.join(USERS_DIR, f'{name}.json')

    @staticmethod
    def player_exists(name):
        return os.path.isdir(PlayerManager._get_user_dir(name)) or \
               os.path.exists(PlayerManager._get_legacy_file(name))

    # ── 底层读写 ──

    @staticmethod
    def _load_user_file(name):
        """加载用户全部数据（含 password_hash）"""
        user_dir = PlayerManager._get_user_dir(name)

        # 新格式：文件夹
        if os.path.isdir(user_dir):
            data = {}
            for mod_name, keys in _MODULE_MAP.items():
                path = os.path.join(user_dir, f'{mod_name}.json')
                chunk = _read_json(path)
                if chunk:
                    data.update(chunk)
            # 游戏子文件夹
            games_dir = os.path.join(user_dir, 'games')
            if os.path.isdir(games_dir):
                for gf in os.listdir(games_dir):
                    if gf.endswith('.json'):
                        game_id = gf[:-5]
                        chunk = _read_json(os.path.join(games_dir, gf))
                        if chunk is not None:
                            data[game_id] = chunk
            return data or None

        # 旧格式：单文件
        legacy = PlayerManager._get_legacy_file(name)
        if os.path.exists(legacy):
            return _read_json(legacy)

        return None

    @staticmethod
    def _save_user_file(name, data):
        """将完整 data dict 拆分写入多文件"""
        user_dir = PlayerManager._get_user_dir(name)
        os.makedirs(user_dir, exist_ok=True)

        # 按模块分组
        buckets = {mod: {} for mod in _MODULE_MAP}
        game_data = {}

        for key, value in data.items():
            mod = _KEY_TO_MODULE.get(key)
            if mod:
                buckets[mod][key] = value
            elif key not in _ALL_KNOWN_KEYS:
                game_data[key] = value

        # 写入固定模块
        for mod_name, content in buckets.items():
            if content:
                _write_json(os.path.join(user_dir, f'{mod_name}.json'), content)

        # 写入游戏数据
        if game_data:
            games_dir = os.path.join(user_dir, 'games')
            os.makedirs(games_dir, exist_ok=True)
            for game_id, game_content in game_data.items():
                _write_json(os.path.join(games_dir, f'{game_id}.json'), game_content)

        # 删除旧单文件（迁移完成）
        legacy = PlayerManager._get_legacy_file(name)
        if os.path.exists(legacy):
            os.remove(legacy)

    # ── 公开接口（签名不变）──

    @staticmethod
    def register_player(name, password):
        if PlayerManager.player_exists(name):
            return False
        data = get_default_user_template(
            name=name,
            password_hash=PlayerManager.hash_password(password),
        )
        PlayerManager._save_user_file(name, data)
        return True

    @staticmethod
    def verify_password(name, password):
        data = PlayerManager._load_user_file(name)
        if not data:
            return False
        stored = data.get('password_hash', '')
        if not PlayerManager._verify_hash(stored, password):
            return False
        if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
            data['password_hash'] = PlayerManager.hash_password(password)
            PlayerManager._save_user_file(name, data)
        return True

    @staticmethod
    def load_player_data(name):
        legacy = os.path.exists(PlayerManager._get_legacy_file(name))
        data = PlayerManager._load_user_file(name)
        if not data:
            return None
        try:
            updated_data, changes = ensure_user_schema(data)
            if changes or legacy:
                if changes:
                    print(f"[用户数据更新] {name}: {len(changes)} 个属性已补充")
                if legacy:
                    print(f"[数据迁移] {name}: 单文件 → 多文件")
                PlayerManager._save_user_file(name, updated_data)
            return {k: v for k, v in updated_data.items() if k != 'password_hash'}
        except Exception as e:
            print(f"[错误] 加载用户数据失败 {name}: {e}")
            return None

    @staticmethod
    def save_player_data(name, data):
        old_data = PlayerManager._load_user_file(name)
        if old_data and 'password_hash' in old_data:
            data['password_hash'] = old_data['password_hash']
        PlayerManager._save_user_file(name, data)

    @staticmethod
    def rename_player(old_name, new_name):
        if not PlayerManager.player_exists(old_name) or PlayerManager.player_exists(new_name):
            return False
        data = PlayerManager._load_user_file(old_name)
        if not data:
            return False
        data['name'] = new_name
        PlayerManager._save_user_file(new_name, data)
        # 删除旧目录或旧文件
        old_dir = PlayerManager._get_user_dir(old_name)
        if os.path.isdir(old_dir):
            shutil.rmtree(old_dir)
        old_file = PlayerManager._get_legacy_file(old_name)
        if os.path.exists(old_file):
            os.remove(old_file)
        return True

    @staticmethod
    def change_password(name, new_password):
        data = PlayerManager._load_user_file(name)
        if not data:
            return False
        data['password_hash'] = PlayerManager.hash_password(new_password)
        PlayerManager._save_user_file(name, data)
        return True

    @staticmethod
    def delete_player(name, password=None):
        if password is not None:
            if not PlayerManager.verify_password(name, password):
                return False, '密码错误'
        deleted = False
        user_dir = PlayerManager._get_user_dir(name)
        if os.path.isdir(user_dir):
            shutil.rmtree(user_dir)
            deleted = True
        legacy = PlayerManager._get_legacy_file(name)
        if os.path.exists(legacy):
            os.remove(legacy)
            deleted = True
        if deleted:
            return (True, '账号已删除') if password is not None else True
        return (False, '用户不存在') if password is not None else False

    @staticmethod
    def upgrade_all_users():
        """升级所有用户数据到最新模板，同时迁移旧单文件格式。"""
        total = 0
        updated = 0

        if not os.path.exists(USERS_DIR):
            return 0, 0

        entries = list(os.listdir(USERS_DIR))
        seen = set()

        for entry in entries:
            # 旧格式: {name}.json
            if entry.endswith('.json'):
                name = entry[:-5]
            # 新格式: 文件夹
            elif os.path.isdir(os.path.join(USERS_DIR, entry)):
                name = entry
            else:
                continue

            if name in seen:
                continue
            seen.add(name)
            total += 1

            data = PlayerManager.load_player_data(name)
            if data:
                updated += 1

        return total, updated
