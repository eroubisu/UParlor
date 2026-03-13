"""
JRPG 游戏数据管理
"""

import os
import json
import random

# 数据文件路径
DATA_DIR = os.path.dirname(os.path.abspath(__file__))


class JRPGData:
    """JRPG游戏数据管理 - 加载和管理游戏配置"""
    
    def __init__(self):
        self.config = self.load_config()
    
    def load_config(self):
        """加载游戏配置文件"""
        config_path = os.path.join(DATA_DIR, 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"monsters": [], "items": [], "areas": [], "maps": {}}
    
    def get_monster(self, monster_id):
        """获取怪物数据"""
        for m in self.config['monsters']:
            if m['id'] == monster_id:
                return m.copy()
        return None
    
    def get_area(self, area_id):
        """获取区域数据"""
        for a in self.config['areas']:
            if a['id'] == area_id:
                return a
        return None
    
    def get_map(self, area_id):
        """获取区域地图"""
        maps = self.config.get('maps', {})
        return maps.get(area_id, None)
    
    def get_random_monster_for_area(self, area_id):
        """获取区域内随机怪物"""
        area = self.get_area(area_id)
        if area and area['monsters']:
            monster_id = random.choice(area['monsters'])
            return self.get_monster(monster_id)
        return None
    
    def get_item(self, item_id):
        """获取道具数据"""
        for item in self.config['items']:
            if item['id'] == item_id:
                return item.copy()
        return None
    
    def get_all_areas(self):
        """获取所有区域"""
        return self.config.get('areas', [])
