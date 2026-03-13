"""
麻将 - 消息构建器
纯函数模块：将房间状态转换为 Rich Result 协议中的消息列表。

所有函数返回 dict，包含 send_to_players / schedule 等键，
供 command_handler 和 bot_scheduler 组装最终 result。
"""


def build_self_action_prompt(room, pos):
    """构建自摸/立直/暗杠/加杠的操作提示数据"""
    actions = {}
    hand = room.hands[pos]
    if not hand:
        return actions
    drawn_tile = hand[-1] if len(hand) % 3 == 2 else None
    if drawn_tile and room.can_win(hand[:-1], drawn_tile):
        actions['tsumo'] = True
    riichi_tiles = room.can_declare_riichi(pos)
    if riichi_tiles:
        actions['riichi'] = riichi_tiles
    for k in (room.check_self_kong(pos) or []):
        key = 'ankan' if k['type'] == 'concealed' else 'kakan'
        actions.setdefault(key, []).append(k)
    return actions


def build_draw_messages(room, room_id, pos, player_name, drawn_tile):
    """构建摸牌通知消息列表 + 调度任务。

    Returns:
        (messages: list[dict], schedule: list[dict])
        messages 发给该玩家，schedule 是 bot 调度任务。
    """
    msgs = []

    # 文字提示
    text = f"轮到你出牌！\n摸到: [{drawn_tile}]"
    self_actions_text = []
    if room.can_win(room.hands[pos][:-1], drawn_tile):
        self_actions_text.append("可以自摸 /tsumo")
    riichi_tiles = room.can_declare_riichi(pos)
    if riichi_tiles:
        self_actions_text.append("可以立直 /riichi <编号>")
    for k in (room.check_self_kong(pos) or []):
        cmd = 'ankan' if k['type'] == 'concealed' else 'kakan'
        label = '暗杠' if k['type'] == 'concealed' else '加杠'
        self_actions_text.append(f"可{label} [{k['tile']}] /{cmd}")
    if self_actions_text:
        text += "\n" + "\n".join(self_actions_text)

    msgs.append({'type': 'game', 'text': text})
    msgs.append({
        'type': 'hand_update',
        'hand': room.hands[pos], 'drawn': drawn_tile,
        'tenpai_analysis': room.get_tenpai_analysis(pos),
    })
    self_action_data = build_self_action_prompt(room, pos)
    if self_action_data:
        msgs.append({'type': 'self_action_prompt', 'actions': self_action_data})

    # 立直自动摸切调度
    schedule = []
    if room.riichi[pos] and not (drawn_tile and room.can_win(room.hands[pos][:-1], drawn_tile)):
        schedule.append({
            'game_id': 'mahjong', 'action': 'riichi_auto',
            'room_id': room_id, 'player': player_name,
        })

    return msgs, schedule


def build_discard_broadcast(room, room_id, discard_player, tile, next_player,
                            drawn_tile, waiting_action, is_riichi=False,
                            exclude_player=None):
    """构建出牌广播：每个玩家收到个性化消息（含 action_prompt / 摸牌）。

    Returns:
        {'send_to_players': {name: [msg, ...]}, 'schedule': [...]}
    """
    send_to_players = {}
    schedule = []

    action_hint = ""
    if waiting_action and hasattr(room, 'action_players') and room.action_players:
        action_hint = f" [等待操作({len(room.action_players)})]"
    if discard_player:
        prefix = f"{discard_player} 立直！打出" if is_riichi else f"{discard_player} 打出"
        base_msg = f"{prefix} [{tile}]，轮到 {next_player}{action_hint}"
    else:
        base_msg = None

    room_data = room.get_table_data()

    for pos_i in range(len(room.players)):
        pname = room.players[pos_i]
        if not pname or pname == exclude_player:
            continue
        if room.is_bot(pname):
            continue

        msgs = [{'type': 'room_update', 'room_data': room_data}]
        actions = room.check_actions(pos_i, tile) if tile else {}
        if base_msg:
            msgs.append({'type': 'game', 'text': base_msg})

        if pname == next_player:
            if waiting_action:
                if actions:
                    msgs.append({'type': 'action_prompt', 'actions': actions,
                                 'tile': tile, 'from_player': discard_player})
            elif drawn_tile:
                draw_msgs, draw_sched = build_draw_messages(
                    room, room_id, pos_i, pname, drawn_tile)
                msgs.extend(draw_msgs)
                schedule.extend(draw_sched)
        elif actions and any(k in actions for k in ('pong', 'kong', 'win')):
            filtered = {k: v for k, v in actions.items() if k in ('pong', 'kong', 'win')}
            msgs.append({'type': 'action_prompt', 'actions': filtered,
                         'tile': tile, 'from_player': discard_player})

        send_to_players[pname] = msgs

    # Bot 调度
    if next_player and room.is_bot(next_player) and not waiting_action:
        schedule.append({
            'game_id': 'mahjong', 'action': 'bot_play',
            'room_id': room_id, 'player': next_player,
        })
    if waiting_action and hasattr(room, 'action_players') and room.action_players:
        schedule.append({
            'game_id': 'mahjong', 'action': 'bot_pass',
            'room_id': room_id, 'tile': tile, 'from_player': discard_player,
        })

    return {'send_to_players': send_to_players, 'schedule': schedule}


def build_hands_broadcast(room, message, room_data, location=None, exclude_player=None):
    """构建开局/续局手牌广播：每人收到各自手牌。

    Returns:
        {'send_to_players': {name: [msg, ...]}}
    """
    send_to_players = {}
    for pos_i in range(len(room.players)):
        pname = room.players[pos_i]
        if not pname or pname == exclude_player:
            continue
        if room.is_bot(pname):
            continue
        msgs = [{'type': 'room_update', 'message': message, 'room_data': room_data}]
        if location:
            msgs.append({'type': 'location_update', 'location': location})
        msgs.append({
            'type': 'hand_update',
            'hand': room.hands[pos_i],
            'tenpai_analysis': room.get_tenpai_analysis(pos_i),
        })
        send_to_players[pname] = msgs
    return {'send_to_players': send_to_players}


def build_room_broadcast(room, message, room_data, exclude_player=None,
                         update_last=False, embed_message=False, location=None):
    """构建通用房间广播。

    embed_message=True: message 嵌入 room_update JSON 中
    embed_message=False: game 文本 + room_update 分开发

    Returns:
        {'send_to_players': {name: [msg, ...]}}
    """
    send_to_players = {}
    for pos_i in range(len(room.players)):
        pname = room.players[pos_i]
        if not pname or pname == exclude_player:
            continue
        if room.is_bot(pname):
            continue
        msgs = []
        if embed_message:
            msgs.append({'type': 'room_update', 'message': message, 'room_data': room_data})
        else:
            if message:
                msgs.append({'type': 'game', 'text': message, 'update_last': update_last})
            msgs.append({'type': 'room_update', 'room_data': room_data})
        if location:
            msgs.append({'type': 'location_update', 'location': location})
        send_to_players[pname] = msgs
    return {'send_to_players': send_to_players}


def build_win_broadcast(room, win_animation, room_data, exclude_player=None):
    """构建胜利动画广播。

    Returns:
        {'send_to_players': {name: [msg, ...]}}
    """
    send_to_players = {}
    anims = win_animation if isinstance(win_animation, list) else [win_animation]
    for pos_i in range(len(room.players)):
        pname = room.players[pos_i]
        if not pname or pname == exclude_player:
            continue
        if room.is_bot(pname):
            continue
        msgs = []
        for anim in anims:
            msgs.append({'type': 'win_animation', **anim})
        if room_data:
            msgs.append({'type': 'room_update', 'room_data': room_data})
        send_to_players[pname] = msgs
    return {'send_to_players': send_to_players}


def build_ryuukyoku_message(room, ryuukyoku_result,
                            last_discard_player=None, last_tile=None):
    """构建流局文本消息。

    Returns:
        str — 消息文本
    """
    msg_lines = []
    if last_discard_player and last_tile:
        msg_lines.append(f"{last_discard_player} 打出 [{last_tile}]")
    msg_lines.append("荒牌流局！牌山已摸完")

    tenpai_names = [room.players[i] for i in ryuukyoku_result['tenpai']]
    noten_names = [room.players[i] for i in ryuukyoku_result['noten']]
    if tenpai_names:
        msg_lines.append(f"📗 听牌: {', '.join(tenpai_names)}")
    if noten_names:
        msg_lines.append(f"📕 未听: {', '.join(noten_names)}")
    for i in range(4):
        change = ryuukyoku_result['score_changes'][i]
        if change != 0:
            sign = '+' if change > 0 else ''
            msg_lines.append(f"  {room.players[i]}: {sign}{change}")
    if ryuukyoku_result.get('renchan'):
        msg_lines.append(f"🔄 {room.players[room.dealer]} 连庄")
    else:
        msg_lines.append("➡ 轮庄")
    msg_lines += ["", "输入 /next 开始下一局", "输入 /quit 或 /back 离开"]
    return '\n'.join(msg_lines)


def build_ryuukyoku_broadcast(room, ryuukyoku_result,
                              last_discard_player=None, last_tile=None):
    """构建流局广播（含取消 bot timer）。

    Returns:
        {'send_to_players': {name: [msg, ...]}, 'schedule': [...]}
    """
    msg = build_ryuukyoku_message(room, ryuukyoku_result,
                                  last_discard_player, last_tile)
    room_data = room.get_table_data()
    broadcast = build_room_broadcast(room, msg, room_data)
    broadcast['schedule'] = [{'game_id': 'mahjong', 'action': 'cancel_timer',
                              'room_id': room.room_id}]
    return broadcast


def build_after_pass_broadcast(room, room_id, next_player, drawn_tile, room_data):
    """构建全员 pass 后的广播：下家摸牌，其他人只收 room_update。

    Returns:
        {'send_to_players': {name: [msg, ...]}, 'schedule': [...]}
    """
    send_to_players = {}
    schedule = []
    for pos_i in range(len(room.players)):
        pname = room.players[pos_i]
        if not pname:
            continue
        if room.is_bot(pname):
            continue
        msgs = [{'type': 'room_update', 'room_data': room_data}]
        if pname == next_player:
            draw_msgs, draw_sched = build_draw_messages(
                room, room_id, pos_i, pname, drawn_tile)
            msgs.extend(draw_msgs)
            schedule.extend(draw_sched)
        send_to_players[pname] = msgs

    if room.is_bot(next_player):
        schedule.append({
            'game_id': 'mahjong', 'action': 'bot_play',
            'room_id': room_id, 'player': next_player,
        })

    return {'send_to_players': send_to_players, 'schedule': schedule}
