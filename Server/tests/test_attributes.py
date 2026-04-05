"""属性系统测试"""

from __future__ import annotations

import pytest

from server.systems.attributes import (
    get_base_stats, get_total_stats, get_max_hp, get_max_mp,
    heal_hp, damage_hp, heal_mp, ensure_attributes,
)


class TestBaseStats:
    """基础属性计算"""

    def test_level_1(self):
        stats = get_base_stats(1)
        assert stats['hp'] == 100
        assert stats['mp'] == 50
        assert stats['attack'] == 10

    def test_level_10(self):
        stats = get_base_stats(10)
        assert stats['hp'] == 100 + 10 * 9  # base + per_level * (10-1)
        assert stats['mp'] == 50 + 5 * 9

    def test_all_stats_present(self):
        stats = get_base_stats(1)
        expected = {'hp', 'mp', 'attack', 'defense', 'magic_attack',
                    'magic_defense', 'agility', 'luck'}
        assert set(stats.keys()) == expected

    def test_stats_grow_with_level(self):
        s1 = get_base_stats(1)
        s50 = get_base_stats(50)
        assert s50['hp'] > s1['hp']
        assert s50['mp'] > s1['mp']


class TestTotalStats:
    """总属性（含装备加成）"""

    def test_no_equipment(self):
        data = {'level': 5}
        total = get_total_stats(data)
        base = get_base_stats(5)
        assert total == base

    def test_default_level(self):
        data = {}
        total = get_total_stats(data)
        assert total == get_base_stats(1)


class TestHpOperations:
    """HP 增减操作"""

    def test_damage_reduces_hp(self):
        data = {'level': 1, 'attributes': {'current_hp': 80}}
        actual = damage_hp(data, 30)
        assert actual == 30
        assert data['attributes']['current_hp'] == 50

    def test_damage_clamps_at_zero(self):
        data = {'level': 1, 'attributes': {'current_hp': 10}}
        actual = damage_hp(data, 100)
        assert actual == 10
        assert data['attributes']['current_hp'] == 0

    def test_heal_recovers_hp(self):
        data = {'level': 1, 'attributes': {'current_hp': 50}}
        actual = heal_hp(data, 20)
        assert actual == 20
        assert data['attributes']['current_hp'] == 70

    def test_heal_capped_at_max(self):
        data = {'level': 1, 'attributes': {'current_hp': 95}}
        actual = heal_hp(data, 100)
        assert actual == 5  # max_hp(lv1) = 100
        assert data['attributes']['current_hp'] == 100


class TestMpOperations:
    """MP 恢复操作"""

    def test_heal_mp(self):
        data = {'level': 1, 'attributes': {'current_mp': 20}}
        actual = heal_mp(data, 10)
        assert actual == 10
        assert data['attributes']['current_mp'] == 30

    def test_heal_mp_capped(self):
        data = {'level': 1, 'attributes': {'current_mp': 48}}
        actual = heal_mp(data, 100)
        assert actual == 2  # max_mp(lv1) = 50


class TestEnsureAttributes:
    """属性初始化"""

    def test_initializes_missing(self):
        data = {'level': 1}
        ensure_attributes(data)
        assert data['attributes']['current_hp'] == 100
        assert data['attributes']['current_mp'] == 50

    def test_preserves_existing(self):
        data = {'level': 1, 'attributes': {'current_hp': 42, 'current_mp': 10}}
        ensure_attributes(data)
        assert data['attributes']['current_hp'] == 42
