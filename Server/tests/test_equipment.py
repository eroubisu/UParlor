"""装备系统测试"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from server.systems.equipment import equip_item, get_equipped_items, unequip_item


def _mock_item(item_id, name='测试物品', equip_slot=None, stats=None):
    """构造模拟物品信息"""
    info = {'name': name}
    if equip_slot:
        info['equip_slot'] = equip_slot
    if stats:
        info['stats'] = stats
    return info


_ITEMS = {
    'iron_sword': _mock_item('iron_sword', '铁剑', 'main_hand', {'attack': 5}),
    'steel_sword': _mock_item('steel_sword', '钢剑', 'main_hand', {'attack': 10}),
    'leather_helm': _mock_item('leather_helm', '皮盔', 'head', {'defense': 3}),
    'potion': _mock_item('potion', '药水'),  # 不可装备
}


@pytest.fixture(autouse=True)
def mock_items():
    with patch('server.systems.equipment.get_item_info', side_effect=_ITEMS.get):
        yield


class TestEquipItem:
    """穿戴装备"""

    def test_equip_from_inventory(self):
        data = {'inventory': {'iron_sword': {'0': 1}}, 'equipment': {}}
        msg = equip_item(data, 'iron_sword')
        assert '铁剑' in msg
        assert data['equipment']['main_hand'] == {'id': 'iron_sword', 'quality': 0}
        assert 'iron_sword' not in data['inventory']

    def test_equip_replaces_existing(self):
        data = {
            'inventory': {'steel_sword': {'0': 1}},
            'equipment': {'main_hand': {'id': 'iron_sword', 'quality': 0}},
        }
        msg = equip_item(data, 'steel_sword')
        assert '钢剑' in msg
        assert '铁剑' in msg  # 旧装备提示
        assert data['equipment']['main_hand']['id'] == 'steel_sword'
        # 旧装备回到背包
        from server.systems.items import inv_get
        assert inv_get(data['inventory'], 'iron_sword', 0) == 1

    def test_equip_unknown_item(self):
        data = {'inventory': {}, 'equipment': {}}
        msg = equip_item(data, 'nonexistent')
        assert '未知' in msg

    def test_equip_non_equipment(self):
        data = {'inventory': {'potion': {'0': 1}}, 'equipment': {}}
        msg = equip_item(data, 'potion')
        assert '无法装备' in msg

    def test_equip_no_stock(self):
        data = {'inventory': {}, 'equipment': {}}
        msg = equip_item(data, 'iron_sword')
        assert '没有' in msg


class TestUnequipItem:
    """卸下装备"""

    def test_unequip(self):
        data = {
            'inventory': {},
            'equipment': {'main_hand': {'id': 'iron_sword', 'quality': 0}},
        }
        msg = unequip_item(data, 'main_hand')
        assert '铁剑' in msg
        assert data['equipment']['main_hand'] is None
        from server.systems.items import inv_get
        assert inv_get(data['inventory'], 'iron_sword', 0) == 1

    def test_unequip_empty_slot(self):
        data = {'inventory': {}, 'equipment': {}}
        msg = unequip_item(data, 'main_hand')
        assert '没有装备' in msg

    def test_unequip_invalid_slot(self):
        data = {'inventory': {}, 'equipment': {}}
        msg = unequip_item(data, 'invalid_slot')
        assert '无效' in msg


class TestGetEquippedItems:
    """装备栏查询"""

    def test_empty_equipment(self):
        data = {}
        equipped = get_equipped_items(data)
        assert all(v is None for v in equipped.values())

    def test_shows_equipped(self):
        data = {'equipment': {'main_hand': {'id': 'iron_sword', 'quality': 0}}}
        equipped = get_equipped_items(data)
        assert equipped['main_hand']['name'] == '铁剑'
        assert equipped['head'] is None
