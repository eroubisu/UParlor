"""
玩家数据管理
"""

import os
import json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .config import USERS_DIR
from .user_schema import get_default_user_template, ensure_user_schema


class PlayerManager:
    """玩家数据管理 - 注册、登录、存档"""
    
    @staticmethod
    def hash_password(password):
        """密码哈希（werkzeug scrypt）"""
        return generate_password_hash(password)
    
    @staticmethod
    def _verify_hash(stored_hash, password):
        """验证密码，兼容旧版 SHA256 哈希"""
        if stored_hash and len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash):
            import hashlib
            return stored_hash == hashlib.sha256(password.encode()).hexdigest()
        return check_password_hash(stored_hash, password)
    
    @staticmethod
    def _get_user_file(name):
        """获取用户文件路径"""
        return os.path.join(USERS_DIR, f'{name}.json')
    
    @staticmethod
    def player_exists(name):
        """检查玩家是否存在"""
        return os.path.exists(PlayerManager._get_user_file(name))
    
    @staticmethod
    def register_player(name, password):
        """注册新玩家"""
        if PlayerManager.player_exists(name):
            return False
        
        # 创建用户数据（包含密码哈希）
        data = PlayerManager._create_initial_data(name, password)
        PlayerManager._save_user_file(name, data)
        return True
    
    @staticmethod
    def _load_user_file(name):
        """加载用户文件原始数据（含密码哈希）"""
        file_path = PlayerManager._get_user_file(name)
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None

    @staticmethod
    def verify_password(name, password):
        """验证密码（自动升级旧 SHA256 哈希为 werkzeug）"""
        data = PlayerManager._load_user_file(name)
        if not data:
            return False
        stored = data.get('password_hash', '')
        if not PlayerManager._verify_hash(stored, password):
            return False
        # 自动升级旧的 SHA256 哈希
        if len(stored) == 64 and all(c in '0123456789abcdef' for c in stored):
            data['password_hash'] = PlayerManager.hash_password(password)
            PlayerManager._save_user_file(name, data)
        return True
    
    @staticmethod
    def _create_initial_data(name, password):
        """创建初始玩家数据 - 使用标准模板"""
        template = get_default_user_template(
            name=name,
            password_hash=PlayerManager.hash_password(password)
        )
        return template
    
    @staticmethod
    def _save_user_file(name, data):
        """保存用户文件"""
        # 确保目录存在
        os.makedirs(USERS_DIR, exist_ok=True)
        file_path = PlayerManager._get_user_file(name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    @staticmethod
    def load_player_data(name):
        """加载玩家数据（不包含密码哈希）并确保数据完整性"""
        data = PlayerManager._load_user_file(name)
        if not data:
            return None
        try:
            updated_data, changes = ensure_user_schema(data)
            if changes:
                print(f"[用户数据更新] {name}: {len(changes)} 个属性已补充")
                PlayerManager._save_user_file(name, updated_data)
            return {k: v for k, v in updated_data.items() if k != 'password_hash'}
        except Exception as e:
            print(f"[错误] 加载用户数据失败 {name}: {e}")
            return None
    
    @staticmethod
    def save_player_data(name, data):
        """保存玩家数据"""
        old_data = PlayerManager._load_user_file(name)
        if old_data and 'password_hash' in old_data:
            data['password_hash'] = old_data['password_hash']
        PlayerManager._save_user_file(name, data)

    @staticmethod
    def rename_player(old_name, new_name):
        """重命名玩家"""
        old_file = PlayerManager._get_user_file(old_name)
        if not os.path.exists(old_file) or PlayerManager.player_exists(new_name):
            return False
        data = PlayerManager._load_user_file(old_name)
        if not data:
            return False
        data['name'] = new_name
        PlayerManager._save_user_file(new_name, data)
        os.remove(old_file)
        return True
    
    @staticmethod
    def change_password(name, new_password):
        """修改密码"""
        data = PlayerManager._load_user_file(name)
        if not data:
            return False
        data['password_hash'] = PlayerManager.hash_password(new_password)
        PlayerManager._save_user_file(name, data)
        return True

    @staticmethod
    def delete_player(name, password=None):
        """删除玩家账号。提供 password 时验证，否则直接删除。"""
        if password is not None:
            if not PlayerManager.verify_password(name, password):
                return False, '密码错误'
        file_path = PlayerManager._get_user_file(name)
        if os.path.exists(file_path):
            os.remove(file_path)
            return (True, '账号已删除') if password is not None else True
        return (False, '用户不存在') if password is not None else False

    @staticmethod
    def upgrade_all_users():
        """升级所有用户数据到最新模板。Returns: (total, updated)"""
        total = 0
        updated = 0
        
        if not os.path.exists(USERS_DIR):
            return 0, 0
        
        for filename in os.listdir(USERS_DIR):
            if not filename.endswith('.json'):
                continue
            
            name = filename[:-5]  # 去掉 .json
            total += 1
            
            # 加载用户数据（会自动补充缺失属性）
            data = PlayerManager.load_player_data(name)
            if data:
                # load_player_data 已经自动保存了更新后的数据
                updated += 1
        
        return total, updated
