"""头衔/背包指令（item / mytitle / alltitle / title）"""

from ..player.manager import PlayerManager


def cmd_item(player_data, args):
    """背包指令"""
    from .items import ITEM_LIBRARY, ITEM_SOURCES, inv_total
    inventory = player_data.get('inventory', {})
    gold = player_data.get('gold', 0)
    text = "【背包】\n\n"
    text += f"金币: {gold}\n\n"

    filter_source = args.strip() if args else None
    has_items = False
    for source_id, source_name in ITEM_SOURCES.items():
        if filter_source and filter_source != source_id:
            continue
        items_in_source = []
        for item_id, val in inventory.items():
            total = inv_total(inventory, item_id)
            if total <= 0:
                continue
            item_info = ITEM_LIBRARY.get(item_id, {})
            if item_info.get('source') == source_id:
                items_in_source.append((item_id, total, item_info))
        if items_in_source:
            has_items = True
            text += f"【{source_name}】\n"
            for item_id, count, info in items_in_source:
                text += f"  {info.get('name', item_id)} x{count} - {info.get('desc', '')}\n"
            text += "\n"

    if not has_items:
        text += "暂无物品\n"
    return text


def cmd_mytitle(player_data):
    """查看我的头衔"""
    from .titles import get_title_name, TITLE_LIBRARY
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    owned = titles.get('owned', [])
    displayed = titles.get('displayed', [])

    text = "【我的头衔库】\n\n"
    if displayed:
        displayed_names = ' | '.join(get_title_name(t) for t in displayed)
        text += f"当前显示: {displayed_names}\n\n"
    else:
        text += "当前显示: (无)\n\n"

    text += "已拥有的头衔:\n"
    for i, title_id in enumerate(owned, 1):
        mark = ' [显示中]' if title_id in displayed else ''
        title_info = TITLE_LIBRARY.get(title_id, {})
        name = title_info.get('name', title_id)
        desc = title_info.get('desc', '')
        text += f"  {i}. {name}{mark} - {desc}\n"

    total_titles = len(TITLE_LIBRARY)
    text += f"\n已收集: {len(owned)}/{total_titles}"
    text += "\n\n/settitle <编号> - 切换显示（最多3个）"
    text += "\n/settitle clear - 清除所有显示"
    text += "\n/title - 查看头衔图鉴"
    return text


def cmd_alltitle(player_data, args):
    """查看头衔图鉴"""
    from .titles import TITLE_LIBRARY, TITLE_SOURCES, get_title_name
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    owned = titles.get('owned', [])

    filter_source = args.strip() if args else None
    if filter_source and filter_source not in TITLE_SOURCES:
        text = "可用的筛选类别:\n"
        for src, name in TITLE_SOURCES.items():
            count = sum(1 for t in TITLE_LIBRARY.values() if t.get('source') == src)
            text += f"  title {src}  {name} ({count}个头衔)\n"
        return text

    text = "【头衔图鉴】\n"
    if filter_source:
        text += f"(筛选: {TITLE_SOURCES.get(filter_source, filter_source)})\n"

    current_source = None
    for tid, info in TITLE_LIBRARY.items():
        source = info.get('source', '')
        if filter_source and source != filter_source:
            continue
        if source != current_source:
            if current_source is not None:
                text += "\n"
            current_source = source
            text += f"\n--- {TITLE_SOURCES.get(source, source)} ---\n"
        is_owned = tid in owned
        status = '[已获得]' if is_owned else '[未获得]'
        text += f"  {status} {info.get('name', tid)}"
        text += f"       {info.get('desc', '')}\n"
        if not is_owned:
            text += f"       条件: {info.get('condition', '')}\n"
    return text


def cmd_title(player_name, player_data, args):
    """切换头衔显示"""
    from .titles import TITLE_LIBRARY, get_title_name
    titles = player_data.get('titles', {'owned': ['newcomer'], 'displayed': ['newcomer']})
    owned = titles.get('owned', [])
    displayed = titles.get('displayed', [])

    if not args:
        return "用法: /title <编号> 或 /title clear"

    if args.strip() == 'clear':
        titles['displayed'] = []
        player_data['titles'] = titles
        PlayerManager.save_player_data(player_name, player_data)
        return '已清除所有显示的头衔。'

    try:
        idx = int(args.strip())
    except ValueError:
        return "用法: /title <编号> 或 /title clear"

    if idx < 1 or idx > len(owned):
        return f"无效的编号。你有 {len(owned)} 个头衔。"

    title_id = owned[idx - 1]
    if title_id in displayed:
        displayed.remove(title_id)
        player_data['titles'] = titles
        PlayerManager.save_player_data(player_name, player_data)
        return f"已取消显示头衔: {get_title_name(title_id)}"

    if len(displayed) >= 3:
        return "最多只能显示3个头衔。请先取消其他头衔。"

    displayed.append(title_id)
    player_data['titles'] = titles
    PlayerManager.save_player_data(player_name, player_data)
    title_display = ' | '.join(get_title_name(t) for t in displayed)
    return f"已添加显示头衔: {get_title_name(title_id)}\n当前显示: {title_display}"
