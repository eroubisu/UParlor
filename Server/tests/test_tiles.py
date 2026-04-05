"""麻将牌编码转换测试"""

from __future__ import annotations

import pytest

from server.games.mahjong.tiles import (
    hand_to_34, str_to_tile34, tile_suit, tile_to_chinese, tile_to_str,
)


class TestTileToStr:
    """136编码 → 字符串"""

    def test_man(self):
        assert tile_to_str(0) == '1m'    # 1万 (tile_34=0)
        assert tile_to_str(35) == '9m'   # 9万 (tile_34=8)

    def test_pin(self):
        assert tile_to_str(36) == '1p'   # 1筒 (tile_34=9)
        assert tile_to_str(71) == '9p'   # 9筒 (tile_34=17)

    def test_sou(self):
        assert tile_to_str(72) == '1s'   # 1索 (tile_34=18)
        assert tile_to_str(107) == '9s'  # 9索 (tile_34=26)

    def test_honors(self):
        assert tile_to_str(108) == '東'   # 东 (tile_34=27)
        assert tile_to_str(132) == '中'   # 中 (tile_34=33)


class TestTileToChinese:
    """136编码 → 中文名"""

    def test_man(self):
        assert tile_to_chinese(0) == '一萬'
        assert tile_to_chinese(35) == '九萬'

    def test_pin(self):
        assert tile_to_chinese(36) == '一筒'

    def test_sou(self):
        assert tile_to_chinese(72) == '一條'

    def test_honor(self):
        assert tile_to_chinese(108) == '東'
        assert tile_to_chinese(132) == '中'


class TestStrToTile34:
    """字符串 → 34编码"""

    def test_alphanumeric(self):
        assert str_to_tile34('1m') == 0
        assert str_to_tile34('5p') == 13
        assert str_to_tile34('9s') == 26

    def test_chinese(self):
        assert str_to_tile34('一万') == 0
        assert str_to_tile34('一萬') == 0
        assert str_to_tile34('五筒') == 13

    def test_honor_traditional(self):
        assert str_to_tile34('東') == 27
        assert str_to_tile34('中') == 33

    def test_honor_simplified(self):
        assert str_to_tile34('东') == 27
        assert str_to_tile34('发') == 32

    def test_invalid(self):
        assert str_to_tile34('xx') is None
        assert str_to_tile34('0m') is None

    def test_wind_z_format(self):
        assert str_to_tile34('1z') == 27
        assert str_to_tile34('7z') == 33


class TestTileSuit:
    """花色判断"""

    def test_suits(self):
        assert tile_suit('1m') == 'm'
        assert tile_suit('5p') == 'p'
        assert tile_suit('9s') == 's'
        assert tile_suit('東') == 'z'


class TestHandTo34:
    """手牌 → 34编码数组"""

    def test_empty(self):
        arr = hand_to_34([])
        assert arr == [0] * 34
        assert len(arr) == 34

    def test_single_tile(self):
        arr = hand_to_34([0])  # 1万的第1张 (tile_34=0)
        assert arr[0] == 1

    def test_four_same(self):
        arr = hand_to_34([0, 1, 2, 3])  # 4张1万
        assert arr[0] == 4
