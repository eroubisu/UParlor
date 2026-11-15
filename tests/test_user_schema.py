"""Legacy user-data schema migration regressions."""

from copy import deepcopy

from server.player.schema import ensure_user_schema, get_default_user_template
from server.systems.titles import TITLE_LIBRARY


def test_legacy_user_fields_migrate_without_losing_identity_or_game_data():
    title_id, title_info = next(iter(TITLE_LIBRARY.items()))
    user_data = {
        'name': 'alice',
        'password_hash': 'hash',
        'created_at': '2024-01-02T03:04:05',
        'gold': 10,
        'rename_cards': 4,
        'title': 'legacy-title',
        'titles': {
            'owned': [title_info['name'], 'custom-title'],
            'displayed': [title_info['name']],
        },
        'games': {
            'uno': {'gold': 7, 'wins': 3},
        },
        'attributes': {'strength': 8},
        'equipment': {'weapon': 'old-sword'},
        'profile_card': {'motto': '保留这句话'},
    }

    upgraded, changes = ensure_user_schema(user_data)

    assert upgraded is user_data
    assert upgraded['name'] == 'alice'
    assert upgraded['password_hash'] == 'hash'
    assert upgraded['created_at'] == '2024-01-02T03:04:05'
    assert upgraded['gold'] == 17
    assert upgraded['inventory']['rename_card'] == 4
    assert upgraded['uno'] == {'wins': 3}
    assert upgraded['titles'] == {
        'owned': [title_id, 'custom-title'],
        'displayed': [title_id],
    }
    assert upgraded['profile_card']['motto'] == '保留这句话'
    assert upgraded['profile_card']['name_color'] == '#ffffff'
    for removed in ('rename_cards', 'title', 'games', 'attributes', 'equipment'):
        assert removed not in upgraded
    assert "迁移: rename_cards -> inventory.rename_card" in changes
    assert "迁移: games.uno.gold -> gold" in changes
    assert "迁移: games.uno -> uno" in changes
    assert f"迁移头衔: '{title_info['name']}' -> '{title_id}'" in changes


def test_legacy_inventory_is_flattened_and_removed_items_are_dropped():
    user_data = get_default_user_template('alice', 'hash')
    user_data['rename_cards'] = 9
    user_data['inventory'] = {
        'rename_card': {'0': 2, '1': 3, 'ignored': 'not-a-count'},
        'custom_item': {'0': 1, 'rare': 2},
        'healing_herb': 4,
    }

    upgraded, changes = ensure_user_schema(user_data)

    assert upgraded['inventory'] == {
        'rename_card': 5,
        'custom_item': 3,
    }
    assert 'rename_cards' not in upgraded
    assert "删除: 旧字段 rename_cards" in changes
    assert "迁移库存: rename_card 品质格式 -> 简单计数" in changes
    assert "迁移库存: custom_item 品质格式 -> 简单计数" in changes
    assert "删除: 已移除物品 healing_herb" in changes


def test_schema_upgrade_is_idempotent_after_first_persist():
    user_data = {
        'name': 'alice',
        'password_hash': 'hash',
        'created_at': '2024-01-02T03:04:05',
        'profile_card': {'motto': 'hello'},
    }

    upgraded, first_changes = ensure_user_schema(user_data)
    first_snapshot = deepcopy(upgraded)
    upgraded_again, second_changes = ensure_user_schema(upgraded)

    assert first_changes
    assert upgraded_again == first_snapshot
    assert second_changes == []


def test_empty_user_data_is_not_upgraded():
    assert ensure_user_schema(None) == (None, [])
    assert ensure_user_schema({}) == (None, [])
