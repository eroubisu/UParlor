"""等级系统测试"""

from __future__ import annotations

import pytest

from server.systems.leveling import check_level_up, exp_for_level, max_level


class TestExpTable:
    """经验表查询"""

    def test_level_1_exp(self):
        assert exp_for_level(1) == 1000

    def test_max_level_returns_zero(self):
        assert exp_for_level(max_level()) == 0

    def test_invalid_level_returns_zero(self):
        assert exp_for_level(0) == 0
        assert exp_for_level(-1) == 0

    def test_exp_increases(self):
        """经验需求单调递增"""
        prev = 0
        for lv in range(1, max_level()):
            needed = exp_for_level(lv)
            if needed > 0:
                assert needed >= prev
                prev = needed


class TestCheckLevelUp:
    """升级检查（含级联升级）"""

    def test_no_level_up(self):
        data = {'level': 1, 'exp': 100}
        leveled = check_level_up(data)
        assert leveled == []
        assert data['level'] == 1
        assert data['exp'] == 100

    def test_single_level_up(self):
        data = {'level': 1, 'exp': 1500}
        leveled = check_level_up(data)
        assert leveled == [2]
        assert data['level'] == 2
        assert data['exp'] == 500  # 1500 - 1000

    def test_cascade_level_up(self):
        """经验足够连升多级"""
        data = {'level': 1, 'exp': 1000 + 1325 + 100}
        leveled = check_level_up(data)
        assert leveled == [2, 3]
        assert data['level'] == 3
        assert data['exp'] == 100

    def test_max_level_cap(self):
        """满级不再升级"""
        cap = max_level()
        data = {'level': cap, 'exp': 999999}
        leveled = check_level_up(data)
        assert leveled == []
        assert data['level'] == cap

    def test_exact_exp(self):
        """恰好够升级，经验归零"""
        data = {'level': 1, 'exp': 1000}
        leveled = check_level_up(data)
        assert leveled == [2]
        assert data['exp'] == 0
