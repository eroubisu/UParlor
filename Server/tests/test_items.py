"""物品库存操作测试"""

from __future__ import annotations

import pytest

from server.systems.items import (
    inv_add, inv_get, inv_sub, inv_total, parse_item_key,
)


class TestInvGet:
    """inv_get — 读取库存"""

    def test_empty_inventory(self):
        assert inv_get({}, 'sword') == 0

    def test_dict_format(self):
        inv = {'sword': {'0': 3, '1': 2}}
        assert inv_get(inv, 'sword', 0) == 3
        assert inv_get(inv, 'sword', 1) == 2
        assert inv_get(inv, 'sword', 5) == 0

    def test_legacy_int_format(self):
        """兼容旧格式 {item_id: int}"""
        inv = {'sword': 5}
        assert inv_get(inv, 'sword', 0) == 5
        assert inv_get(inv, 'sword', 1) == 0


class TestInvAdd:
    """inv_add — 增加物品"""

    def test_add_to_empty(self):
        inv = {}
        inv_add(inv, 'potion', 0, 3)
        assert inv_get(inv, 'potion', 0) == 3

    def test_add_accumulates(self):
        inv = {'gem': {'0': 2}}
        inv_add(inv, 'gem', 0, 5)
        assert inv_get(inv, 'gem', 0) == 7

    def test_add_different_quality(self):
        inv = {}
        inv_add(inv, 'ring', 0, 1)
        inv_add(inv, 'ring', 3, 2)
        assert inv_get(inv, 'ring', 0) == 1
        assert inv_get(inv, 'ring', 3) == 2

    def test_add_upgrades_legacy_format(self):
        """旧 int 格式自动升级为 dict"""
        inv = {'sword': 5}
        inv_add(inv, 'sword', 0, 2)
        assert inv_get(inv, 'sword', 0) == 7
        assert isinstance(inv['sword'], dict)


class TestInvSub:
    """inv_sub — 扣减物品"""

    def test_sub_reduces(self):
        inv = {'potion': {'0': 5}}
        inv_sub(inv, 'potion', 0, 3)
        assert inv_get(inv, 'potion', 0) == 2

    def test_sub_to_zero_removes(self):
        inv = {'potion': {'0': 1}}
        inv_sub(inv, 'potion', 0, 1)
        assert 'potion' not in inv

    def test_sub_below_zero_clamps(self):
        inv = {'potion': {'0': 2}}
        inv_sub(inv, 'potion', 0, 10)
        assert 'potion' not in inv

    def test_sub_from_empty(self):
        inv = {}
        inv_sub(inv, 'potion', 0, 1)
        # 不应报错，空操作


class TestInvTotal:
    """inv_total — 所有品质总数"""

    def test_total_across_qualities(self):
        inv = {'gem': {'0': 3, '1': 2, '5': 1}}
        assert inv_total(inv, 'gem') == 6

    def test_total_legacy_format(self):
        inv = {'gem': 10}
        assert inv_total(inv, 'gem') == 10

    def test_total_missing_item(self):
        assert inv_total({}, 'gem') == 0


class TestParseItemKey:
    """parse_item_key — 解析 'item:quality'"""

    def test_with_quality(self):
        assert parse_item_key('sword:3') == ('sword', 3)

    def test_without_quality(self):
        assert parse_item_key('sword') == ('sword', 0)

    def test_invalid_quality(self):
        assert parse_item_key('sword:abc') == ('sword:abc', 0)
