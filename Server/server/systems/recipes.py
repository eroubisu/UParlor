"""合成配方注册表 — 框架级配方存储

配方来自游戏模块 recipes.json，由 register_game() 自动注入。
框架不解读配方内容，只存储并提供查询。

配方格式（约定）:
{
    "recipe_id": {
        "name": "...",
        "inputs": [{"id": "item_id", "count": 1}],
        "outputs": [{"id": "item_id", "count": 1, "quality": 0}],
        "gold_cost": 0
    }
}
"""

from __future__ import annotations

# {game_id: {recipe_id: recipe_data}}
_GAME_RECIPES: dict[str, dict] = {}


def register_game_recipes(game_id: str, recipes: dict) -> None:
    """注册游戏配方集"""
    _GAME_RECIPES[game_id] = recipes


def get_recipes(game_id: str) -> dict:
    """获取某游戏的全部配方"""
    return _GAME_RECIPES.get(game_id, {})


def get_recipe(game_id: str, recipe_id: str) -> dict | None:
    """获取单个配方"""
    return _GAME_RECIPES.get(game_id, {}).get(recipe_id)


def get_all_recipes() -> dict[str, dict]:
    """获取所有已注册配方"""
    return dict(_GAME_RECIPES)
