"""棒球：规则判定、阶段接线、飞行窗口与整场对局的回归测试。"""

from __future__ import annotations

import json
import random
import threading
from unittest.mock import Mock

import pytest

from client.games import baseball as _client_baseball  # noqa: F401
from client.config import NF_ONLINE
from client.protocol.handler import get_handler
from client.protocol.renderer import RENDERER_REGISTRY
from client.window_engine.text import cell_width
from server import chat_server as chat_server_module
from server.games.baseball import rules
from server.games.baseball.engine import BaseballEngine
from server.games.baseball.room import (BALLS_FOR_WALK, DEFAULT_INNINGS,
                                        BaseballRoom, STRIKES_FOR_OUT)
from server.games.baseball.state import Flight, Pickup, Runner, Tick
from server.player.manager import PlayerManager, get_default_user_template

# ── 规则 ──


def test_zone_bands_keep_aggressive_pitches_riskier():
    inside = rules.PitchCall('four_seam', 'inside', 'normal')
    rng = random.Random(1)
    take = rules.SwingCall('four_seam', 'take')
    zones = [rules.resolve_pitch(inside, take,
                                 rules.PitcherAttributes(5, 5, 5),
                                 rules.BatterAttributes(5, 5, 5),
                                 rng).zone for _ in range(400)]
    assert zones.count('heart') > zones.count('outside')

    outside = rules.PitchCall('four_seam', 'outside', 'normal')
    rng = random.Random(1)
    zones = [rules.resolve_pitch(outside, take,
                                 rules.PitcherAttributes(5, 5, 5),
                                 rules.BatterAttributes(5, 5, 5),
                                 rng).zone for _ in range(400)]
    assert zones.count('outside') > zones.count('heart')


def test_expected_timing_follows_pitch_type_and_effort():
    assert rules.expected_timing('four_seam', 'normal') == 'early'
    assert rules.expected_timing('slider', 'normal') == 'normal'
    assert rules.expected_timing('changeup', 'normal') == 'late'
    assert rules.expected_timing('four_seam', 'full') == 'early'
    assert rules.expected_timing('changeup', 'full') == 'normal'
    assert rules.expected_timing('splitter', 'full') == 'normal'


def test_every_pitch_type_is_really_different():
    """五种球各有一张自己的性格表：不许出现"换名字但一模一样"的假选择。"""
    assert len(rules.PITCH_TYPES) == 5
    assert len(set(rules.PITCH_TYPES)) == 5
    profiles = [rules.PITCH_PROFILES[key] for key in rules.PITCH_TYPES]
    assert len(set(profiles)) == 5
    assert set(rules.PITCH_TYPE_LABELS) == set(rules.PITCH_TYPES)
    # 名字是中文 + 英文（英文是权威写法，用户 2026-10-15 要求）
    for key in rules.PITCH_TYPES:
        label = rules.PITCH_TYPE_LABELS[key]
        assert label.split(' ', 1)[1][0].isascii(), label
        assert rules.PITCH_TYPE_SHORT[key] in label


def test_pitch_profiles_move_the_numbers_they_claim_to():
    """性格表的每一项都要真的起作用：变化、速度、控球各改一处。"""
    pitcher = rules.PitcherAttributes(control=5, velocity=8, breaking=8)   # 强投手：球种差异才看得出来
    batter = rules.BatterAttributes(5, 5, 5)

    def sample(pitch_type: str, n: int = 4000) -> tuple[float, float]:
        """按这颗球自己的正确时机出手，量进场率与质量——时机因素因此被排除。"""
        rng = random.Random(41)
        hits = quality = 0
        timing = rules.expected_timing(pitch_type, 'normal')
        for _ in range(n):
            call = rules.PitchCall(pitch_type, 'edge', 'normal')
            swing = rules.SwingCall(pitch_type, 'standard', timing)
            result = rules.resolve_pitch(call, swing, pitcher, batter, rng)
            if result.hit is not None:
                hits += 1
                quality += result.hit.quality
        return hits / n, quality / max(1, hits)

    four_seam_rate, four_seam_quality = sample('four_seam')
    splitter_rate, _splitter_quality = sample('splitter')
    changeup_rate, changeup_quality = sample('changeup')

    # 变化越大越难碰到球（飞进来会拐）
    assert splitter_rate < four_seam_rate
    # 球速也是压制力：慢速的变速球被打到更扎实（质量更高）
    assert changeup_quality > four_seam_quality
    # 但变速球也有它的好处：省体力
    assert (rules.PITCH_PROFILES['changeup'].stamina
            < rules.PITCH_PROFILES['four_seam'].stamina)

    def wild_rate(pitch_type: str, n: int = 4000) -> float:
        rng = random.Random(43)
        wild = 0
        for _ in range(n):
            call = rules.PitchCall(pitch_type, 'inside', 'normal')
            result = rules.resolve_pitch(call,
                                         rules.SwingCall('four_seam', 'take'),
                                         pitcher, batter, rng)
            wild += 1 if result.zone == 'outside' else 0
        return wild / n

    # 控球差的球种更容易跑出好球带
    assert wild_rate('splitter') > wild_rate('cutter')
    assert changeup_rate > 0


def test_ground_swing_always_stays_on_the_ground():
    """滚地球打法：质量封顶、球型一定是滚地（没有长打，也没有全垒打）。"""
    pitcher = rules.PitcherAttributes(5, 5, 5)
    batter = rules.BatterAttributes(power=8, contact=8, eye=5)
    rng = random.Random(7)
    kinds = set()
    for _ in range(400):
        call = rules.PitchCall('four_seam', 'edge', 'normal')
        swing = rules.SwingCall('four_seam', 'ground', 'early')
        result = rules.resolve_pitch(call, swing, pitcher, batter, rng)
        if result.hit is not None:
            kinds.add(result.hit.kind)
            assert result.hit.quality <= rules.GROUND_QUALITY_CAP
            assert result.hit.homerun is False
    assert kinds == {'ground'}

    # 收着挥更碰得到球：同一球滚地球的进场率高于大力挥击
    def in_play(swing_kind: str) -> float:
        rng = random.Random(9)
        hits = 0
        for _ in range(4000):
            call = rules.PitchCall('four_seam', 'edge', 'normal')
            swing = rules.SwingCall('four_seam', swing_kind, 'early')
            if rules.resolve_pitch(call, swing, pitcher, batter,
                                   rng).hit is not None:
                hits += 1
        return hits / 4000

    assert in_play('ground') > in_play('power')


def test_a_ground_ball_can_never_be_caught_in_the_air():
    """滚地球是地面球：野手站得再正也只算拦下来（要传垒才算出去，用户 2026-10-15 纠正）。"""
    fielder = rules.FielderAttributes(speed=5, fielding=9, arm=5)
    rng = random.Random(3)
    for _ in range(200):
        hit = rules.HitBall(kind='ground', landing=6, shown=6, ticks=4,
                            tick_ms=560, quality=20)
        result = rules.resolve_fielding(
            hit, 6, False, fielder, 'standard', rng)
        assert result.caught is False
        assert isinstance(result.error, bool)
    # 飞球站得正就是接杀（对照组）
    fly = rules.HitBall(kind='fly', landing=6, shown=6, ticks=4, tick_ms=560,
                        quality=20)
    caught_any = any(rules.resolve_fielding(fly, 6, False, fielder,
                                            'standard',
                                            random.Random(seed)).caught
                     for seed in range(20))
    assert caught_any is True


def test_power_swing_trades_contact_for_quality():
    """强挥是取舍不是白拿：进场明显更少，换来质量与长打。

    曾经这里坏过——接触代价是加法、读准的人接触率已经顶到 CONTACT_MAX，
    代价被上限整口吃掉，强挥变成无条件最优（端到端 3 倍分差）。
    """
    pitcher = rules.PitcherAttributes(5, 5, 5)
    batter = rules.BatterAttributes(5, 5, 5)
    call = rules.PitchCall('four_seam', 'edge', 'normal')

    def sample(swing_kind: str) -> tuple[float, float]:
        rng = random.Random(23)
        in_play = quality = 0
        n = 4000
        for _ in range(n):
            swing = rules.SwingCall('four_seam', swing_kind,
                                    rules.expected_timing('four_seam', 'normal'))
            result = rules.resolve_pitch(call, swing, pitcher, batter, rng)
            if result.hit is not None:
                in_play += 1
                quality += result.hit.quality
        return in_play / n, quality / max(1, in_play)

    contact_rate, contact_quality = sample('standard')
    power_rate, power_quality = sample('power')
    assert power_rate < contact_rate - 0.15, (power_rate, contact_rate)
    assert power_quality > contact_quality
    assert power_rate > 0.4                   # 强挥不是打不到球，只是更难打准


def test_holding_the_runner_cuts_steals_but_helps_the_batter():
    """投手盯跑者：盗垒成功率大幅下降，代价是分心、打者更好打。"""
    assert rules.steal_chance(5, 'yes') < rules.steal_chance(5, 'no') * 0.6
    assert rules.steal_chance(8, 'yes') < rules.steal_chance(8, 'no')

    pitcher = rules.PitcherAttributes(5, 5, 5)
    batter = rules.BatterAttributes(5, 5, 5)

    def in_play(hold: str) -> float:
        rng = random.Random(31)
        hits = 0
        for _ in range(4000):
            call = rules.PitchCall('four_seam', 'edge', 'normal', hold)
            result = rules.resolve_pitch(
                call, rules.SwingCall('four_seam', 'standard', 'early'),
                pitcher, batter, rng)
            hits += 1 if result.kind == 'contact' else 0
        return hits / 4000

    assert in_play('yes') > in_play('no') + 0.03


def test_reading_the_pitcher_beats_guessing():
    """预判球种 + 时机正确时，命中率必须显著高于盲猜。"""
    pitcher = rules.PitcherAttributes(5, 5, 5)
    batter = rules.BatterAttributes(5, 5, 5)
    call = rules.PitchCall('slider', 'edge', 'normal')

    good = rules.SwingCall('slider', 'standard', 'normal')
    bad = rules.SwingCall('four_seam', 'power', 'late')

    def hits(swing, seed) -> int:
        rng = random.Random(seed)
        return sum(
            1 for _ in range(400)
            if rules.resolve_pitch(call, swing, pitcher, batter, rng).kind
            in ('contact', 'foul')
        )

    # 契约是"读准球种 + 对上时机要明显更划算"，不写死绝对差——平衡系数一变，
    # 绝对差就跟着变（接触率上限会压缩高读准的收益），所以按相对比例判。
    good_hits, bad_hits = hits(good, 7), hits(bad, 7)
    assert good_hits > bad_hits * 1.08, (good_hits, bad_hits)
    assert bad_hits > 0                       # 瞎猜也不是打不到，只是差得多


def test_place_runners_scores_and_resolves_collisions():
    outcome = rules.place_runners([1, 2, 3], batter_base=1, advance=1)
    assert outcome.runs == 1
    assert outcome.bases == [1, 2, 3]

    outcome = rules.place_runners([3], batter_base=2, advance=2)
    assert outcome.runs == 1
    assert outcome.bases == [2]


def test_a_jump_widens_the_reach_and_the_guards_help_too():
    fielder = rules.FielderAttributes(5, 5, 5)
    plain = rules.coverage(False, 'fly', fielder, 'standard')
    assert rules.coverage(True, 'fly', fielder, 'standard') == \
        plain + rules.LUNGE_REACH_BONUS
    assert plain == rules.BASE_COVERAGE
    assert rules.coverage(False, 'ground', rules.FielderAttributes(5, 8, 5),
                          'standard') > rules.coverage(
        False, 'ground', fielder, 'standard')
    assert rules.coverage(False, 'fly', fielder, 'deep') > plain


def test_a_jump_is_named_by_the_ball():
    assert rules.jump_label('fly') == rules.jump_label('line') == '跳起'
    assert rules.jump_label('ground') == '飞扑'


def test_a_jump_catches_what_standing_cannot_but_drops_more_often():
    """起跳＝范围大、手更糙：够不着的球靠它接到，够得着的球反而更容易脱手。"""
    fielder = rules.FielderAttributes(5, 5, 5)

    def catch_rate(gap: float, airborne: bool, n: int = 600) -> float:
        rng = random.Random(7)
        hit = rules.HitBall(kind='fly', landing=9, shown=9, ticks=5,
                            quality=40)
        return sum(rules.resolve_fielding(hit, 9 - gap, airborne, fielder,
                                          'standard', rng).caught
                   for _ in range(n)) / n

    assert catch_rate(3, False) < 0.35 < catch_rate(3, True)   # 够不着：靠起跳才接得到
    assert catch_rate(0, True) < catch_rate(0, False) - 0.1    # 站正了：起跳反而更糙


def test_shift_start_moves_the_fielder_along_the_line():
    assert rules.shift_start('left') < rules.shift_start('standard')
    assert rules.shift_start('right') > rules.shift_start('standard')
    assert rules.shift_start('deep') == rules.shift_start('standard')


def test_fielding_catch_and_drop_depends_on_gap():
    hit = rules.HitBall(kind='line', landing=5, shown=5, ticks=4)
    fielder = rules.FielderAttributes(5, 5, 5)
    result = rules.resolve_fielding(
        hit, 5, False, fielder, 'standard', random.Random(3))
    assert result.caught is True

    result = rules.resolve_fielding(
        hit, 12, False, fielder, 'standard', random.Random(3))
    assert result.caught is False


def test_hit_quality_rewards_reading_and_attributes():
    """击球质量靠读准球种/时机堆起来，并受双方属性影响；全垒打是它的上限。"""
    def sample(pitch, swing, batter, pitcher, seed=5, n=300):
        rng = random.Random(seed)
        qualities = []
        homeruns = 0
        for _ in range(n):
            result = rules.resolve_pitch(pitch, swing, pitcher, batter, rng)
            if result.hit is not None:
                qualities.append(result.hit.quality)
                homeruns += 1 if result.hit.homerun else 0
        average = sum(qualities) / len(qualities)
        return average, homeruns

    edge = rules.PitchCall('four_seam', 'edge', 'normal')
    good_swing = rules.SwingCall('four_seam', 'standard',
                                 rules.expected_timing('four_seam', 'normal'))
    bad_swing = rules.SwingCall('slider', 'standard', 'late')
    average_pitcher = rules.PitcherAttributes(5, 5, 5)
    strong = rules.BatterAttributes(power=8, contact=8, eye=5)
    weak = rules.BatterAttributes(power=4, contact=4, eye=5)

    read, home_runs = sample(edge, good_swing, strong, average_pitcher)
    misread, no_home_runs = sample(edge, bad_swing, weak,
                                   rules.PitcherAttributes(8, 8, 8))
    assert read > misread + 25              # 读准 + 属性好，质量明显更高
    assert home_runs > 0 and no_home_runs == 0

    same_swing_weak, _ = sample(edge, good_swing, weak, average_pitcher)
    assert read > same_swing_weak
    fast_ball, _ = sample(edge, good_swing, strong,
                          rules.PitcherAttributes(5, 8, 5))
    slow_ball, _ = sample(edge, good_swing, strong,
                          rules.PitcherAttributes(5, 3, 5))
    assert slow_ball > fast_ball            # 投手球速压制击球质量


def test_hit_quality_makes_the_ball_harder_to_catch():
    """站对位置也可能接不住：击球质量越高，脱手概率越大。"""
    def catch_rate(quality: int, seed: int = 11, n=400) -> float:
        rng = random.Random(seed)
        caught = 0
        for _ in range(n):
            hit = rules.HitBall(kind='fly', landing=9, shown=9, ticks=5,
                                quality=quality)
            result = rules.resolve_fielding(
                hit, 9, False, rules.FielderAttributes(5, 5, 5),
                'standard', rng)
            caught += 1 if result.caught else 0
        return caught / n

    assert catch_rate(30) > catch_rate(70) > catch_rate(100)
    assert catch_rate(100) < 0.85           # 打得结实，摆对位置也常接不住


def test_double_play_when_runner_leaves_early():
    """接杀时提前离垒的人被双杀：打者 + 一个跑者 = 2 出局。"""
    fielder = rules.FielderAttributes(5, 5, 9)
    outs, message = rules.resolve_caught(True, 1, 0, fielder, 3,
                                         random.Random(5))
    assert outs == 2
    assert message == '双杀'

    outs, message = rules.resolve_caught(False, 1, 0, fielder, 3,
                                         random.Random(5))
    assert outs == 1
    assert '接杀' in message


def test_caught_play_never_doubles_with_two_outs():
    """已经两出局：双杀不再生效（只剩一个出局名额）。"""
    outs, _ = rules.resolve_caught(True, 2, 2,
                                   rules.FielderAttributes(5, 5, 9), 5,
                                   random.Random(1))
    assert outs == 1


def test_error_lets_everyone_take_an_extra_base():
    """野手脱手：球滚开，垒上的人各多跑一个垒。"""
    room = _room()
    room.bases = [1]
    hit = rules.HitBall(kind='ground', landing=7, shown=7, ticks=4,
                        tick_ms=100)
    room._begin_flight(hit)
    room.set_run_order('stop')                  # 先叫停：这样「脱手多跑一垒」才看得出来
    room._start_ground(hit, True, room.flight.fielder)
    assert all(runner.bonus for runner in room.runners)
    while room.phase == 'ground':               # 让他们真跑完那两个垒
        room.ground_tick()
    assert room.bases == [2, 3]                 # 一垒跑者上三垒、打者上二垒


# ── 房间阶段机 ──


def _room() -> BaseballRoom:
    room = BaseballRoom('test', ['alice', 'bob'], None)
    room.rng = random.Random(11)
    room.start()
    return room


def test_add_bot_returns_the_bot_name_like_every_other_game():
    room = BaseballRoom('test', ['alice'], None)

    ok, name = room.add_bot()

    assert ok and name == 'Bot_1'
    assert room.is_bot(name) and name in room.players


def test_every_glyph_the_board_draws_is_declared_by_the_renderer():
    from client.games.baseball import diamond

    drawn = {diamond.GUIDE_GLYPH, diamond.SPAN_GLYPH, *diamond.SPAN_CAPS}

    assert drawn <= RENDERER_REGISTRY['baseball'].glyphs


def _through_countdown(room: BaseballRoom) -> None:
    """走完两边交牌后的倒数（3→2→1），再让投手按下「投球」把球投出去。

    倒数完不会自动投（用户 2026-10-16 定）：投手那边亮起「投球」键，他按下才开投。
    """
    for _ in range(rules.COUNTDOWN_SECONDS):
        assert room.countdown > 0
        room.countdown_tick()
    assert room.armed
    assert room.release_pitch(room.fielding_player())


def test_room_requires_two_players_and_runs_three_innings():
    engine = BaseballEngine()
    room = engine.room_class('r1', ['alice'], None)
    assert room.min_players == 2
    assert room.max_players == 2
    assert room.is_full() is False
    assert DEFAULT_INNINGS == 3


def test_homerun_cannot_be_fielded_and_clears_the_bases():
    """全垒打：规则层直接判飞出墙外，阶段机把垒上所有人送回本垒。"""
    room = _room()
    room.bases = [1, 2]
    hit = rules.HitBall(kind='fly', landing=rules.FIELD_CELLS, shown=12,
                        ticks=5, tick_ms=100, homerun=True)
    result = rules.resolve_fielding(
        hit, 6, True, rules.FielderAttributes(5, 5, 5), 'standard',
        room.rng)
    assert result.caught is False and result.homerun is True

    batter = room.batting_player()
    before = room.score[batter]
    room._begin_flight(hit)
    while room.phase == 'flight':
        room.flight_step()
    assert room.phase == 'call'             # 不进入捡球阶段
    assert room.score[batter] == before + 3  # 两个跑者 + 打者
    assert room.bases == []
    assert room.log[-1] == f'全垒打 得分3 {room._score_text()}'   # 一行说完：全垒打、得分、比分
    assert room.line_score[batter][0] == 3


def test_strikeout_and_walk_change_the_count():
    room = _room()
    fielder = room.fielding_player()
    batter = room.batting_player()

    room.set_pitch(fielder, rules.PitchCall('four_seam', 'inside', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    assert room.phase == 'call'
    _through_countdown(room)
    assert room.phase == 'delivery'
    while room.phase == 'delivery':
        room.delivery_step()
    assert room.balls + room.strikes == 1

    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'early'))
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
    assert room.phase in ('call', 'flight', 'ground', 'finished')


def test_flight_shows_a_range_that_narrows_onto_the_landing():
    room = _room()
    hit = rules.HitBall(kind='line', landing=9, shown=8, spread=2.0,
                        ticks=4, tick_ms=100)
    room._begin_flight(hit)
    assert room.phase == 'flight'
    assert room.decision_owner() == ''
    data = room.get_game_data()['flight']
    assert data['span'] == [6.0, 10.0]               # 刚出手最宽：含真落点 9，但不在正中
    assert data['span_next'] == [6.75, 9.75]
    assert 'landing' not in data and 'shown' not in data

    widths = []
    while room.phase == 'flight':
        low, high = room.flight.hit.span_at(room.flight.tick)
        assert low <= hit.landing <= high
        widths.append(high - low)
        room.flight_step()
    assert widths == sorted(widths, reverse=True) and widths[0] > widths[-1]
    assert hit.span_at(hit.ticks) == (9.0, 9.0)       # 球到的那一拍收成一点


def test_a_harder_hit_starts_with_a_wider_range_and_never_pins_the_landing():
    """范围一直含真落点、落点不在正中；打得越结实，刚出手时越看不清。"""
    pitch = rules.PitchCall('four_seam', 'edge', 'normal')
    swing = rules.SwingCall('four_seam', 'standard', 'early')
    pitcher = rules.PitcherAttributes(5, 5, 5)
    batter = rules.BatterAttributes(8, 8, 5)
    rng = random.Random(9)
    hits = [result.hit for result in (
        rules.resolve_pitch(pitch, swing, pitcher, batter, rng)
        for _ in range(600)) if result.hit is not None]
    assert len(hits) > 100
    for hit in hits:
        low, high = hit.span_at(0)
        assert low <= hit.landing <= high
        assert hit.estimate_at(0) != hit.landing
        assert 1 <= hit.estimate_at(0) <= rules.FIELD_CELLS
    assert hits and max(h.quality for h in hits) > min(h.quality
                                                       for h in hits) + 20
    for hit in hits:
        assert hit.spread == pytest.approx(
            rules.SPAN_HALF_MIN + (rules.SPAN_HALF_MAX - rules.SPAN_HALF_MIN)
            * hit.quality / 100)             # 质量越高，刚出手时范围越宽


def test_the_fielder_runs_at_a_steady_speed_by_the_clock():
    room = _room()
    now = [100.0]
    room.clock = lambda: now[0]
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=8, tick_ms=700))
    chaser = room.flight.fielder
    start, speed = chaser.pos, chaser.speed
    assert speed == pytest.approx(
        rules.flight_run_speed(room._fielder().speed, 8, 700))

    assert room.steer_fielder(1) is True
    assert room.steer_fielder(1) is False             # 方向没变：什么都不发生
    now[0] += 2.0
    assert chaser.position(now[0]) == pytest.approx(start + speed * 2)
    now[0] += 1.0
    assert chaser.position(now[0]) == pytest.approx(start + speed * 3)

    assert room.steer_fielder(0) is True              # 站住：就停在此刻的位置
    stopped = chaser.position(now[0])
    now[0] += 5.0
    assert chaser.position(now[0]) == pytest.approx(stopped)

    room.steer_fielder(-1)
    now[0] += 1000
    assert chaser.position(now[0]) == 1.0              # 跑到边线就停


def test_the_fielder_stops_on_the_ball_but_may_run_away_from_it():
    room = _room()
    now = [100.0]
    room.clock = lambda: now[0]
    _ground_play(room, rules.HitBall(kind='line', landing=9, shown=9,
                                     ticks=4, tick_ms=100), cell=4)
    chaser = room.ground.fielder
    assert room.at_ball() is False
    assert room.steer_fielder(1)
    now[0] += 1000                                    # 一直朝球跑：到了球位就自动停住
    assert chaser.position(now[0]) == 9.0
    assert room.at_ball() is True

    room.steer_fielder(0)
    chaser.place(11.0, now[0])                        # 球在他左边，他还朝右跑：不受限制
    room.steer_fielder(1)
    now[0] += 1000
    assert chaser.position(now[0]) == float(rules.FIELD_CELLS)
    assert room.at_ball() is False


def test_a_jump_freezes_the_fielder_until_he_has_recovered():
    room = _room()
    now = [100.0]
    room.clock = lambda: now[0]
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=8, tick_ms=700))
    chaser = room.flight.fielder
    air, rest = rules.FIELDER_AIR_SECONDS, rules.FIELDER_REST_SECONDS
    room.steer_fielder(1)
    now[0] += 1.0
    before = chaser.position(now[0])
    assert room.jump_fielder() is True
    assert chaser.airborne(now[0]) is True
    now[0] += air + rest / 2
    assert chaser.airborne(now[0]) is False            # 落地了，但还在缓冲
    assert room.jump_fielder() is False                # 缓冲里不能再跳
    assert chaser.position(now[0]) == pytest.approx(before)   # 也不能跑
    now[0] += rest / 2 + 1.0                           # 缓冲完：按住的方向接着跑
    assert chaser.position(now[0]) == pytest.approx(
        before + chaser.speed * 1.0)
    assert room.jump_fielder() is True


def test_the_jump_only_counts_when_the_ball_arrives_while_he_is_in_the_air():
    def land(jump_at: float, land_at: float) -> str:
        room = _room()
        now = [100.0]
        room.clock = lambda: now[0]
        room._begin_flight(rules.HitBall(kind='fly', landing=6, shown=6,
                                         ticks=2, tick_ms=700, quality=20))
        now[0] = jump_at
        assert room.jump_fielder() is True
        now[0] = land_at
        room._land()
        return '\n'.join(room.log)

    on_time = land(104.0, 104.0 + rules.FIELDER_AIR_SECONDS / 2)
    assert '跳起恰好' in on_time
    early = land(104.0, 104.0 + rules.FIELDER_AIR_SECONDS + 0.5)
    assert '跳起过早' in early
    assert '跳起' not in _jump_free_landing()


def _jump_free_landing() -> str:
    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=6, shown=6,
                                     ticks=2, tick_ms=700))
    room._land()
    return '\n'.join(room.log)


def test_a_ground_ball_jump_is_called_a_dive():
    room = _room()
    now = [100.0]
    room.clock = lambda: now[0]
    room._begin_flight(rules.HitBall(kind='ground', landing=6, shown=6,
                                     ticks=2, tick_ms=700))
    room.jump_fielder()
    now[0] += 0.3
    room._land()
    assert '飞扑恰好' in '\n'.join(room.log)


def test_the_jump_only_works_while_the_ball_is_flying():
    room = _room()
    assert room.jump_fielder() is False                # 还没击球
    room._begin_flight(rules.HitBall(kind='line', landing=9, shown=9,
                                     ticks=4, tick_ms=100))
    room._land()
    assert room.jump_fielder() is False                # 已经落地 / 接杀


def test_flight_keys_return_silent_result_not_unknown_command():
    engine = BaseballEngine()
    room = _room()
    engine._rooms[room.room_id] = room
    engine._player_room[room.fielding_player()] = room.room_id
    engine._player_room[room.batting_player()] = room.room_id
    result = engine.handle_command(
        None, room.fielding_player(), {}, 'field', 'left')
    assert result == {'action': 'baseball_input'}
    result = engine.handle_command(
        None, room.batting_player(), {}, 'run', 'go')
    assert result == {'action': 'baseball_input'}


def test_game_ends_after_three_innings_and_picks_a_winner():
    room = _room()
    room.innings = DEFAULT_INNINGS
    room.half = 'bottom'
    room.score[room.sides['away']] = 3
    room.score[room.sides['home']] = 1
    room._change_half()
    assert room.state == 'finished'
    assert room.winner == room.sides['away']


def _last_inning(half: str, away: int, home: int) -> BaseballRoom:
    room = _room()
    room.innings = DEFAULT_INNINGS
    room.half = half
    room.score[room.sides['away']] = away
    room.score[room.sides['home']] = home
    return room


def test_the_last_bottom_half_is_skipped_when_home_already_leads():
    """标准终局：主队在末局上半结束时已经领先，下半局不再进行，直接结束并说明原因。"""
    room = _last_inning('top', away=1, home=2)
    room._change_half()
    assert room.state == 'finished'
    assert room.winner == room.sides['home']
    assert any('不打下半局' in line for line in room.log)


def test_the_last_bottom_half_is_played_unless_home_is_ahead():
    for away, home in ((2, 2), (3, 2)):          # 平手或落后：主队还要打
        room = _last_inning('top', away, home)
        room._change_half()
        assert room.state == 'playing'
        assert room.half == 'bottom'
    early = _room()                              # 不是末局：谁领先都照常打
    early.innings = DEFAULT_INNINGS - 1
    early.score[early.sides['home']] = 5
    early._change_half()
    assert early.state == 'playing' and early.half == 'bottom'


def test_a_walk_off_ends_the_game_the_moment_home_takes_the_lead():
    """末局下半主队一取得领先就结束（再见分），不必打满三个出局。"""
    room = _last_inning('bottom', away=1, home=1)
    room.outs = 0
    room.score[room.sides['home']] += 1
    room._after_play()
    assert room.state == 'finished'
    assert room.winner == room.sides['home']
    assert any('提前结束' in line for line in room.log)

    behind = _last_inning('bottom', away=2, home=1)   # 还没反超：继续打
    behind.outs = 0
    behind._after_play()
    assert behind.state == 'playing' and behind.phase == 'call'


def test_a_tie_after_the_last_inning_stays_a_draw():
    room = _last_inning('bottom', away=2, home=2)
    room._change_half()
    assert room.state == 'finished'
    assert room.winner == ''
    assert any('平手' in line for line in room.log)


def _engine_with_room() -> tuple[BaseballEngine, BaseballRoom]:
    engine = BaseballEngine()
    room = _room()
    engine._rooms[room.room_id] = room
    for player in room.players:
        engine._player_room[player] = room.room_id
    return engine, room


def _menu(result: dict) -> dict:
    """取回复里的选择菜单（send_to_caller 末条）。"""
    menu = result['send_to_caller'][-1]
    assert menu['type'] == 'select_menu'
    return menu


def test_step_commands_take_the_pitcher_and_batter_through_every_option():
    """服务端只认完整指令；菜单的层层展开由客户端负责。"""
    engine, room = _engine_with_room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    lobby = Mock()

    engine.handle_command(lobby, pitcher, {}, 'shift', 'left')
    assert room.shift[pitcher] == 'left'
    assert room.phase == 'call'          # 布阵是设置项，不推进阶段

    engine.handle_command(lobby, pitcher, {}, 'pitch',
                          'splitter outside full yes')
    assert room.phase == 'call'          # 只有一边交牌：还在出牌阶段
    assert pitcher in room.pending

    engine.handle_command(lobby, batter, {}, 'swing', 'four_seam power hold')
    assert room.countdown == rules.COUNTDOWN_SECONDS   # 两边都交了：开始倒数
    assert room.phase == 'call'

    # 参数不全或不合法：一律回提示，不改任何状态
    for name, args in (('shift', ''), ('pitch', 'four_seam'),
                       ('pitch', 'four_seam edge normal maybe'),
                       ('swing', 'four_seam'),
                       ('swing', 'four_seam power early')):
        result = engine.handle_command(lobby, batter, {}, name, args)
        text = str(result)
        assert '不完整' in text or '请选择' in text, (name, text)


def test_delivery_animation_reveals_the_result_only_at_the_end():
    """投打动画：投球段 → 挥棒段，最后一帧才揭晓结果。"""
    room = _room()
    fielder = room.fielding_player()
    batter = room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    before = room.phase
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    assert before == 'call'                     # 只有一边交牌时不开始
    assert room.phase == 'call'
    assert room.countdown == rules.COUNTDOWN_SECONDS   # 两边都交了：先倒数
    _through_countdown(room)
    assert room.phase == 'delivery'
    assert room.delivery.frame == 0
    assert room.delivery.frames == rules.PITCH_ANIM_FRAMES

    room.delivery_step()
    assert room.phase == 'delivery'
    # 打者还没按击球：这一球先不判（等他按，或者球到了自动放过去）
    assert room.exchange.result is None
    room.swing_now(batter, 3)                   # 按下击球（早按＝提前）
    assert room.exchange.result is not None

    for _ in range(rules.delivery_frames()):
        if room.phase == 'delivery':
            room.delivery_step()
    assert room.phase in ('call', 'flight', 'ground', 'finished')
    assert room.exchange is None


def test_delivery_has_a_pitch_stage_and_a_swing_stage():
    """两段动画：投球段帧数多、挥棒段帧数少，段与段之间帧号归零。"""
    room = _room()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    seen = [room.delivery.stage]
    for _ in range(rules.delivery_frames() + 2):
        if room.phase != 'delivery':
            break
        room.delivery_step()
        if room.delivery:
            seen.append(room.delivery.stage)
    assert seen[0] == 'pitch'
    assert 'swing' in seen
    assert seen.index('swing') == rules.PITCH_ANIM_FRAMES


def test_landed_ball_needs_the_fielder_to_pick_it_up_and_throw():
    """落地不直接判安打：要跑到落点捡球，再选垒包传球（带距离）。"""
    room = _room()
    hit = rules.HitBall(kind='line', landing=9, shown=9, ticks=4, tick_ms=100)
    room._begin_flight(hit)
    room._land()
    if room.phase != 'ground':          # 接杀就换个落点重的球再来
        room.phase = 'call'
        room._begin_flight(rules.HitBall(
            kind='ground', landing=2, shown=2, ticks=4, tick_ms=100))
        room._land()
    assert room.phase == 'ground', room.phase
    assert room.runners, '落地后应该有人跑垒'
    assert room.get_game_data()['ground']['ball'] == room.ground.ball

    options = room.throw_options()
    assert [item.base for item in options] == list(rules.BASE_ORDER)
    assert all(item.distance > 0 for item in options)
    assert [item.distance for item in options] != sorted(
        item.distance for item in options) or len(options) == 1

    # 没跑到球的位置不能传
    room.ground.cell = 1
    assert room.at_ball() is False
    assert room.start_throw('一垒') is False

    # 跑到球上：传球按距离消耗 tick，传球途中跑者继续推进
    room.ground.cell = room.ground.ball
    assert room.at_ball() is True
    assert room.start_throw('一垒') is True
    assert room.phase == 'throw'
    assert room.throw.ticks >= 1
    guard = 0
    while room.phase == 'throw' and guard < 30:
        room.throw_tick()
        guard += 1
    assert room.phase != 'throw'


def _ground_play(room: BaseballRoom, hit: rules.HitBall,
                 cell: int = 7) -> None:
    """测试用：先按击球生成跑者，再直接进捡球阶段。"""
    room._begin_flight(hit)
    room.flight.fielder.place(float(cell), room.clock())
    room._start_ground(hit, False, room.flight.fielder)


def test_throw_can_beat_a_runner_or_fail_late():
    """传球先到 → 封杀；跑者已经站稳 → 安全。"""
    hit = rules.HitBall(kind='ground', landing=2, shown=2, ticks=4,
                        tick_ms=100)

    room = _room()
    room.bases = [1]
    _ground_play(room, hit, 2)
    room.ground.cell = room.ground.ball
    for runner in room.runners:
        runner.need = 99                      # 还在跑，没到垒
    assert room.start_throw('二垒') is True
    while room.phase == 'throw':
        room.throw_tick()
    assert room.outs == 1                     # 球先到 → 封杀离垒的跑者

    room2 = _room()
    room2.bases = [1]
    _ground_play(room2, hit, 2)
    room2.ground.cell = room2.ground.ball
    for runner in room2.runners:
        runner.settled = True                 # 已经稳稳站在下一个垒上
    assert room2.start_throw('二垒') is True
    while room2.phase == 'throw':
        room2.throw_tick()
    assert room2.outs == 0                    # 球到晚了 → 安全


def test_hold_ball_ends_the_play_without_an_out():
    """击出后默认全体前进：守方控球时，二垒跑者也已经在往三垒跑；叫了「停止」才留在原垒。"""
    room = _room()
    room.bases = [2]
    hit = rules.HitBall(kind='fly', landing=11, shown=11, ticks=5,
                        tick_ms=100)
    _ground_play(room, hit, 11)
    assert room.hold_ball() is True
    assert room.phase == 'call'
    assert room.outs == 0
    assert room.bases == [1, 3]                 # 默认前进：二垒跑者上了三垒，打者上一垒

    # 立刻叫「停止」：二垒没人挤他，他还没离开垒就留在原地
    room = _room()
    room.bases = [2]
    room._begin_flight(hit)
    assert room.set_run_order('stop') is True
    room._start_ground(hit, False, room.flight.fielder)
    room.hold_ball()
    assert room.bases == [1, 2]


def test_the_go_order_keeps_runners_running_until_you_stop_them():
    room = _room()
    room._begin_flight(rules.HitBall(kind='line', landing=8, shown=8,
                                     ticks=4, tick_ms=560))
    assert room.set_run_order('go') is True
    runner = room.runners[-1]

    for _ in range(runner.need):
        room._advance_runners()
    assert (runner.at, runner.to, runner.settled) == (1, 2, False)   # 不停就一直跑
    for _ in range(runner.need):
        room._advance_runners()
    assert (runner.at, runner.to, runner.settled) == (2, 3, False)

    room._advance_runners()                                      # 已经离开二垒一拍：这时叫停
    assert room.set_run_order('stop') is True                    # 半路停不下来：跑到下一个垒再站住
    for _ in range(runner.need - 1):
        room._advance_runners()
    assert (runner.at, runner.settled) == (3, True)
    assert room.set_run_order('go') is True                      # 站着的人也能再起跑
    assert runner.settled is False and runner.to == rules.HOME


def test_everyone_goes_by_default_after_the_hit_and_stop_keeps_the_ones_still_on_base():
    room = _room()
    room.bases = [1, 3]
    room._begin_flight(rules.HitBall(kind='line', landing=8, shown=8,
                                     ticks=4, tick_ms=560))
    assert room.order == 'go' == rules.DEFAULT_RUN_ORDER         # 击出后默认全体前进
    assert not any(r.settled for r in room.runners)              # 站着的三垒跑者也起跑了
    assert room.get_game_data()['run_order'] == 'go'

    assert room.set_run_order('stop') is True                    # 还没离垒：叫停就留在原地
    held = next(r for r in room.runners if r.origin == 3)
    assert held.settled and (held.at, held.to) == (3, 3)
    forced = [r for r in room.runners if r.forced]
    assert len(forced) == 2                                      # 打者与被挤着的一垒跑者照跑
    for _ in range(forced[0].need):
        room._advance_runners()
    assert all(r.settled and r.at == r.origin + 1 for r in forced)

    again = _room()                                              # 已经跑出去的人：半路停不下来
    again.bases = [3]
    again._begin_flight(rules.HitBall(kind='line', landing=8, shown=8,
                                      ticks=4, tick_ms=560))
    again._advance_runners()
    runner = next(r for r in again.runners if not r.batter)
    again.set_run_order('stop')
    assert runner.settled is False and runner.to == rules.HOME   # 来不及了：跑到下一个垒才停


def test_a_runner_halfway_can_turn_back_and_takes_as_long_as_he_has_run():
    room = _room()
    room.bases = [2]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    runner = next(r for r in room.runners if not r.batter)
    assert room.set_run_order('go') is True                     # 二垒跑者起跑去三垒
    assert (runner.at, runner.to, runner.settled) == (2, 3, False)
    for _ in range(3):
        room._advance_runners()
    assert runner.progress == 3

    assert room.set_run_order('back') is True                   # 半路想回去
    assert (runner.at, runner.to, runner.back) == (3, 2, True)
    assert runner.progress == runner.need - 3                   # 跑过 3 拍，回来也要 3 拍
    for _ in range(2):
        room._advance_runners()
    assert runner.settled is False
    room._advance_runners()
    assert (runner.at, runner.settled, runner.back) == (2, True, False)

    room.set_run_order('go')                                    # 回来之后可以再次起跑
    assert (runner.at, runner.to, runner.settled) == (2, 3, False)


def test_turning_back_again_turns_him_forward_without_losing_ground():
    room = _room()
    room.bases = [2]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    runner = next(r for r in room.runners if not r.batter)
    room.set_run_order('go')
    for _ in range(3):
        room._advance_runners()
    room.set_run_order('back')
    room._advance_runners()                                     # 往回跑了 1 拍
    assert runner.progress == runner.need - 2
    room.set_run_order('go')                                    # 又改主意：调头往前
    assert (runner.at, runner.to, runner.back) == (2, 3, False)
    assert runner.progress == 2                                  # 离二垒的距离连续，不瞬移
    room.set_run_order('back')
    room.set_run_order('back')                                  # 重复的撤回不会再翻面
    assert runner.back is True and (runner.at, runner.to) == (3, 2)


def test_forced_runners_and_the_batter_cannot_turn_back_on_their_first_leg():
    room = _room()
    room.bases = [1]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    room._advance_runners()
    before = [(r.at, r.to, r.progress) for r in room.runners]
    assert room.set_run_order('back') is True
    assert [(r.at, r.to, r.progress) for r in room.runners] == before
    assert not any(r.back for r in room.runners)               # 被挤着必须前进：撤回等于停止

    room.set_run_order('go')                                    # 跑过第一个垒、继续往二垒的人可以回一垒
    for _ in range(room.runners[0].need):
        room._advance_runners()
    batter = next(r for r in room.runners if r.batter)
    assert (batter.at, batter.to) == (1, 2)
    room._advance_runners()
    room.set_run_order('back')
    assert batter.back and (batter.at, batter.to) == (2, 1)


def test_a_runner_who_has_not_left_the_base_simply_stays_when_told_to_go_back():
    room = _room()
    room.bases = [2]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    runner = next(r for r in room.runners if not r.batter)
    room.set_run_order('go')
    room.set_run_order('back')                                  # 刚起跑就叫回：还在垒上
    assert (runner.at, runner.to, runner.settled, runner.back) == (2, 2, True, False)


def test_a_throw_to_the_base_he_is_returning_to_is_a_tag_out_not_a_force_out():
    room = _room()
    room.bases = [2]
    _ground_play(room, rules.HitBall(kind='line', landing=8, shown=8,
                                     ticks=4, tick_ms=100), 8)
    runner = next(r for r in room.runners if not r.batter)
    room.set_run_order('go')
    for _ in range(3):
        room._advance_runners()
    room.set_run_order('back')
    room.ground.cell = room.ground.ball
    assert room.start_throw('二垒') is True
    while room.phase == 'throw':
        room.throw_tick()
        if runner.out:
            break
    assert runner.out is True                                   # 他还没回到二垒，球先到了
    assert any('触杀' in line for line in room.log)
    assert not any('封杀' in line for line in room.log)


def test_end_play_reports_only_what_has_not_been_said_yet():
    room = _room()
    room.bases = [1, 3]
    room._begin_flight(rules.HitBall(kind='line', landing=8, shown=8,
                                     ticks=4, tick_ms=560))
    room.set_run_order('stop')                  # 三垒的人还没离垒：留在原地，不用再提

    room._end_play('守方控球')

    assert room.log == ['守方控球 一垒跑者上二垒 打者上一垒']
    assert room.bases == [1, 2, 3]


def test_end_play_does_not_repeat_the_outs_the_out_line_already_gave():
    room = _room()
    room.bases = [1]
    _ground_play(room, rules.HitBall(kind='ground', landing=8, shown=8,
                                     ticks=4, tick_ms=560), 8)
    for runner in room.runners:
        runner.need = 99
    room.ground.cell = room.ground.ball
    room.start_throw('二垒')
    room._drain()
    while room.phase == 'throw':
        room.throw_tick()
    line = room.log[0]
    assert line.startswith('封杀 二垒 一垒跑者 1出局')   # 出局只在这一行里说一次
    assert '一垒跑者出局' not in line and '封杀出局' not in line


def test_walk_only_reports_the_runners_who_were_pushed():
    room = _room()
    room.bases = [1, 3]
    room._walk()
    assert room.log == ['一垒跑者上二垒']             # 打者上一垒是「保送」的题中之意，三垒的人没动
    assert room.bases == [1, 2, 3]

    empty = _room()
    empty._walk()
    assert empty.log == [] and empty.bases == [1]    # 空垒保送：击球那一行已经说了「保送」

    loaded = _room()
    loaded.bases = [1, 2, 3]
    batter = loaded.batting_player()
    loaded._walk()
    assert loaded.log == [f'一垒跑者上二垒 二垒跑者上三垒 三垒跑者得分 '
                          f'{loaded._score_text()}']
    assert loaded.score[batter] == 1
    assert loaded.bases == [1, 2, 3]



def test_flight_speed_and_origin_match_the_slow_ball_contract():
    """一格一拍：跨几格就飞几拍，每格时长固定，一格半秒以上才看得清。"""
    for kind, spec in rules.BALL_KINDS.items():
        assert spec['cell_ms'] >= 500, (kind, spec['cell_ms'])
        low, high = spec['cells']
        for landing in range(low, high + 1):
            ticks, tick_ms = rules.flight_steps(kind, landing)
            assert ticks == max(1, landing - rules.FIELD_START)  # 一格一拍
            assert tick_ms == spec['cell_ms']                   # 每格一样久
            assert tick_ms >= 500                               # 一格看得清

    room = _room()
    room.set_shift(room.fielding_player(), 'standard')
    hit = rules.HitBall(kind='line', landing=10, shown=10, ticks=9,
                        tick_ms=600)
    room._begin_flight(hit)
    assert room.flight.ball == rules.FIELD_START == 1
    positions = []
    while room.phase == 'flight':
        room.flight_step()
        positions.append(room.flight.ball if room.flight else hit.landing)
    assert positions[0] == rules.FIELD_START + 1     # 一拍正好一格
    assert positions == list(range(2, hit.landing + 1))
    assert positions[-1] == hit.landing              # 最后一拍抵达落点
    assert len(positions) == hit.ticks

    assert rules.ball_position(hit, 0) == 1
    assert rules.ball_position(hit, hit.ticks) == hit.landing
    assert rules.ball_position(hit, 3) == rules.FIELD_START + 3


def test_fielder_runs_the_whole_flight_at_a_speed_that_ignores_the_ball_length():
    """野手匀速跑完整段飞行：总共 FLIGHT_MOVE_CELLS 格（速度 ≥7 翻倍），球飞得远不会让他更快。"""
    slow = rules.flight_run_speed(5, 9, 600)
    assert slow * 9 * 0.6 == pytest.approx(rules.FLIGHT_MOVE_CELLS)
    assert rules.flight_run_speed(7, 9, 600) == 2 * slow    # 速度 ≥7 翻倍
    assert rules.flight_run_speed(5, 3, 600) > slow          # 飞得近：留给他的时间少，跑得更急
    assert rules.ground_run_speed(7) == 2 * rules.ground_run_speed(5)

    room = _room()
    now = [100.0]
    room.clock = lambda: now[0]
    for player in room.players:
        room.attributes[player].fielder.speed = 5
    hit = rules.HitBall(kind='line', landing=10, shown=10, ticks=9,
                        tick_ms=600)
    room._begin_flight(hit)
    chaser = room.flight.fielder
    start = chaser.pos
    room.steer_fielder(1)
    now[0] += hit.ticks * hit.tick_ms / 1000       # 一整段飞行一直追
    assert chaser.position(now[0]) - start == pytest.approx(
        rules.FLIGHT_MOVE_CELLS)


def test_only_room_operations_stay_in_the_bottom_right_panel():
    """玩法动作走棋盘下方的操作区，右下角只留房间级操作。"""
    engine, room = _engine_with_room()
    pitcher = room.fielding_player()

    def names() -> list[str]:
        commands = engine.get_commands(None, 'playing', pitcher, {})
        return [item['name'] for item in commands]

    room.phase = 'call'
    assert names() == ['forfeit']
    room.phase = 'call'
    assert names() == ['forfeit']
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=5, tick_ms=380))
    assert names() == ['forfeit']


def test_next_tick_follows_the_active_timed_phase():
    """动画/飞行/捡球/传球都由 tick 推进，对局结束则不再排 tick。"""
    engine, room = _engine_with_room()
    pitcher, batter = room.fielding_player(), room.batting_player()

    assert room.next_tick() is None               # 出牌阶段没有 tick
    assert engine._tick_tasks(room) == []

    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
    assert room.phase == 'call'
    assert room.next_tick() == Tick('countdown', rules.COUNTDOWN_TICK_MS)
    assert engine._tick_tasks(room)[0]['action'] == 'tick'
    for _ in range(rules.COUNTDOWN_SECONDS):
        room.countdown_tick()
    assert room.armed and room.next_tick() is None   # 等投手按「投球」，没有计时
    assert room.release_pitch(pitcher)
    assert room.next_tick() == Tick('delivery', rules.ANIM_FRAME_MS)

    while room.phase == 'delivery':
        room.delivery_step()
    if room.phase == 'flight':
        assert room.next_tick() == Tick('flight', room.flight.hit.tick_ms)
    else:
        assert room.next_tick() is None

    _ground_play(room, rules.HitBall(kind='fly', landing=10, shown=10,
                                       ticks=5, tick_ms=100), 6)
    assert room.next_tick() == Tick('ground', rules.TICK_MS)

    room.ground.cell = room.ground.ball
    room.start_throw('二垒')
    assert room.next_tick() == Tick('throw', rules.TICK_MS)

    room.state = 'finished'
    assert room.next_tick() is None


def test_scheduler_keeps_one_tick_and_rejects_a_stale_phase_timer(monkeypatch):
    """同一阶段只保留一条计时；阶段切换后旧 Timer 不能推进新阶段。"""
    from server.games.baseball.engine import BaseballScheduler

    engine, room = _engine_with_room()
    hit = rules.HitBall(kind='ground', landing=4, shown=4,
                        ticks=3, tick_ms=100)
    _ground_play(room, hit, 4)

    class _Lobby:
        def __init__(self):
            self._lock = threading.RLock()
            self.game_engines = {'baseball': engine}
            self.online_players = {}

    class _Server:
        def __init__(self):
            self.lobby_engine = _Lobby()
            self.messages = []
            self.results = []

        def send_to_player(self, player, message):
            self.messages.append((player, message))

        def dispatch_game_result(self, result):
            self.results.append(result)

    timers = []

    class _Timer:
        def __init__(self, delay, callback, args=(), kwargs=None):
            self.delay = delay
            self.callback = callback
            self.args = args
            self.kwargs = kwargs or {}
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(threading, 'Timer', _Timer)
    scheduler = BaseballScheduler(_Server())

    ground_task = engine._tick_tasks(room)[0]
    scheduler.handle_schedule(ground_task)
    scheduler.handle_schedule(ground_task)
    assert len(timers) == 1

    room.ground.cell = room.ground.ball
    assert room.start_throw('二垒')
    room.throw.left = 8
    scheduler.handle_schedule(engine._tick_tasks(room)[0])
    assert len(timers) == 2
    assert timers[0].cancelled

    timers[0].callback(*timers[0].args)         # 旧链的计时器：推不动新阶段
    assert room.throw.left == 8
    timers[1].callback(*timers[1].args)
    assert room.throw.left == 7
    assert len(timers) == 3                     # 这一拍走完自动续下一拍
    assert timers[2].delay == rules.TICK_MS / 1000
    results = scheduler._server.results
    assert results and results[-1]['action'] == 'baseball_play'


def test_state_result_sends_boards_to_both_players():
    """阶段推进后双方都收到棋盘；不轮到的一方没有菜单。"""
    from server.msg_types import ROOM_UPDATE

    engine, room = _engine_with_room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    ok, _ = room.set_pitch(
        pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    assert ok and room.phase == 'call'

    result = engine._state_result(Mock(), room, pitcher, ['投出直球'])
    messages = result['send_to_players'][batter]
    kinds = [message['type'] for message in messages]
    assert ROOM_UPDATE in kinds
    board = next(m['room_data'] for m in messages if m['type'] == ROOM_UPDATE)
    assert board['phase'] == 'call'
    assert board['viewer_side'] == 'batting'
    assert not any(m['type'] == 'select_menu' for m in messages)


def test_commands_json_matches_engine_command_map():
    import json
    from pathlib import Path

    engine = BaseballEngine()
    path = (Path(__file__).resolve().parent.parent / 'Server' / 'server'
            / 'games' / 'baseball' / 'data' / 'commands.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    assert set(data) == {'baseball:lobby', 'baseball:room', 'baseball:playing'}
    playing = {item['name'] for item in data['baseball:playing']}
    declared = set(engine._COMMAND_MAP['playing'])
    assert playing == declared
    assert engine._COMMAND_MAP['playing']['pitch'] == '_cmd_pitch'
    assert engine._COMMAND_MAP['playing']['swing'] == '_cmd_swing'
    assert engine._COMMAND_MAP['playing']['hit'] == '_cmd_hit'


def test_the_client_parses_the_payload_of_every_phase_for_both_sides():
    """协议契约：服务端每个阶段给每一方发的数据，客户端都能严格解析（缺字段就报错）。"""
    from client.games.baseball.view import Board

    rooms = {'call': _room()}
    delivering = _room()
    delivering.set_pitch(delivering.fielding_player(),
                         rules.PitchCall('four_seam', 'inside', 'normal'))
    delivering.set_swing(delivering.batting_player(),
                         rules.SwingCall('four_seam', 'power'))
    _through_countdown(delivering)
    rooms['delivery'] = delivering
    flying = _room()
    flying.bases = [1]
    flying._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                       ticks=5, tick_ms=100))
    rooms['flight'] = flying
    grounded = _room()
    grounded.bases = [1]
    _ground_play(grounded, rules.HitBall(kind='ground', landing=7, shown=7,
                                         ticks=3, tick_ms=100), 7)
    rooms['ground'] = grounded
    throwing = _room()
    throwing.bases = [1]
    _ground_play(throwing, rules.HitBall(kind='ground', landing=7, shown=7,
                                         ticks=3, tick_ms=100), 7)
    throwing.ground.cell = throwing.ground.ball
    throwing.start_throw('二垒')
    rooms['throw'] = throwing
    rooms['tag'] = _tag_room([3])

    for phase, room in rooms.items():
        for player in room.players:
            board = Board.parse(room.get_game_data(viewer=player))
            assert board.phase == phase
            assert board.tick_ms > 0


# ── 客户端 ──


def _room_data(room: BaseballRoom, viewer: str) -> dict:
    return room.get_game_data(viewer=viewer)


def _flat_state(ui) -> dict:
    """把交互状态翻成测试读起来顺手的平面字典：菜单、光标、模式、动画值。"""
    controls = ui.controls

    def flat(item) -> dict:
        data = {'label': item.label, 'action': item.action}
        for key in ('desc', 'command', 'param', 'value'):
            if getattr(item, key):
                data[key] = getattr(item, key)
        if item.row >= 0:
            data['row'] = item.row
        if item.move is not None:
            data['move'] = item.move
        if item.live:
            data['live'] = True
        if item.home:
            data['home'] = True
        return data

    values = ui.anim.values
    return {
        'menu': [flat(item) for item in controls.items],
        'cursor': controls.cursor, 'title': controls.title,
        'stack': list(controls.stack), 'pad': controls.is_pad,
        'my_turn': controls.mode == 'act',
        'preview': controls.mode == 'preview',
        'active': not ui.waiting,
        'move': controls.move, 'root_kind': controls.kind,
        'form': dict(vars(ui.form)),
        'ball_at': values.get('ball', 0.0),
        'field_at': values.get('field', 0.0),
        'delivery_at': values.get('delivery', 0.0),
        'throw_at': values.get('throw', 0.0),
        'runner_at': {name.split(':', 1)[1]: value
                      for name, value in values.items()
                      if name.startswith('runner:')},
    }


@pytest.fixture(autouse=True)
def _flat_interaction_state(monkeypatch):
    """客户端测试读到的交互状态：框架存的是 `{'ui': Ui}`，这里额外铺一份平面字典。"""
    from client.state.game_interaction import GameInteractionState

    original = GameInteractionState.snapshot

    def snapshot(self, game_type):
        data = original(self, game_type)
        if data is None or game_type != 'baseball' or 'ui' not in data:
            return data
        return {**data, **_flat_state(data['ui'])}

    monkeypatch.setattr(GameInteractionState, 'snapshot', snapshot)


@pytest.fixture(autouse=True)
def _fielder_cell(monkeypatch):
    """测试里直接把野手放到某一格（`room.ground.cell = 6`），读出来的是他此刻的位置。"""
    def put(self, cell):
        self.fielder.place(float(cell), self.fielder.at)

    for state_class in (Flight, Pickup):
        monkeypatch.setattr(
            state_class, 'cell',
            property(lambda self: self.fielder.pos, put), raising=False)


class _Client:
    """测试里的一个玩家客户端：处理器、状态、发出去的指令、可手动拨的时钟与计时器。"""

    def __init__(self) -> None:
        from client.games.baseball.handler import BaseballHandler
        from client.protocol.handler import GameHandlerContext
        from client.state import ModuleStateManager

        self.state = ModuleStateManager()
        self.handler = BaseballHandler()
        self.clock = [100.0]
        self.handler.clock = lambda: self.clock[0]
        self.sent: list[str] = []
        self.timers: list = []
        self.ctx = GameHandlerContext(
            self.state, get_module=lambda _: None,
            set_timer=lambda delay, callback: self.timers.append(
                (delay, callback)),
            send_command=self.sent.append)

    def update(self, room: BaseballRoom, viewer: str) -> dict:
        data = room.get_game_data(viewer=viewer)
        self.handler.on_room_update(data, self.ctx)
        self.state.game_board.update_room(data)
        return data

    @property
    def ui(self):
        return self.state.game_interaction.snapshot('baseball')['ui']

    @property
    def labels(self) -> list[str]:
        return [item.label for item in self.ui.controls.items]

    def press(self, *directions: str) -> None:
        for direction in directions:
            self.handler.on_nav(direction, self.ctx)


def _dump(renderable, width: int) -> str:
    from rich.console import Console

    console = Console(width=width, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


def _track_lines(text: str) -> list[str]:
    """棋盘底部三条固定行，按顺序返回：投打 → 外野 → 传球（行首有 2 列左边距）。"""
    return [line for line in text.split('\n')
            if line.lstrip().startswith(('投打', '外野', '传球'))]


def _field_line(text: str) -> str:
    """三条固定行里的第二条：外野线。"""
    return _track_lines(text)[1]


def _visual(text: str) -> int:
    """这段文字在终端里占几列（所有字形都算一列，中日韩文字两列）。"""
    return cell_width(text)


def _lane_line(text: str, index: int) -> str:
    """三条固定行：0＝投打行、1＝外野线、2＝传球行（永远都在，各自有前缀）。"""
    return _track_lines(text)[index]


def test_board_draws_base_square_with_lanes_and_no_digits():
    """棋盘只有图形：正方形四条边都画通，垒包就是四个角。"""
    from client.config import NF_CIRCLE_NOTCH, NF_OFFLINE, NF_ONLINE, NF_USER

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.bases = [1, 3]
    data = _room_data(room, room.fielding_player())

    sections = renderer.render_board(data, None, board_width=64)
    text = _dump(sections['board'], 64)

    lines = [line for line in text.split('\n') if line.strip()]
    top_labels = next(line for line in lines if '三垒' in line)
    bottom_labels = next(line for line in lines if '本垒' in line)
    assert top_labels.index('三垒') < top_labels.index('二垒')
    assert bottom_labels.index('本垒') < bottom_labels.index('一垒')
    assert text.index('三垒') < text.index('本垒')

    # 正方形：上边（三垒─二垒）、左边与右边（│）、下边（本垒─一垒）
    top_edge = next(line for line in lines if '───' in line)
    assert NF_ONLINE in top_edge and NF_OFFLINE in top_edge
    sides = [line for line in lines if line.count('│') == 2]
    assert len(sides) >= 3, sides
    bottom_edge = next(line for line in lines if '───' in line
                       and line != top_edge)
    assert NF_USER in bottom_edge           # 打者在本垒
    # 垒包不再被方框圈起来
    assert '╭' not in text and '╮' not in text
    assert '╰' not in text and '╯' not in text
    assert NF_CIRCLE_NOTCH not in text      # 没有飞行时不该有预测落点

    # 文字状态一律在右栏，棋盘上连数字都没有
    for word in ('局数', '比分', '球数', '平飞球', '号位'):
        assert word not in text
    assert not any(char.isdigit() for char in text)

    # 外野线仍是 12 格，球从 1 号位那一侧起飞
    field = _field_line(text)
    marks = sum(field.count(glyph)
                for glyph in (NF_ONLINE, NF_USER, NF_CIRCLE_NOTCH, '·'))
    assert marks == rules.FIELD_CELLS
    assert field.count(NF_USER) == 1


def test_board_marks_the_ball_the_range_and_the_fielder():
    """飞行中：球（实心圆）与野手各占一格；落点先是一段横线，窄到不足一格才收成虚线圈。"""
    from client.config import NF_CIRCLE_NOTCH, NF_ONLINE, NF_USER
    from client.games.baseball.diamond import SPAN_CAPS, SPAN_GLYPH

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room._begin_flight(rules.HitBall(kind='line', landing=9, shown=8,
                                     spread=1.0, ticks=4, tick_ms=100))

    def field_after(steps: int) -> str:
        for _ in range(steps):
            room.flight_step()
        data = _room_data(room, room.fielding_player())
        return _field_line(_dump(
            renderer.render_board(data, None, 64)['board'], 64))

    wide = field_after(1)                    # 范围 1.5 格宽：画成一条横线
    assert SPAN_GLYPH in wide and all(cap in wide for cap in SPAN_CAPS)
    assert NF_CIRCLE_NOTCH not in wide
    assert wide.count(NF_ONLINE) == 1        # 球只有一个
    assert wide.count(NF_USER) == 1          # 一个野手

    narrow = field_after(2)                  # 范围窄到不足一格：收成虚线圈
    assert narrow.count(NF_CIRCLE_NOTCH) == 1
    assert SPAN_GLYPH not in narrow
    assert narrow.count(NF_ONLINE) == 1 and narrow.count(NF_USER) == 1
    assert narrow.index(NF_ONLINE) < narrow.index(NF_CIRCLE_NOTCH)


def test_board_marks_runners_while_the_play_is_live():
    """击球进行中：正在跑向某垒的跑者用箭头，站稳后用实心圆。"""
    from client.config import NF_ARROW_R, NF_ONLINE

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.bases = [1]
    hit = rules.HitBall(kind='ground', landing=7, shown=7, ticks=4,
                        tick_ms=100)
    _ground_play(room, hit, 7)
    data = _room_data(room, room.fielding_player())
    assert data['bases'] == []                  # 击球中垒位交给 runners
    board = _dump(renderer.render_board(data, None, 64)['board'], 64)
    square = board.split('外野')[0]              # 只看垒包跑道的部分
    assert square.count(NF_ARROW_R) == 2         # 一垒跑者与打者都在跑
    assert NF_ONLINE not in square               # 还没人站稳

    room.ground_tick()
    while not room._play_over():
        room.ground_tick()
    room._end_play()
    data = _room_data(room, room.fielding_player())
    square = _dump(renderer.render_board(data, None, 64)['board'],
                   64).split('外野')[0]
    assert NF_ARROW_R not in square
    assert square.count(NF_ONLINE) == len(room.bases)


def test_board_annotates_throw_distances_after_the_ball_lands():
    """球一被打出去，四个垒的传球距离就写在垒名旁边（颜色按远近），按钮只写动作名。"""
    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    hit = rules.HitBall(kind='fly', landing=9, shown=9, ticks=5, tick_ms=100)
    _ground_play(room, hit, 9)
    room.ground.cell = room.ground.ball
    data = _room_data(room, room.fielding_player())
    options = data['ground']['options']
    assert [item['base'] for item in options] == list(rules.BASE_ORDER)

    board = _dump(renderer.render_board(data, None, 64)['board'], 64)
    for item in options:
        # 右边的垒（二垒、一垒）距离写在名字左边，这样名字有没有距离都不挪
        written = (f'{item["distance"]}米 {item["base"]}'
                   if item['base'] in ('二垒', '一垒')
                   else f'{item["base"]} {item["distance"]}米')
        assert written in board
    # 四个垒都给，不只是这一次能传的那些（提前判断该传哪）
    assert set(data['base_distances']) == set(rules.BASE_ORDER)
    # 落点越远，传球距离越大
    distances = {item['base']: item['distance'] for item in options}
    assert distances['三垒'] > distances['一垒']

    from client.games.baseball.controls import Form, plan_for
    from client.games.baseball.view import Board

    board_view = Board.parse(data)
    plan = plan_for(board_view, Form.initial(board_view))
    labels = [item.label for item in plan.items]
    assert labels[:4] == [f'传{base}' for base in rules.BASE_ORDER]
    assert labels[-1] == '不传'
    # 操作面板只写动作名，距离这类说明性数据留在棋盘上
    assert all(item.desc == '' for item in plan.items)


def test_the_distance_colors_run_from_green_to_red_smoothly():
    """距离颜色平滑：最近的偏绿、最远的偏红，中间连着过渡（用户 2026-10-16 定）。"""
    from client.games.baseball import diamond

    colors = diamond._distance_colors({
        '一垒': 20.0, '二垒': 35.0, '三垒': 50.0, '本垒': 65.0})
    near = diamond._rgb(colors['一垒'])
    far = diamond._rgb(colors['本垒'])
    assert near[1] > near[0]               # 近：绿色分量更大
    assert far[0] > far[1]                 # 远：红色分量更大
    middle = diamond._rgb(colors['二垒'])
    assert near != middle != far
    assert all(color.startswith('#') for color in colors.values())


def test_the_corner_rows_never_outgrow_the_square():
    """垒名行（带四个距离）绝不许比正方形宽——超了就连距离一起省掉。"""
    from client.games.baseball.diamond import Infield
    from client.games.baseball.view import Board

    room = _room()
    room.bases = [1]
    hit = rules.HitBall(kind='ground', landing=7, shown=7, ticks=4,
                        tick_ms=100)
    _ground_play(room, hit, 7)
    live = Board.parse(_room_data(room, room.fielding_player()))
    for width in (46, 58, 78, 88):
        infield = Infield(live, None, width, 19)
        rows = infield.render()
        for row in (rows[0], rows[-1]):
            assert cell_width(row.plain) <= infield.width, (width, row.plain)

    # 宽窗口：距离照旧写在垒名后；没落地时不该出现传球距离
    rendered = _dump(RENDERER_REGISTRY['baseball'].render_board(
        _room_data(room, room.fielding_player()), None, 64, 19)['board'], 64)
    assert '三垒' in rendered and '米' in rendered
    plain = _dump(RENDERER_REGISTRY['baseball'].render_board(
        _room_data(_room(), room.fielding_player()), None, 64, 19)['board'],
        64)
    assert '米' not in plain


def test_the_base_names_keep_their_columns_whether_or_not_distances_show():
    """用户 2026-11-15：东西都在原位。出传球距离时，二垒/一垒的名字不许往左挪。"""
    from client.games.baseball.diamond import Infield
    from client.games.baseball.view import Board

    room = _room()
    room.bases = [1]
    quiet = Board.parse(_room_data(room, room.fielding_player()))
    _ground_play(room, rules.HitBall(kind='ground', landing=7, shown=7,
                                     ticks=4, tick_ms=100), 7)
    live = Board.parse(_room_data(room, room.fielding_player()))

    def columns(board, width):
        rows = Infield(board, None, width, 19).render()
        found = {}
        for row in (rows[0], rows[-1]):
            plain = row.plain
            for name in ('三垒', '二垒', '本垒', '一垒'):
                if name in plain:
                    found[name] = cell_width(plain[:plain.index(name)])
        return found

    for width in (46, 58, 78, 88):
        assert columns(quiet, width) == columns(live, width), width


def test_board_animates_the_pitch_before_the_result():
    """投打行：球在轨道上从右往左逐帧前移，段与段之间不跳帧。"""
    from client.config import NF_ONLINE

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    positions: list[int] = []
    while room.phase == 'delivery':
        data = _room_data(room, room.batting_player())
        if data['delivery']['stage'] == 'swing':
            break
        board = _dump(renderer.render_board(data, None, 64)['board'], 64)
        row = _lane_line(board, 0)              # 第一条带前缀的行＝投打行
        positions.append(row.index(NF_ONLINE))
        room.delivery_step()

    assert len(positions) == rules.PITCH_ANIM_FRAMES
    assert positions == sorted(positions, reverse=True)   # 从右往左飞
    assert positions[0] > positions[-1]
    while room.phase == 'delivery':             # 挥棒段：球停在本垒那一端
        room.delivery_step()
    data = _room_data(room, room.batting_player())
    row = _lane_line(_dump(renderer.render_board(data, None, 64)['board'], 64),
                     0)
    assert NF_ONLINE not in row                 # 这一球结束了，轨道上没有球


def test_status_pages_are_ordered_by_importance():
    """三页顺序不变；**行位固定**：局面页永远是那 5 行，没内容的行留空占位。"""
    from client.games.baseball import status as module

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.bases = [2]
    room.outs = 2
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=8,
                                     ticks=5, tick_ms=100))
    room.flight.ball = 3
    data = _room_data(room, room.fielding_player())

    status = renderer.render_status(data)
    assert [name for name, _ in status.pages] == [
        '局面', '比分', '侦察', '属性']

    first = _dump(status.pages[0][1], 38)
    from client.config import NF_OFFLINE, NF_ONLINE, NF_STAR
    labels = [line.strip().split()[0] for line in first.split('\n')
              if line.strip()]
    assert labels == ['局数', '比分', '出局', '球数', '体力']
    assert len(labels) <= module.STATUS_HEIGHT - 2
    assert '比分' in first and '出局' in first and '球数' in first
    assert first.count(NF_ONLINE) >= 2 and NF_OFFLINE in first  # 出局圆点
    # 只放棋盘上没有的比分牌数据；其他东西（这一拍在干什么、交牌灯、跑者、传球）
    # 都在棋盘上，右栏不重复
    for word in ('阶段', '就绪', '打者', '跑者', '传球', '落点', '球位', '野手',
                 '高飞球', '中线偏右'):
        assert word not in first, word
    assert NF_STAR not in first
    # 不写句子：状态页里不该出现这几个标点
    for mark in ('：', '，', '。', '（', '）'):
        assert mark not in first, mark

    second = _dump(status.pages[2][1], 38)
    assert len(second.rstrip('\n').split('\n')) == module._HISTORY_SLOTS * 2
    third = _dump(status.pages[3][1], 38)
    for word in ('我方投手', '我方打者', '我方野手', '布阵'):
        assert word in third
    assert '控' in third and '力' in third
    # 面板高度够最高的那一页（侦察 6 行 + 上下边框），也不再浪费多余的行
    assert renderer.status_height(data) == module._HISTORY_SLOTS * 2 + 2


def test_ready_lights_show_who_has_submitted():
    """交牌灯在**棋盘中间那一槽**（固定槽位）：两边交牌前空心圆，交牌后实心绿灯。"""
    from client.config import NF_OFFLINE, NF_ONLINE
    from client.games.baseball.diamond import live_slot_segments
    from client.games.baseball.view import Board

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    board = _dump(renderer.render_board(
        _room_data(room, pitcher), None, 88, 19)['board'], 88)
    assert '投' in board and '打' in board
    assert board.count(NF_OFFLINE) >= 2       # 两个灯都还没亮

    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    board_text = renderer.render_board(
        _room_data(room, pitcher), None, 88, 19)['board']
    board = _dump(board_text, 88)
    assert NF_ONLINE in board                 # 投手那个灯亮了（绿灯实心圆）
    # 样式走格子、不走文字：盘面上绝不能出现富文本标记的生字符串（2026-10-17 实机 bug）
    assert '[#' not in board and '[/]' not in board
    assert any('50b070' in str(span.style) for span in board_text.spans)
    assert live_slot_segments(
        Board.parse(_room_data(room, pitcher)))[2]   # 中槽里放着这两盏灯

    ok, lines = room.set_swing(batter, rules.SwingCall('four_seam', 'take',
                                                       'normal'))
    assert ok and lines == []                 # 不另发提示：两盏灯就是提示
    assert room.phase == 'call'               # 倒数期间还没开投
    assert room.countdown == rules.COUNTDOWN_SECONDS
    _through_countdown(room)
    assert room.phase == 'delivery'


def test_the_countdown_locks_both_calls_and_then_starts_the_pitch():
    """两边交牌 → 倒数 3 秒（这期间谁也不能改）→ 投手按「投球」才开投（用户 2026-10-16 定）。"""
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    ok, lines = room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                                       'normal'))
    assert ok and lines == []
    assert room.phase == 'call'                     # 还没开投
    assert room.countdown == rules.COUNTDOWN_SECONDS
    assert room.delivery is None
    # 倒数期间两边都改不了：交牌还锁在 pending 里，灯继续亮着
    assert room.ready_sides() == {'fielding': True, 'batting': True}
    assert room.set_pitch(pitcher, rules.PitchCall('changeup', 'inside',
                                                  'full'))[0] is False
    assert room.set_swing(batter, rules.SwingCall('changeup', 'take',
                                                  'normal'))[0] is False
    for left in (2, 1):
        room.countdown_tick()
        assert room.countdown == left
        assert room.phase == 'call'
    room.countdown_tick()                           # 0：球交给投手（还没投出去）
    assert room.countdown == 0
    assert room.phase == 'call'
    assert room.delivery is None
    assert room.armed is True                       # 投手那颗「投球」键亮了
    assert room.pending != {}                       # 交牌还锁着，等他按投球
    assert room.release_pitch(batter) is False      # 只有投手能投
    assert room.release_pitch(pitcher) is True
    assert room.armed is False
    assert room.phase == 'delivery'
    assert room.delivery.stage == rules.DELIVERY_PITCH
    assert room.pending == {}                       # 交牌这时才解锁
    assert room.release_pitch(pitcher) is False     # 一球只能投一次


def test_the_countdown_does_not_restart_when_both_sides_are_ready():
    """两边都交了之后又有人重交（不可能，但防线要有）：倒数不重置。"""
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    room.countdown_tick()
    assert room.countdown == rules.COUNTDOWN_SECONDS - 1
    room._start_when_both_ready()
    assert room.countdown == rules.COUNTDOWN_SECONDS - 1


def test_pressing_after_the_ball_arrives_is_a_late_swing():
    """球到了本垒（挥棒段）再按也算挥棒，就是「延后」（用户 2026-10-15 定）。"""
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    while room.phase == 'delivery' and room.delivery.stage == 'pitch':
        room.delivery_step()
    assert room.delivery.stage == rules.DELIVERY_SWING
    assert room.swing_now(batter, 1)[0] is True     # 挥棒段里按得动
    assert room.exchange.swing.timing == 'late'
    while room.phase == 'delivery':
        room.delivery_step()
    assert '时机延后' in '\n'.join(room.log)    # 事后日志只陈述按在了哪一档


def test_the_pitch_report_states_the_timing_and_the_read_as_facts():
    """每球结束后日志多一行事实：按在哪一档、预判球种对不对；放过去的球没有这一行。"""
    def play(guess: str, frame: int | None) -> str:
        room = _room()
        pitcher, batter = room.fielding_player(), room.batting_player()
        room.set_pitch(pitcher, rules.PitchCall('slider', 'edge', 'normal'))
        room.set_swing(batter, rules.SwingCall(guess, 'standard'))
        _through_countdown(room)
        while room.phase == 'delivery':
            if frame is not None and room.delivery.frame == frame \
                    and not room.delivery.swung \
                    and room.delivery.stage == rules.DELIVERY_PITCH:
                room.swing_now(batter, frame)
            room.delivery_step()
        return '\n'.join(room.log)

    early_wrong = play('four_seam', 1)
    assert '时机提前 预判错误' in early_wrong
    normal_right = play('slider', 5)
    assert '时机正常 预判正确' in normal_right
    assert '时机' not in play('slider', None)       # 没按＝放过去，没有时机可言
    # 只说发生了什么：不写概率、不写这一档对不对
    assert '%' not in early_wrong and '应' not in early_wrong


def test_submenu_title_is_underlined():
    """二级菜单标题下面要有一根横杠（和外层面板的标题线一样，用户 2026-10-15 要求）。"""
    from client.games.baseball.controls import (
        MODE_ACT, Controls, Item)
    from client.games.baseball.panel import _RULE_GLYPH, render_controls

    controls = Controls(
        items=[Item('布阵', desc='标准站位', action='open', param='shift')],
        title='布阵')
    controls.plan = type('P', (), {'mode': MODE_ACT, 'kind': 'pitch'})()
    text = _dump(render_controls(controls, 40), 40)
    lines = text.split('\n')
    assert lines[0].startswith('布阵')
    assert set(lines[1].strip()) == {_RULE_GLYPH}
    assert '标准站位' in text

    # 一级主盘不留标题，也就不多这一行
    controls.title = ''
    assert _RULE_GLYPH not in _dump(render_controls(controls, 40), 40)


def test_the_delivery_animation_spans_exactly_one_server_frame():
    """投打动画按时间滑，而且领先一拍：一帧到来就朝下一帧滑，
    滑动的时长＝服务端一拍的时长，球出手的瞬间就在动，也不会落在服务端后面。"""
    client = _Client()
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    client.clock = [100.0]
    client.update(room, batter)
    anim = client.ui.anim
    assert anim.values['delivery'] == 0.0             # 出手那一刻球在起点……
    assert anim.moving                                # ……但已经朝第 1 帧滑起来了
    handler = client.handler
    snapshot = {'ui': client.ui}
    client.clock[0] += rules.ANIM_FRAME_MS / 2000
    handler._advance(snapshot)
    assert 0.0 < snapshot['ui'].anim.values['delivery'] < 1.0   # 滑到一半
    client.clock[0] += rules.ANIM_FRAME_MS / 2000 + 0.001
    assert handler._advance(snapshot) is False        # 正好在下一拍到来时走完
    assert snapshot['ui'].anim.values['delivery'] == 1.0
    client.state.game_interaction.replace('baseball', snapshot)
    room.delivery_step()                              # 服务端的第 1 帧到了：接着滑向第 2 帧
    client.update(room, batter)
    assert client.ui.anim.values['delivery'] == 1.0   # 没有停顿，从上一帧的终点接着滑
    assert client.ui.anim.moving


def test_status_page_lists_runners_and_throw_target():
    """跑者与传球进度在**棋盘**上（右栏只留比分牌）；棋盘中间三槽写出这一拍在干什么。"""
    from client.games.baseball.diamond import situation_label
    from client.games.baseball.view import Board

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.bases = [1]
    hit = rules.HitBall(kind='ground', landing=7, shown=7, ticks=4,
                        tick_ms=100)
    _ground_play(room, hit, 7)
    room.ground.cell = room.ground.ball
    room.start_throw('二垒')
    data = _room_data(room, room.fielding_player())
    board = _dump(renderer.render_board(data, None, 88, 19)['board'], 88)
    assert '传球' in board and '二垒' in board          # 传球行写着目标垒
    assert situation_label(Board.parse(data)) in board   # 中间槽写着这一拍在干什么
    first = _dump(renderer.render_status(data).pages[0][1], 38)
    assert '传球' not in first and '跑者' not in first   # 右栏不重复棋盘上的东西
    assert room.throw.distance == round(
        rules.throw_distance(7, 'ground', '二垒'), 1)


def test_game_window_shows_baseball_status_tabs():
    """右栏状态面板用标签页分局面/侦察/属性，棋盘上只有图形。"""
    import asyncio

    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    from client.state import ModuleStateManager
    from client.views.game.board import GameBoardPanel
    from client.views.game.status import GameStatusPanel
    from client.views.game.window import GameWindow

    class GameApp(App):
        def compose(self) -> ComposeResult:
            yield GameWindow(id="game-window")

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.bases = [1]
    data = _room_data(room, room.batting_player())
    data['message'] = '界外'

    async def verify() -> None:
        app = GameApp()
        async with app.run_test(size=(88, 32)) as pilot:
            window = app.query_one(GameWindow)
            window.add_class("visible")
            state = ModuleStateManager()
            window.bind_state(state)
            state.game_board.update_room(data)
            await pilot.pause()

            status = window.query_one(GameStatusPanel)
            assert status.region.height == renderer.status_height(data)
            assert status.tabs == ['局面', '比分', '侦察', '属性']
            assert '局面' in str(status.border_title)
            assert status.query_one('#t0', VerticalScroll).display is True
            assert status.query_one('#t1', VerticalScroll).display is False
            status.switch_tab(1)
            await pilot.pause()
            assert status.query_one('#t0', VerticalScroll).display is False
            assert status.query_one('#t1', VerticalScroll).display is True

            board = window.query_one(GameBoardPanel)
            text = str(board.query_one('#board-main', Static).content)
            assert '本垒' in text and '一垒' in text and '外野' in text
            assert '比分' not in text and '局数' not in text
            assert not any(char.isdigit() for char in text)
            board_view = board.query_one('#t0', VerticalScroll)
            assert board_view.region.height >= 9

    asyncio.run(verify())


def _handler_ctx(state):
    from client.protocol.handler import GameHandlerContext

    sent: list[str] = []
    ctx = GameHandlerContext(
        state, get_module=lambda _: None,
        set_timer=lambda delay, callback: None, send_command=sent.append,
    )
    return ctx, sent


def test_handler_builds_two_level_menus_and_sends_complete_commands():
    """棋盘下方是一级/二级菜单：选完值回到一级，投球前再确认一次。"""
    client = _Client()
    room = _room()
    fielder = room.fielding_player()
    client.update(room, fielder)
    assert client.labels == ['布阵', '球种', '区域', '力度', '确定']
    assert client.state.game_interaction.snapshot('baseball')['menu'][0][
        'desc'] == rules.SHIFT_LABELS['standard']
    assert client.ui.controls.mode == 'act'

    def snapshot() -> dict:
        return client.state.game_interaction.snapshot('baseball')

    # 一级 →「布阵」二级菜单：列出取值 + 返回，游标停在当前取值
    client.press('enter')
    assert client.labels == [
        rules.SHIFT_LABELS[key] for key in rules.SHIFTS] + ['返回']
    assert snapshot()['cursor'] == 0
    client.press('right', 'enter')
    assert client.sent == ['/shift left']           # 选中即生效
    assert client.labels == ['布阵', '球种', '区域', '力度', '确定']   # 回到一级
    assert snapshot()['menu'][0]['desc'] == rules.SHIFT_LABELS['left']  # 取值同步
    assert snapshot()['cursor'] == 0                # 还能接着选下一项

    # 服务端确认布阵后，一级菜单显示新取值，游标不被顶掉
    room.set_shift(fielder, 'left')
    client.update(room, fielder)
    assert snapshot()['menu'][0]['desc'] == rules.SHIFT_LABELS['left']
    assert snapshot()['cursor'] == 0

    # 「区域」二级菜单：上下键也能走，选值不发指令（留到投球时一起发）
    client.press('right', 'right', 'enter')
    assert client.labels == [
        rules.BAND_LABELS[key] for key in rules.BANDS] + ['返回']
    client.press('down', 'enter')
    assert snapshot()['menu'][2]['desc'] == rules.BAND_LABELS['edge']
    assert client.sent == ['/shift left']

    # 「返回」不改取值
    client.press('enter')
    client.press('down', 'down')
    assert snapshot()['cursor'] == len(snapshot()['menu']) - 1
    assert snapshot()['menu'][-1]['label'] == '返回'
    client.press('enter')
    assert snapshot()['menu'][2]['desc'] == rules.BAND_LABELS['edge']

    # 最后一项「确定」→ 是否确定 → 否回到一级、是才发出完整参数
    while snapshot()['menu'][snapshot()['cursor']]['label'] != '确定':
        client.press('down')
    client.press('enter')
    assert client.labels == ['是', '否']
    client.press('down', 'enter')                   # 选「否」回上一级
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '确定'
    assert snapshot()['menu'][3]['desc'] == rules.EFFORT_LABELS['normal']
    client.press('enter', 'enter')                  # 选「是」投出去
    assert client.sent[-1] == '/pitch four_seam edge normal no'
    # 交牌那一刻就离开确认子菜单、回到当前阶段的菜单（用户 2026-10-15 要求）
    assert snapshot()['stack'] == []
    assert snapshot()['title'] == ''
    assert snapshot()['cursor'] == 0
    assert client.labels == ['布阵', '球种', '区域', '力度', '确定']


def test_the_runner_item_only_exists_while_a_runner_can_be_held():
    """垒上没人时「跑者（牵制）」没有意义，表单里不出现；垒上有人才多这一项，
    并且没人时不管表单里存着什么，一律按「不牵制」交牌。"""
    client = _Client()
    room = _room()
    fielder = room.fielding_player()
    room.bases = [1]
    client.update(room, fielder)
    assert client.labels == ['布阵', '球种', '区域', '力度', '跑者', '确定']
    client.press('down', 'down', 'down', 'down', 'enter')   # 进「跑者」二级菜单
    assert client.labels == [rules.HOLD_LABELS[key]
                             for key in rules.HOLDS] + ['返回']
    client.press('down', 'enter')                            # 选「牵制跑者」
    assert client.ui.form.hold == 'yes'

    room.bases = []
    client.update(room, fielder)
    assert client.labels == ['布阵', '球种', '区域', '力度', '确定']
    while client.ui.controls.items[client.ui.controls.cursor].label != '确定':
        client.press('down')
    client.press('enter', 'enter')
    assert client.sent[-1].endswith(' no')                   # 存着的 yes 不会发出去


def test_the_cursor_rests_on_confirm_after_the_first_submit():
    """交过一次牌之后，下一球的表单光标停在「确定」：原样再来一球只要 回车→回车。"""
    client = _Client()
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    client.update(room, pitcher)
    assert client.ui.controls.cursor == 0              # 开局第一球：从第一项开始设置
    while client.ui.controls.items[client.ui.controls.cursor].label != '确定':
        client.press('down')
    client.press('enter', 'enter')
    assert client.sent[-1].startswith('/pitch ')

    # 这一球走完（放过去），回到出牌阶段：光标直接停在「确定」
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
    client.update(room, pitcher)                        # 倒数、投球：客户端一路看着
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
        client.update(room, pitcher)
    assert room.phase == 'call'
    assert client.labels[client.ui.controls.cursor] == '确定'
    client.press('enter', 'enter')
    assert client.sent[-1].startswith('/pitch ')

    swinger = _Client()                                 # 打者那一边同理
    swinger.update(room, batter)
    assert swinger.ui.controls.cursor == 0
    while swinger.ui.controls.items[swinger.ui.controls.cursor].label != '确定':
        swinger.press('down')
    swinger.press('enter', 'enter')
    assert swinger.sent[-1].startswith('/swing ')


def test_value_menus_only_name_the_options():
    """二级菜单只写取值名字，不写“这个值值什么”。

    用户 2026-10-15 定档：选项的作用是玩家该自己研究、自己判断的东西——
    把概率与效果直接印在菜单上，等于替玩家把账算完，游戏就没得研究了。
    """
    client = _Client()
    room = _room()
    room.bases = [1]
    batter = room.batting_player()
    client.update(room, batter)
    # 垒上有人：表单是 预判 / 挥棒 / 盗垒 / 确定（和投球表单一样，设置项在前、确定在最后）

    def snapshot() -> dict:
        return client.state.game_interaction.snapshot('baseball')

    assert client.labels == ['预判', '挥棒', '盗垒', '确定']
    client.press('enter')                           # 预判（游标开局停在第一项）
    assert client.labels == \
        [rules.PITCH_TYPE_LABELS[key] for key in rules.PITCH_TYPES] + ['返回']
    assert not [item for item in snapshot()['menu'] if item.get('desc')]
    client.press('enter')                           # 返回：不改取值
    client.press('right')                           # 挥棒
    client.press('enter')
    assert client.labels == \
        [rules.SWING_LABELS[key] for key in rules.SWINGS] + ['返回']
    # 挥棒三项：标准 / 大力 / 滚地球，中文 + 英文，没有「等球」（用户 2026-10-15 定）
    assert client.labels[:3] == [
        '标准挥击 Standard Swing', '大力挥击 Power Swing',
        '滚地球 Ground Ball']
    assert not [item for item in snapshot()['menu'] if item.get('desc')]
    assert not hasattr(rules, 'SWING_HINTS')        # 效果文案不该再存在


def _slots(data: dict) -> tuple[str, str, str, str]:
    """方框中间四槽的纯文字：判定 / 倒数 / 交牌灯或方位 / 当前动作。"""
    from client.games.baseball.diamond import live_slot_segments
    from client.games.baseball.view import Board

    return tuple(''.join(text for text, _ in slot)
                 for slot in live_slot_segments(Board.parse(data)))


def test_the_diamond_shows_four_fixed_live_slots():
    """四个垒包中间那四槽：判定 / 倒数 / 交牌灯或方位 / 当前动作，位置钉死，不显示就留白。

    用户 2026-10-15 定：实时内容都放棋盘中间（属性那类静态数据留在右栏面板），
    某一槽空着时别的内容不许挤过来。
    """
    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    fielder = room.fielding_player()
    data = _room_data(room, fielder)
    board = _dump(renderer.render_board(data, None, 88, 32)['board'], 88)
    # 开局：三槽全空，方框里干干净净
    assert 'SAFE' not in board and 'OUT' not in board
    assert '投球' not in board.split('\n')[5]

    # 这一拍判定：出局按方式写（封杀 / 接杀 / 触杀），空槽不动别的槽
    room.verdict = 'force_out'
    data = _room_data(room, fielder)
    board_out = _dump(renderer.render_board(data, None, 88, 32)['board'], 88)
    rows_out = board_out.split('\n')
    verdict_row = next(i for i, row in enumerate(rows_out)
                       if '封杀 FORCE OUT' in row)

    # 倒数槽和判定槽各占一行，位置与没判定时完全一样（行数、行号都不变）
    room2 = _room()
    room2.set_pitch(room2.fielding_player(),
                    rules.PitchCall('four_seam', 'edge', 'normal'))
    room2.set_swing(room2.batting_player(),
                    rules.SwingCall('four_seam', 'standard', 'normal'))
    assert room2.countdown == rules.COUNTDOWN_SECONDS
    data2 = _room_data(room2, room2.fielding_player())
    board_count = _dump(renderer.render_board(data2, None, 88, 32)['board'], 88)
    rows_count = board_count.split('\n')
    assert len(rows_count) == len(rows_out)
    count_row = next(i for i, row in enumerate(rows_count)
                     if row.strip(' │').strip() == '3')
    assert count_row != verdict_row
    assert '封杀 FORCE OUT' not in board_count

    # 当前动作：投球段写「投球」，挥棒段写「挥棒」
    _through_countdown(room2)
    data3 = _room_data(room2, room2.fielding_player())
    assert _slots(data3)[3] == '投球'
    while room2.delivery.stage == rules.DELIVERY_PITCH:
        room2.delivery_step()
    batting = _room_data(room2, room2.batting_player())
    assert _slots(batting)[3] == '挥棒'
    # 属性（静态）不在棋盘上，只在右栏：棋盘里不出现控球/力量这些词
    assert '控球' not in _dump(
        renderer.render_board(batting, None, 88, 32)['board'], 88)

    # 球被打出去之后：判定槽写球的方位（飞向哪 / 落在哪），双方同一份（2026-10-17 定）
    room3 = _room()
    room3._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                      ticks=4, tick_ms=100))
    for viewer in (room3.fielding_player(), room3.batting_player()):
        data4 = _room_data(room3, viewer)
        assert _slots(data4)[2] == f'飞向 {rules.field_label(9)}'
    room4 = _room()
    _ground_play(room4, rules.HitBall(kind='ground', landing=7, shown=7,
                                      ticks=3, tick_ms=100), 7)
    data5 = _room_data(room4, room4.fielding_player())
    assert _slots(data5)[2] == f'落点 {rules.field_label(7)}'
    # 判定有自己的一槽：出判定后方位照旧在原位，谁也不顶替谁
    room4.verdict = 'safe'
    data6 = _room_data(room4, room4.fielding_player())
    assert _slots(data6)[0] == '安全 SAFE'
    assert _slots(data6)[2] == f'落点 {rules.field_label(7)}'


def test_the_ready_lights_stay_in_place_while_the_last_verdict_is_shown():
    """用户 2026-11-15 实机：安全上垒后，下一球的交牌阶段只剩 SAFE、准备灯不见了。

    东西都在原位，亮不亮都占同样空间：判定和灯各占自己的槽，同一行号，互不顶替。
    """
    renderer = RENDERER_REGISTRY['baseball']

    def rows(room, viewer):
        text = _dump(renderer.render_board(
            _room_data(room, viewer), None, 46, 19)['board'], 46)
        return text.split('\n')

    room = _room()
    viewer = room.fielding_player()
    before = rows(room, viewer)
    lights_row = next(i for i, row in enumerate(before) if '投' in row
                      and '打' in row and '│' in row)
    room.verdict = 'safe'
    after = rows(room, viewer)

    assert len(after) == len(before)
    assert '投' in after[lights_row] and '打' in after[lights_row]
    verdict_row = next(i for i, row in enumerate(after) if 'SAFE' in row)
    assert verdict_row < lights_row
    assert before[verdict_row].strip(' │') == ''     # 没判定时这一槽留白


def test_the_verdict_clears_when_the_next_pitch_starts():
    """判定只在揭晓那一刻写，下一球开投就清空（槽位留着，内容留白）。"""
    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    # 满球数：这一球不管判成好球（三振）还是坏球（保送）都会写判定出来。
    # 别钉死三振——球种的实际落点随手感属性浮动，钉死就会变成看运气的测试。
    room.strikes = STRIKES_FOR_OUT - 1
    room.balls = BALLS_FOR_WALK - 1
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'inside', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    assert room.verdict == ''
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
    assert room.verdict in ('strikeout', 'walk')

    # 下一球：开投那一刻才清空（和本垒结果符号一样，留到下一球再换）
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('slider', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('slider', 'standard', 'normal'))
    _through_countdown(room)
    assert room.verdict == ''


def test_the_fielding_side_gets_the_chase_panel_as_the_ball_leaves_the_hand():
    """球一出手，守方那边就是跑位盘（暗着）：球被打出来那一刻原地亮、接球键才加入。

    接球三键在投打动画里不上：球还没被打出来，没有球可接，摆上去只会误导
    （2026-10-17 玩家体验审计后定）。
    """
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    fielder = room.fielding_player()
    batter = room.batting_player()
    handler.on_room_update(_room_data(room, fielder), ctx)
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    assert room.phase == 'delivery'
    handler.on_room_update(_room_data(room, fielder), ctx)
    menu = snapshot()['menu']
    assert [item['label'] for item in menu] == ['左移', '停止', '右移']
    assert snapshot()['preview'] is True and snapshot()['my_turn'] is False
    assert snapshot()['title'] == ''            # 一级盘不写标题（不是子菜单）
    before = list(sent)
    handler.on_nav('enter', ctx)                # 预告期间不提交
    assert sent == before
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'
    handler.on_nav('right', ctx)                # 但游标可以先摆好
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '右移'
    assert sent == before                       # 预告里挪光标不发指令

    # 球真被打出来：同一个盘原地亮起来（还是左 / 停 / 右三个键），游标位置不跳
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=4, tick_ms=100))
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '左移', '停止', '右移']
    assert snapshot()['my_turn'] is True and snapshot()['preview'] is False
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '右移'


def test_handler_keeps_batting_choices_and_the_three_flight_buttons():
    """打击菜单同理；飞行时只有左 / 停 / 右三个键：光标落下就跑，回车＝起跳。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    batter = room.batting_player()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '预判', '挥棒', '确定']

    handler.on_nav('right', ctx)                    # 挥棒
    handler.on_nav('enter', ctx)
    handler.on_nav('right', ctx)                    # 强挥
    handler.on_nav('enter', ctx)
    assert sent == []                               # 只改本地菜单
    assert snapshot()['menu'][1]['desc'] == rules.SWING_LABELS['power']

    handler.on_nav('right', ctx)
    handler.on_nav('enter', ctx)
    handler.on_nav('enter', ctx)
    command = sent[-1].split()
    assert command[0] == '/swing'
    assert command[2] == 'power'
    assert len(command) == 4                        # 预判 + 挥棒 + 盗垒，没有时机
    assert command[3] == 'hold'                     # 垒上没人：没有盗垒可排

    # 飞行：按钮盘默认停在「停止」，方向键只挪光标，光标落到哪个按钮就生效
    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=8,
                                     ticks=5, tick_ms=100))
    fielder = room.fielding_player()
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '左移', '停止', '右移']
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'
    handler.on_nav('right', ctx)                    # → 把光标挪到「右移」
    assert sent[-1] == '/field right'
    assert snapshot()['move'] == 'right'            # 一直往右跑，直到再选「停止」
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '右移'
    handler.on_nav('right', ctx)                    # 行尾环绕回行首（和 UNO/Ludo 一致）
    assert sent[-1] == '/field left'
    assert snapshot()['move'] == 'left'
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '左移'
    handler.on_nav('left', ctx)                     # ← 也从行首环绕回行尾
    assert sent[-1] == '/field right'
    handler.on_nav('left', ctx)                     # 挪回「停止」＝服务端也停住
    assert sent[-1] == '/field stop'
    assert snapshot()['move'] == ''
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'

    # 回车＝起跳：三个键都一样，不管光标停在哪个上
    for label in ('停止', '右移'):
        while snapshot()['menu'][snapshot()['cursor']]['label'] != label:
            handler.on_nav('right', ctx)
        sent.clear()
        handler.on_nav('enter', ctx)
        assert sent == ['/jump']

    # 攻方在击出后拿到那三个跑垒按钮（默认「前进」：击出后全体前进）
    handler.on_room_update(_room_data(room, room.batting_player()), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '撤回', '停止', '前进']
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '前进'
    handler.on_nav('left', ctx)                     # 光标挪到「停止」
    assert sent[-1] == '/run stop'
    handler.on_nav('left', ctx)                     # 再 ← 是「撤回」
    assert sent[-1] == '/run back'
    handler.on_nav('right', ctx)                    # 回到「停止」
    handler.on_nav('right', ctx)                    # 再回到「前进」
    assert sent[-1] == '/run go'


def test_handler_switches_to_throw_menu_once_the_fielder_reaches_the_ball():
    """落地后先跑位，站到球上才换成四个垒包的传球菜单。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    hit = rules.HitBall(kind='line', landing=8, shown=8, ticks=4,
                        tick_ms=100)
    _ground_play(room, hit, 4)
    fielder = room.fielding_player()
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '左移', '停止', '右移']
    handler.on_nav('right', ctx)                    # 光标挪到「右移」就生效，不用回车
    assert sent[-1] == '/field right'
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '右移'
    sent.clear()
    handler.on_nav('enter', ctx)                    # 捡球时回车没有动作（不起跳、不报错）
    assert sent == []
    handler.on_nav('left', ctx)                     # 挪回「停止」＝站住
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'

    room.ground.cell = room.ground.ball
    handler.on_room_update(_room_data(room, fielder), ctx)
    distances = {item.base: item.distance
                 for item in room.throw_options()}
    assert [item['label'] for item in snapshot()['menu']] == [
        f'传{base}' for base in rules.BASE_ORDER] + ['不传']
    # 按钮只写动作名（距离写在棋盘垒角上，操作面板不写说明性数据）
    assert 'desc' not in snapshot()['menu'][0]
    assert f'{distances["一垒"]}米 一垒' in _dump(
        RENDERER_REGISTRY['baseball'].render_board(
            _room_data(room, fielder), None, board_width=88)['board'], 88)
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '不传'
    handler.on_nav('left', ctx)                     # 传球要斟酌，不执行
    assert sent[-1] == '/field stop'
    handler.on_nav('enter', ctx)
    assert sent[-1] == '/throw 本垒'

    # 传球途中先把下一次传球的按钮放出来（预告：球到了才按得动）
    room.start_throw('一垒')
    # 传球行这时才有内容：第 1 格守方、最后一格目标垒名、球在中间格点上
    board = _dump(RENDERER_REGISTRY['baseball'].render_board(
        _room_data(room, fielder), None, board_width=88)['board'], 88)
    throw_row = _lane_line(board, 2)                # 第三条固定行＝传球行
    assert throw_row.lstrip().startswith('传球')
    assert f'{room.throw.distance:.1f}' in throw_row    # 右边写着这次传球的距离
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        f'传{base}' for base in rules.BASE_ORDER] + ['不传']
    assert snapshot()['preview'] is True
    assert snapshot()['my_turn'] is False
    assert snapshot()['title'] == ''                # 一级盘不写标题（不是子菜单）
    handler.on_nav('enter', ctx)                    # 预告期间按不动
    assert sent[-1] == '/throw 本垒'


def test_pad_arrow_keys_only_move_the_cursor():
    """契约（用户 2026-10-15 定档）：方向键只挪光标，不会自己换向、不会替玩家停。

    回归的是"按 h 直接变左移、按 l 直接变右移、↓ 当成停止"那版错误实现：
    方向键一旦带动作语义，玩家就没法好好在按钮之间挪光标了。
    """
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=8,
                                     ticks=5, tick_ms=100))
    fielder = room.fielding_player()
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'
    assert sent == []                               # 还没动光标，什么都没发

    handler.on_nav('down', ctx)                     # 只有一行：↑ ↓ 什么都不发生
    assert sent == []
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'
    handler.on_nav('up', ctx)
    assert sent == []
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'

    handler.on_nav('left', ctx)                     # 光标落到「左移」＝往左跑
    assert sent[-1] == '/field left'
    handler.on_nav('right', ctx)                    # 光标回到「停止」＝站住，服务端也要知道
    assert snapshot()['move'] == ''
    assert sent[-1] == '/field stop'
    handler.on_nav('right', ctx)
    assert sent[-1] == '/field right'
    assert snapshot()['move'] == 'right'
    handler.on_nav('right', ctx)                    # 行尾环绕回行首＝改往左跑
    assert sent[-1] == '/field left'
    assert snapshot()['move'] == 'left'
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '左移'


def test_fielder_keeps_running_when_the_menu_changes_phase():
    """球落地换菜单时不打断跑位：方向保留，光标跟着方向停在同一个按钮上。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    hit = rules.HitBall(kind='fly', landing=10, shown=9, ticks=8, tick_ms=700)
    room._begin_flight(hit)
    fielder = room.fielding_player()
    handler.on_room_update(_room_data(room, fielder), ctx)
    handler.on_nav('right', ctx)
    assert snapshot()['move'] == 'right'

    room._start_ground(hit, False, room.flight.fielder)
    room.flight.fielder.place(5.0, room.flight.fielder.at)
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert snapshot()['move'] == 'right'            # 方向没被清掉
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '右移'
    assert sent[-1] == '/field right'

    room.ground.cell = room.ground.ball             # 站到球位＝跑位结束
    handler.on_room_update(_room_data(room, fielder), ctx)
    assert snapshot()['move'] == ''
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '不传'


def test_handler_smooths_the_ball_between_server_ticks():
    """球出手/击出的瞬间就开始动，朝下一拍的位置滑，滑完正好下一拍到来；落地不会跳。"""
    client = _Client()
    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=10,
                                     ticks=10, tick_ms=300))
    fielder = room.fielding_player()
    client.update(room, fielder)

    def ball() -> float:
        return client.state.game_interaction.snapshot('baseball')['ball_at']

    assert client.timers, '击出的瞬间就该排上动画帧，不用等第一拍'
    assert ball() == 1.0                             # 从起点起滑

    seen = []
    while client.timers:
        _delay, callback = client.timers.pop(0)
        client.clock[0] += 0.11
        callback()
        seen.append(ball())
    assert seen == sorted(seen) and len(seen) == 3   # 300ms 的一拍，每 110ms 一帧
    assert seen[-1] == 2.0                           # 下一拍到来时正好到位（服务端的球位 +1）

    room.flight_step()                               # 服务端的第 1 拍：球到 2 号位
    client.update(room, fielder)
    assert ball() == 2.0 == float(room.flight.ball)  # 画面球位＝服务端球位，没有慢一拍
    assert client.timers, '接着朝 3 号位滑'

    # 落地后球停在落点（滚动的球直接按服务端位置画），不再有动画
    room._land()
    client.update(room, fielder)
    assert 'ball' not in client.ui.anim.values


def test_the_ball_never_jumps_on_the_last_cell():
    """球飞到落点的那一拍，画面上的球也正好到落点——最后一格不会突然"跳"过去。"""
    client = _Client()
    room = _room()
    hit = rules.HitBall(kind='fly', landing=4, shown=4, ticks=3, tick_ms=300)
    room._begin_flight(hit)
    fielder = room.fielding_player()
    client.update(room, fielder)
    for _tick in range(hit.ticks - 1):
        client.clock[0] += hit.tick_ms / 1000
        snapshot = client.state.game_interaction.snapshot('baseball')
        client.handler._advance(snapshot)
        client.state.game_interaction.replace('baseball', snapshot)
        room.flight_step()
        client.update(room, fielder)
    client.clock[0] += hit.tick_ms / 1000
    snapshot = client.state.game_interaction.snapshot('baseball')
    client.handler._advance(snapshot)
    visual = snapshot['ui'].anim.values['ball']
    room.flight_step()                               # 最后一拍：落地判定
    assert room.phase in ('ground', 'call', 'tag')
    assert visual == pytest.approx(float(hit.landing))   # 落地那一刻球已经在落点


def test_handler_smooths_the_runners_between_server_ticks():
    """跑者也朝下一拍的位置滑：出现的瞬间就开始跑，在垒线之间一点点挪，不会直接跳到终点。"""
    client = _Client()
    room = _room()
    room.bases = [1]
    _ground_play(room, rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700), 7)
    fielder = room.fielding_player()
    client.update(room, fielder)
    runner = room.runners[0]
    key = f'{runner.at}>{runner.to}'

    def at() -> float:
        return client.state.game_interaction.snapshot(
            'baseball')['runner_at'][key]

    assert at() == 0.0
    assert client.timers, '跑者一出现就该开始跑，不用等下一拍'
    seen = []
    step = rules.TICK_MS / 1000 / 4 + 0.001
    while client.timers:
        _delay, callback = client.timers.pop(0)
        client.clock[0] += step
        callback()
        seen.append(at())
    assert seen == sorted(seen)                      # 只会向前
    assert len(seen) >= 3                            # 一拍被拆成好几帧，不是一跳
    assert seen[-1] == 1 / runner.need               # 下一拍到来时正好到位

    room.ground_tick()                               # 服务端推进一拍：从这里接着滑，不停顿
    client.update(room, fielder)
    assert at() == 1 / runner.need
    assert client.timers


def test_status_page_fits_the_fixed_panel_and_never_grows():
    """面板高度固定：塞满垒包 + 长播报也不会多出一行、不出现滚动条。"""
    from rich.console import Console

    renderer = RENDERER_REGISTRY['baseball']
    heights = set()
    for bases in ([], [1, 2, 3]):
        room = _room()
        room.bases = list(bases)
        hit = rules.HitBall(kind='fly', landing=9, shown=9, ticks=5,
                            tick_ms=100)
        _ground_play(room, hit, 7)
        room.ground.cell = room.ground.ball
        room.start_throw('二垒')
        data = _room_data(room, room.fielding_player())
        data['message'] = '落地 右边线 野手右外野 普通接球\n脱手 球滚开'
        heights.add(renderer.status_height(data))

        console = Console(width=36, record=True, color_system=None)
        console.print(renderer.render_status(data).pages[0][1])
        rows = console.export_text().rstrip('\n').split('\n')
        # 行数固定：永远是那几行（含留空占位），长播报也不会多出一行
        assert len(rows) == 5, rows
        assert len(rows) <= renderer.status_height(data) - 2, len(rows)
        # 全是棋盘上没有的比分牌数据
        body = '\n'.join(rows)
        assert '比分' in body and '出局' in body
        # 左右各缩进一个 ICON_INDENT（2 格）：左右缝一样宽、值都不贴边框，
        # 数值彼此仍然共用同一条右边缘（留空占位的行只有槽名，短一些）
        visible = [row.rstrip() for row in rows if row.strip()]
        assert visible, rows
        assert max(cell_width(row) for row in visible) == 36 - 2
        insets = {cell_width(row) - cell_width(row.lstrip()) for row in visible}
        assert insets == {2}, insets
    assert heights == {8}           # 任何局面都是同一个高度（够最高的那一页）


def test_handler_routes_room_confirm_menus_to_the_room_panel():
    """房间级确认菜单（放弃比赛）仍走右下角面板，不占棋盘下方。"""
    from client.protocol.handler import GameHandlerContext
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    calls: list[tuple] = []

    class _Panel:
        def show_select_menu(self, title, items, empty_msg='', confirm=None):
            calls.append((title, items, empty_msg, confirm))

    ctx = GameHandlerContext(
        state, get_module=lambda name: _Panel() if name == 'room_controls'
        else None,
        set_timer=lambda delay, callback: None, send_command=lambda _: None,
    )
    room = _room()
    handler.on_room_update(_room_data(room, room.fielding_player()), ctx)
    assert handler.handle_event(
        'select_menu', {'title': '确认', 'items': [{'label': '是'}],
                        'empty_msg': '',
                        'confirm': {'message': '确认放弃对局?',
                                    'command': '/forfeit yes'}},
        ctx) is True
    assert calls and calls[0][0] == '确认'
    assert calls[0][3] == {'message': '确认放弃对局?', 'command': '/forfeit yes'}
    assert state.game_interaction.snapshot('baseball')['menu'][0][
        'label'] == '布阵'



# ── 整场对局 ──


class _CollectTimer:
    """把定时器变成可驱动的队列，便于在测试里推进飞行。"""

    queue: list = []

    def __init__(self, delay, fn, args=(), kwargs=None):
        self._entry = (fn, args, delay)

    def start(self) -> None:
        _CollectTimer.queue.append(self._entry)

    def cancel(self) -> None:
        if self._entry in _CollectTimer.queue:
            _CollectTimer.queue.remove(self._entry)


class _BotMatch:
    """一个真人 + 一个机器人的对局现场：指令走引擎，机器人的计时器由测试手动泵。"""

    def __init__(self, monkeypatch, innings: int | None = None) -> None:
        monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
        monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
        monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())
        monkeypatch.setattr(threading, 'Timer', _CollectTimer)
        _CollectTimer.queue = []
        self.server = chat_server_module.ChatServer()
        self.lobby = self.server.lobby_engine
        self.engine = self.lobby._ensure_engine('baseball')
        self.scheduler = self.server.bot_schedulers['baseball']
        self.human = 'human'
        self.innings = innings
        self.now = [1000.0]                # 房间的时钟：每跑一个计时器就走过它的延时
        self.rejections: list[tuple[str, str, str]] = []
        self.received: list[dict] = []     # 真人收到的所有消息（机器人那一半走服务器分发）
        monkeypatch.setattr(
            self.server, 'send_to_player',
            lambda name, message: self.received.append(message)
            if name == self.human else None)
        self.data = get_default_user_template(name=self.human,
                                              password_hash='x')
        self.data.pop('password_hash', None)
        self.lobby.register_player(self.human, self.data)
        self.lobby.set_player_location(self.human, 'baseball')

    @property
    def room(self) -> BaseballRoom | None:
        return self.engine.get_player_room(self.human)

    def command(self, name: str, arg: str = '') -> dict:
        result = self.engine.handle_command(
            self.lobby, self.human, self.data, name, arg)
        for message in result.get('send_to_caller', []):
            text = message.get('room_data', {}).get('message', '')
            if text:                       # 服务端拒收：回了一句提示
                self.rejections.append((name, arg, text))
        self.received.extend(result.get('send_to_caller', []))
        self.received.extend(result.get('send_to_players', {}).get(
            self.human, []))
        for task in result.get('schedule', []):
            scheduler = self.server.bot_schedulers.get(task.get('game_id', ''))
            if scheduler:
                scheduler.handle_schedule(task)
        return result

    def step(self) -> bool:
        """跑一个到点的计时器（机器人动作 / 倒数 / 一拍动画）；队列空了返回 False。"""
        if not _CollectTimer.queue:
            return False
        fn, args, delay = _CollectTimer.queue.pop(0)
        self.now[0] += delay
        fn(*args)
        return True

    def pump(self, limit: int = 5000) -> None:
        steps = 0
        while self.step():
            steps += 1
            assert steps < limit, '调度次数异常'

    def start(self) -> None:
        self.command('create', json.dumps({'innings': self.innings})
                     if self.innings else '')
        self.room.clock = lambda: self.now[0]
        self.command('bot')
        self.command('start')
        self.pump()
        assert self.room is not None and self.room.state == 'playing'


def test_full_game_runs_three_innings_without_stalling(monkeypatch):
    random.seed(4)
    match = _BotMatch(monkeypatch)
    engine, scheduler, human = match.engine, match.scheduler, match.human
    command, pump = match.command, match.pump
    match.start()
    for _ in range(4000):
        room = engine.get_player_room(human)
        if room is None or room.phase == 'finished':
            break
        owner = room.decision_owner()
        if room.armed and room.fielding_player() == human:
            # 倒数完：人当投手就走指令路径把球投出去（顺带把投打动画拍起来）
            command('release')
            pump()
            continue
        if room.is_bot(owner):
            assert _CollectTimer.queue, '机器人回合没有后续调度（卡死）'
            pump()
            continue
        if owner == human:
            if room.phase == 'call':
                # 出牌阶段：交自己那一张牌（守方投球、攻方打击），对面由机器人自己交
                if room.fielding_player() == human:
                    bot = scheduler._bot
                    if bot._pick_shift(room) != 'standard':
                        command('shift', bot._pick_shift(room))
                    call = bot._pick_pitch(room)
                    command('pitch', f'{call.pitch_type} {call.band} '
                                     f'{call.effort} {call.hold}')
                else:
                    call = scheduler._bot._pick_swing(room)
                    command('swing',
                            f'{call.guess} {call.swing} {call.steal}')
            elif room.phase == 'tag':
                command('run', 'stop' if room.outs >= 2 else 'go')
            pump()
            continue
        if room.phase == 'flight':
            flight = room.flight
            if room.fielding_player() == human:
                command('field', 'right'
                        if flight.fielder.pos < flight.estimate() else 'left')
                command('jump')
            elif room.bases:
                command('run', 'go')
            pump()
            continue
        if room.phase == 'ground':
            ground = room.ground
            if room.fielding_player() == human:
                if not room.at_ball():
                    command('field', 'right'
                            if ground.fielder.pos < ground.ball else 'left')
                else:
                    options = room.throw_options()
                    command('throw', options[0].base)
            pump()
            continue
        if room.phase in ('delivery', 'throw'):
            pump()
            continue
        raise AssertionError(f'未知阶段 {room.phase}')

    room = engine.get_player_room(human)
    assert room is not None
    assert room.phase == 'finished', f'对局未结束: {room.phase}'
    assert room.innings == DEFAULT_INNINGS
    assert sum(room.score.values()) >= 0
    assert room.winner in ('', human, 'Bot_1')


def _play_a_game_through_menus(monkeypatch, innings: int | None = None):
    """真人只按上下左右和回车打完一场对机器人的比赛：返回操作区亮过哪几种盘、这场比赛的现场。"""
    from client.games.baseball import controls as ctl

    match = _BotMatch(monkeypatch, innings)
    match.start()
    client = _Client()
    acted_kinds: set[str] = set()

    def play() -> bool:
        """照着操作区按一次键；没有亮着的按钮就返回 False。"""
        ui = client.ui
        controls = ui.controls
        if ui.waiting or controls.mode != ctl.MODE_ACT:
            return False
        acted_kinds.add(controls.kind)
        if controls.kind in (ctl.KIND_PITCH, ctl.KIND_SWING):
            while client.labels[client.ui.controls.cursor] != '确定':
                client.press('down')                # 交互状态每次按键都会换新对象
            client.press('enter', 'enter')
        elif controls.kind in (ctl.KIND_RELEASE, ctl.KIND_HIT):
            client.press('enter')
        elif controls.kind == ctl.KIND_FLIGHT:
            client.press('enter')                 # 回车＝起跳
        elif controls.kind == ctl.KIND_GROUND_MOVE:
            ground = ui.board.ground
            want = 'right' if ground.fielder.pos < ground.ball else 'left'
            if controls.move != want:             # 一次挪一个键，方向对了就不再动
                client.press(want)
        elif controls.kind == ctl.KIND_GROUND_THROW:
            client.press('left', 'enter')         # 最近的垒
        else:
            client.press('left')                  # 跑垒键：领跑者多跑一个垒
        return True

    for _ in range(20000):
        room = match.room
        if room.phase == 'finished':
            break
        data = client.update(room, match.human)
        assert data['room_state'] == 'playing', data['room_state']
        acted = play()
        for text in client.sent:
            name, _, arg = text.removeprefix('/').partition(' ')
            match.command(name, arg)
        client.sent.clear()
        if not match.step() and not acted:
            raise AssertionError(
                f'卡住：阶段 {room.phase}，操作区 {client.ui.controls.kind}'
                f'/{client.ui.controls.mode}')
    assert match.room.phase == 'finished'
    return acted_kinds, match


def test_a_retreating_runner_keeps_his_place_on_the_line_when_he_turns():
    """调头那一刻，画面上的跑者不瞬移：离二垒多远，回头后还是离二垒那么远。"""
    client = _Client()
    room = _room()
    room.bases = [2]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    fielder = room.fielding_player()
    room.set_run_order('go')
    for _ in range(3):
        room._advance_runners()
    client.update(room, fielder)
    runners = client.state.game_interaction.snapshot('baseball')['runner_at']
    forward = runners['2>3']

    room.set_run_order('back')
    client.update(room, fielder)
    runners = client.state.game_interaction.snapshot('baseball')['runner_at']
    assert '2>3' not in runners
    assert 1 - runners['3>2'] == pytest.approx(forward)


def test_a_human_can_finish_a_game_using_only_the_menus(monkeypatch):
    """玩家视角：只按上下左右和回车，一场比赛从头打到尾。

    每个需要人动手的阶段，操作区里都有亮着的按钮；按下去发出的指令服务端一条都不拒收；
    人不动手的阶段（预告 / 等对手）也不会把比赛卡死。机器人和球路是随机的，
    所以打到每一种操作盘都亮过为止（最多 8 场）。
    """
    from client.games.baseball import controls as ctl

    every_kind = {
        ctl.KIND_PITCH, ctl.KIND_SWING, ctl.KIND_RELEASE, ctl.KIND_HIT,
        ctl.KIND_FLIGHT, ctl.KIND_GROUND_MOVE, ctl.KIND_GROUND_THROW,
        ctl.KIND_SEND}
    seen: set[str] = set()
    for _ in range(8):
        kinds, match = _play_a_game_through_menus(monkeypatch, innings=2)
        assert match.rejections == []
        seen |= kinds
        if every_kind <= seen:
            break
    # 触垒窗口（KIND_TAG）只在人踩垒等接杀时才出现：出现了也要走得通，但不强求每场都有
    assert every_kind <= seen, every_kind - seen
    assert seen - every_kind <= {ctl.KIND_TAG}


def test_everything_the_player_is_told_fits_the_one_line_notification_bar(
        monkeypatch):
    """真人这一边收到的每一条播报都是一行、放得进上方通知栏；最后留下的是结算结论。

    顺带验证「局数在创建房间时定」从创建到结算一路生效：2 局的对局奖励是 3 局的 2/3。
    """
    import re

    from server.games.baseball.room import LOG_COLS, _cols

    _kinds, match = _play_a_game_through_menus(monkeypatch, innings=2)
    assert match.room.total_innings == 2
    texts = [message['text'] for message in match.received
             if message['type'] == 'game']
    assert len(texts) > 20
    for text in texts:
        assert '\n' not in text and _cols(text) <= LOG_COLS, text
    conclusion = re.fullmatch(
        r'(获胜|落败|平手) (\d+)-(\d+) 经验\+(\d+) 金币\+(\d+)( 段位[+-]\d+)?',
        texts[-1])
    assert conclusion, texts[-1]
    # 2 局 ＝ 3 局基准的 2/3：赢 100 / 平 60 / 输 40 经验
    assert int(conclusion.group(4)) == {
        '获胜': 100, '平手': 60, '落败': 40}[conclusion.group(1)]
    first, second = int(conclusion.group(2)), int(conclusion.group(3))
    assert {'获胜': first > second, '落败': first < second,
            '平手': first == second}[conclusion.group(1)]    # 比分先写自己的，读起来和结论一致
    assert any(text.startswith('客 ') for text in texts)       # 战报里的逐局比分


def test_tick_tail_mutations_hold_the_lobby_lock(monkeypatch):
    """契约：Timer 回调里的状态变更与分发也必须持锁（不能只锁前半截）。

    回归的是"with lobby._lock 只包住推进、结算/收尾在锁外跑"那版实现。
    """
    monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
    monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())

    class SpyLock:
        """记录当前是否被持有（本项目 lobby._lock 是 RLock，语义一致）。"""

        def __init__(self):
            self.locked = False
            self._inner = threading.RLock()

        def __enter__(self):
            self._inner.acquire()
            self.locked = True

        def __exit__(self, *exc):
            self.locked = False
            self._inner.release()

    server = chat_server_module.ChatServer()
    lobby = server.lobby_engine
    engine = lobby._ensure_engine('baseball')
    scheduler = server.bot_schedulers['baseball']
    spy = SpyLock()
    lobby._lock = spy

    room = engine.room_class('r-lock', ['alice', 'bob'], None)
    engine._rooms['r-lock'] = room
    room.start()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'inside', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'standard'))
    _through_countdown(room)
    for _ in range(rules.delivery_frames() - 1):
        room.delivery_step()
    from server.games.baseball import engine as engine_module

    chain = engine_module._TickChain(room.next_tick())
    scheduler._chains['r-lock'] = chain

    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        type(engine), '_tick_result',
        lambda self, *a, **k: seen.append(('tick_result', spy.locked)) or {})
    monkeypatch.setattr(
        server, 'dispatch_game_result',
        lambda result, *a, **k: seen.append(('dispatch', spy.locked)))

    scheduler._fire('r-lock', chain)                 # 最后一帧：推进、收尾、分发
    assert seen == [('tick_result', True), ('dispatch', True)], seen


def test_leaving_a_match_asks_for_confirmation_only_once(monkeypatch):
    """返回 / 退出时的确认点「是」就直接放弃，不再弹第二次确认（用户 2026-11-15 反馈）。"""
    match = _BotMatch(monkeypatch)
    match.start()
    room = match.room

    for leave in (match.engine.handle_back, match.engine.handle_quit):
        menu = leave(match.lobby, match.human, match.data)['send_to_caller'][0]
        yes = next(item for item in menu['items'] if item.get('label') == '是')
        name, _, arg = yes['command'].removeprefix('/').partition(' ')
        result = match.command(name, arg)

        assert all(message.get('type') != 'select_menu'
                   for message in result.get('send_to_caller', []))
        assert room.state == 'waiting'
        match.start()
        room = match.room


def test_forfeit_aborts_the_match_and_pays_nobody(monkeypatch):
    """放弃＝中止比赛回等待室、不发奖励（和 UNO / Ludo 同一语义）。"""
    from server.msg_types import COMMANDS_UPDATE, GAME, ROOM_UPDATE

    monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
    monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())

    random.seed(7)
    server = chat_server_module.ChatServer()
    lobby = server.lobby_engine
    engine = lobby._ensure_engine('baseball')
    players = {}
    for name in ('humanA', 'humanB'):
        data = get_default_user_template(name=name, password_hash='x')
        data.pop('password_hash', None)
        lobby.register_player(name, data)
        lobby.set_player_location(name, 'baseball')
        players[name] = data
    exp_before = {n: d.get('exp', 0) for n, d in players.items()}
    gold_before = {n: d.get('gold', 0) for n, d in players.items()}

    def command(name: str, key: str, arg: str = '') -> dict:
        return engine.handle_command(lobby, name, players[name], key, arg)

    command('humanA', 'create')
    room = engine.get_player_room('humanA')
    command('humanB', 'join', room.room_id)
    command('humanB', 'ready')
    command('humanA', 'start')
    assert room.state == 'playing'

    result = command('humanA', 'forfeit', 'yes')
    assert room.state == 'waiting'             # 回等待室，不是 finished
    assert room.winner == ''
    assert not room._settled_players           # 没走结算
    for name in players:
        assert players[name].get('exp', 0) == exp_before[name]
        assert players[name].get('gold', 0) == gold_before[name]
    assert result['send_to_caller'][0]['text'] == 'humanA 放弃比赛'
    other = result['send_to_players']['humanB']
    kinds = [item['type'] for item in other]
    assert GAME in kinds and ROOM_UPDATE in kinds and COMMANDS_UPDATE in kinds


def test_delivery_hides_the_pitch_type_and_the_result_until_the_last_frame():
    """投打动画期间：打者看不到球种、双方都看不到结果，最后一帧才揭晓。"""
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('slider', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('slider', 'power', 'normal'))
    _through_countdown(room)
    assert room.phase == 'delivery'

    for _ in range(rules.delivery_frames() - 1):
        room.delivery_step()
        for viewer in (batter, pitcher):
            data = room.get_game_data(viewer=viewer)
            assert data['history'] == []                # 谁都没看到结果
            # 球种只在投手自己手里：下发的投打动画里没有任何球种信息
            assert set(data['delivery']) == {'stage', 'frame', 'frames',
                                             'swung'}

    room.delivery_step()                                # 最后一帧揭晓
    assert room.delivery is None
    for viewer in (batter, pitcher):
        data = room.get_game_data(viewer=viewer)
        assert len(data['history']) == 1
        assert data['history'][-1]['result_label']


def test_disconnect_ends_the_match_without_a_winner_or_rewards(monkeypatch):
    """断线＝中止：比赛结束、不判胜负、双方不发奖励（和 UNO / Ludo 一致）。"""
    from server.msg_types import GAME, ROOM_UPDATE

    monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
    monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())

    random.seed(9)
    server = chat_server_module.ChatServer()
    lobby = server.lobby_engine
    engine = lobby._ensure_engine('baseball')
    players = {}
    for name in ('humanA', 'humanB'):
        data = get_default_user_template(name=name, password_hash='x')
        data.pop('password_hash', None)
        lobby.register_player(name, data)
        lobby.set_player_location(name, 'baseball')
        players[name] = data

    def command(name: str, key: str, arg: str = '') -> dict:
        return engine.handle_command(lobby, name, players[name], key, arg)

    command('humanA', 'create')
    room = engine.get_player_room('humanA')
    command('humanB', 'join', room.room_id)
    command('humanB', 'ready')
    command('humanA', 'start')
    exp_before = {n: d.get('exp', 0) for n, d in players.items()}

    results = engine._match_disconnect(lobby, room, 'humanB')
    assert room.state == 'finished'
    assert room.winner == ''                   # 不判胜负
    assert not room._settled_players           # 没走结算
    for name in players:
        assert players[name].get('exp', 0) == exp_before[name]
    kinds = [item['type'] for item in results[0]['send_to_players']['humanA']]
    assert GAME in kinds and ROOM_UPDATE in kinds
    assert engine.get_player_room('humanA') is None    # 房间已清理


def test_start_puts_both_players_into_the_pitch_phase(monkeypatch):
    """两名真人开局：进入投球阶段，守方是决策者，双方都能拿到棋盘。"""
    from server.msg_types import ROOM_UPDATE

    monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
    monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())

    server = chat_server_module.ChatServer()
    lobby = server.lobby_engine
    engine = lobby._ensure_engine('baseball')
    players = {}
    for name in ('humanA', 'humanB'):
        data = get_default_user_template(name=name, password_hash='x')
        data.pop('password_hash', None)
        lobby.register_player(name, data)
        lobby.set_player_location(name, 'baseball')
        players[name] = data

    engine.handle_command(lobby, 'humanA', players['humanA'], 'create', '')
    room = engine.get_player_room('humanA')
    assert room is not None and room.state == 'waiting'

    engine.handle_command(
        lobby, 'humanB', players['humanB'], 'join', room.room_id)
    engine.handle_command(lobby, 'humanB', players['humanB'], 'ready', '')
    start = engine.handle_command(lobby, 'humanA', players['humanA'],
                                  'start', '')
    room = engine.get_player_room('humanA')
    assert room.state == 'playing'
    assert room.phase == 'call'
    assert room.decision_owner() == room.fielding_player()

    owner = room.decision_owner()
    messages = (start['send_to_caller'] if owner == 'humanA'
                else start['send_to_players'][owner])
    kinds = [message['type'] for message in messages]
    assert ROOM_UPDATE in kinds
    board = next(m['room_data'] for m in messages
                 if m['type'] == ROOM_UPDATE)
    assert board['phase'] == 'call'
    assert board['viewer_side'] == 'fielding'
    assert board['shift'] == 'standard'


@pytest.mark.parametrize('shift', list(rules.SHIFTS))
def test_every_shift_is_playable(shift):
    room = _room()
    ok, _ = room.set_shift(room.fielding_player(), shift)
    assert ok
    assert room.phase == 'call'
    assert room.get_game_data()['shift'] == shift


def test_forced_bases_only_chain_from_first():
    """被迫进垒：只有从一垒连成一串的人必须跑，剩下的可以待命。"""
    assert rules.forced_bases([1]) == {1}
    assert rules.forced_bases([1, 2, 3]) == {1, 2, 3}
    assert rules.forced_bases([3]) == set()
    assert rules.forced_bases([1, 3]) == {1}     # 二垒空着，三垒没人挤

    room = _room()
    room.bases = [1, 3]
    room._begin_flight(rules.HitBall(kind='line', landing=10, shown=10,
                                     ticks=9, tick_ms=600))
    running = {runner.origin: not runner.settled
               for runner in room.runners}
    assert running == {0: True, 1: True, 3: True}    # 击出后默认全体前进：三垒待命的人也起跑
    room.set_run_order('stop')
    running = {runner.origin: not runner.settled
               for runner in room.runners}
    assert running == {0: True, 1: True, 3: False}   # 叫停：被挤着的打者与一垒跑者照跑，三垒留下


def _steal_room(bases: list[int], scope: str) -> BaseballRoom:
    """打者交牌时排了盗垒、投手已投出这一球（投打动画里起跑的人已经在跑）。"""
    room = _room()
    room.bases = list(bases)
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                           steal=scope))
    _through_countdown(room)
    return room


def test_steal_resolves_when_the_pitch_is_not_hit():
    """盗垒在投球结果出来时结算：成功上垒、失败封杀（三垒成功即得分）。"""
    room = _steal_room([1], 'lead')
    assert room.steal == 'lead'
    assert [runner.at for runner in room.runners] == [1]

    room.rng = random.Random(1)
    room._resolve_steal('no')
    assert room.steal == ''
    assert room.runners == []                    # 动画用的条目要清掉
    if room.outs:
        assert room.bases == [1]                 # 被抓：留在原来的垒
        assert any('盗垒失败 触杀 二垒 一垒跑者 1出局' in line for line in room.log)
    else:
        assert room.bases == [2]                 # 成功：上二垒
        assert any('盗垒成功 一垒跑者上二垒' in line for line in room.log)


def test_the_steal_is_hidden_until_the_pitch_is_thrown():
    """盗垒也是出牌：对手在投手投出这一球之前，数据里和棋盘上都看不到它（2026-10-17 实测泄密）。"""
    room = _room()
    room.bases = [1]
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                           steal='all'))
    for viewer in (pitcher, batter):
        data = room.get_game_data(viewer=viewer)
        assert data['runners'] == []              # 没有任何"起跑"的痕迹
        assert 'steal' not in data
    assert room.steal == ''                       # 服务端也要到开投才生效
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    _through_countdown(room)
    assert room.steal == 'all'
    assert room.get_game_data(viewer=pitcher)['runners']   # 开投之后人人看得见


def test_a_steal_without_runners_is_ignored():
    """垒上没人：没有盗垒可排，交上来的盗垒一律按「保持」处理。"""
    room = _room()
    batter = room.batting_player()
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                           steal='all'))
    assert room.pending[batter].steal == 'hold'


def test_a_pickoff_without_runners_is_ignored():
    """垒上没人：「牵制跑者」没有对象，交上来的牵制一律按「不牵制」处理；有人才算数。"""
    room = _room()
    pitcher = room.fielding_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal',
                                            hold='yes'))
    assert room.pending[pitcher].hold == 'no'

    occupied = _room()
    occupied.bases = [1]
    occupied.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal',
                                                hold='yes'))
    assert occupied.pending[pitcher].hold == 'yes'


def test_the_waiting_room_serves_the_table_not_the_playing_board():
    """还没开打的房间：下发的是桌面数据（人、准备、机器人），不是一份空的棋盘。"""
    room = BaseballEngine().room_class('r-wait', ['alice'], None)
    data = room.get_game_data(viewer='alice')
    assert data['room_state'] == 'waiting'
    assert data['players'] == ['alice']
    assert 'phase' not in data and 'runners' not in data


def test_every_tick_sends_the_lines_it_wrote():
    """拍内写下的播报（落地 / 接杀 / 出局…）要随这一拍发给双方，不能被清掉却没人看到。"""
    engine, room = _engine_with_room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=2, tick_ms=100))
    room._drain()                                # 击出那句已经单独发过
    while room.phase == 'flight':
        room.flight_step()
    written = '\n'.join(room.log)
    assert written
    result = engine._tick_result(Mock(), room)
    for viewer in room.players:
        texts = [message['text']
                 for message in result['send_to_players'][viewer]
                 if message['type'] == 'game']
        assert texts == [written]
    assert room.log == []


def test_a_stealer_keeps_his_new_base_when_the_ball_is_hit():
    """盗垒的人在投打动画里已经跑到了下一个垒：球被打进场内，他不会被拉回原来的垒。"""
    room = _steal_room([1], 'lead')
    while room.delivery.stage == rules.DELIVERY_PITCH:
        room.delivery_step()
    room._carry_steal()
    assert room.bases == [2] and room.runners == []
    assert room.log == ['盗垒成功 一垒跑者上二垒']
    room._begin_flight(rules.HitBall(kind='fly', landing=8, shown=8,
                                     ticks=4, tick_ms=560))
    stealer = next(runner for runner in room.runners if not runner.batter)
    assert stealer.origin == stealer.at == 2      # 从二垒起算，不是一垒
    assert not stealer.forced                     # 一垒空了：打者挤不到他


def test_a_stealer_who_reaches_home_scores_even_if_the_ball_is_hit():
    room = _steal_room([3], 'lead')
    batter = room.batting_player()
    room._carry_steal()
    assert room.bases == [] and room.score[batter] == 1
    assert room.log[0].startswith('盗垒成功 三垒跑者得分')


def test_stealing_home_scores_a_run():
    room = _room()
    batter = room.batting_player()
    for seed in range(20):
        room.rng = random.Random(seed)
        room.bases = [3]
        room.outs = 0
        room.score[batter] = 0
        room.log.clear()
        room.steal = 'lead'
        room._resolve_steal('no')
        assert room.steal == ''
        assert room.bases == []                  # 三垒的人不是得分就是出局
        if room.outs == 0:
            assert room.score[batter] == 1       # 盗本垒成功＝直接得分
            assert '盗垒成功 三垒跑者得分' in ''.join(room.log)
            return
        assert room.outs == 1                    # 被抓＝触杀出局
        assert '盗垒失败 触杀 本垒 三垒跑者 1出局' in ''.join(room.log)
    raise AssertionError('20 次都没试出盗本垒成功')


def test_the_pitch_call_never_leaks_and_is_never_echoed(monkeypatch):
    """两个人玩：球种/区域/力度是打者要猜的——不给对手，也不再回显给自己。"""
    monkeypatch.setattr(chat_server_module, 'ChatLogManager', Mock)
    monkeypatch.setattr(chat_server_module, 'DMLogManager', Mock)
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())

    server = chat_server_module.ChatServer()
    lobby = server.lobby_engine
    engine = lobby._ensure_engine('baseball')
    players = {}
    for name in ('humanA', 'humanB'):
        data = get_default_user_template(name=name, password_hash='x')
        data.pop('password_hash', None)
        lobby.register_player(name, data)
        lobby.set_player_location(name, 'baseball')
        players[name] = data

    engine.handle_command(lobby, 'humanA', players['humanA'], 'create', '')
    room = engine.get_player_room('humanA')
    engine.handle_command(
        lobby, 'humanB', players['humanB'], 'join', room.room_id)
    engine.handle_command(lobby, 'humanB', players['humanB'], 'ready', '')
    engine.handle_command(lobby, 'humanA', players['humanA'], 'start', '')
    room = engine.get_player_room('humanA')
    pitcher = room.fielding_player()
    batter = room.batting_player()

    result = engine.handle_command(lobby, pitcher, players[pitcher], 'pitch',
                                  'slider inside full no')
    pitcher_board = next(m['room_data']
                         for m in result['send_to_players'][pitcher]
                         if m['type'] == 'room_update')
    other = result['send_to_players'][batter]
    # 球种/区域/力度**哪里都不回显**：对手不该知道（保密契约），自己刚选的东西
    # 也没必要再显示一遍（用户 2026-10-16 定：右上角不再回显投球内容）
    assert not pitcher_board.get('message')
    assert result['send_to_caller'] == []
    assert [m for m in result['send_to_players'].get(pitcher, [])
            if m['type'] == 'game'] == []
    assert [m for m in other if m['type'] == 'game'] == []   # 打者没收到
    board = next(m['room_data'] for m in other
                 if m['type'] == 'room_update')
    assert not board.get('message')                 # 也没写进棋盘的消息
    assert board['viewer_side'] == 'batting'
    assert room.phase == 'call'  # 交牌后还在出牌阶段，但打者照样该他打击


def test_batter_can_order_the_runners_while_the_ball_is_in_the_air():
    """飞行中下令：垒上的人先动，可能被双杀；捡球阶段还能继续下令，指令一直有效到你改。"""
    room = _room()
    room.bases = [2]
    room._begin_flight(rules.HitBall(kind='fly', landing=11, shown=11,
                                     ticks=10, tick_ms=700))
    held = next(r for r in room.runners if not r.batter)
    assert held.settled is False and held.to == 3   # 击出后默认全体前进：二垒的人也起跑了
    assert room.order == 'go'
    assert room.set_run_order('stop') is True       # 还没离垒：叫停就留在原地
    assert held.settled is True and room.order == 'stop'
    assert room.set_run_order('go') is True
    assert held.settled is False and held.to == 3   # 前进：他再次起跑
    assert room.set_run_order('sprint') is False    # 不认识的指令
    assert room.phase == 'flight'                   # 下令不推进阶段

    # 捡球阶段照样可以下令
    room = _room()
    room.bases = [1]
    _ground_play(room, rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700), 7)
    assert room.set_run_order('go') is True
    assert room.get_game_data()['run_order'] == 'go'


def test_batter_gets_the_three_run_buttons_after_the_hit():
    """击出后操作区是撤回 / 停止 / 前进三个键；光标落到哪个，跑者就照那个跑。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700))
    batter = room.batting_player()
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '撤回', '停止', '前进']                      # 打者自己也能多跑
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '前进'   # 击出后默认全体前进
    handler.on_nav('left', ctx)                 # 光标挪到哪个按钮，哪个按钮生效
    assert sent[-1] == '/run stop'

    # 垒上还有人时也一样给这三个
    room.bases = [2]
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '撤回', '停止', '前进']


def test_the_cursor_starts_on_the_order_the_server_is_holding():
    """重连之类的情况：服务端的指令是「停止」，光标就该停在「停止」上，别让画面说谎。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, _sent = _handler_ctx(state)
    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700))
    room.set_run_order('stop')
    handler.on_room_update(_room_data(room, room.batting_player()), ctx)
    snapshot = state.game_interaction.snapshot('baseball')
    assert snapshot['menu'][snapshot['cursor']]['label'] == '停止'


def test_run_buttons_fit_on_the_minimum_board_width():
    from client.games.baseball.controls import (
        MODE_ACT, Controls, Plan, _pad, _run_row)
    from client.games.baseball.panel import render_controls

    controls = Controls(plan=Plan('send', _pad(_run_row()), MODE_ACT),
                        items=_pad(_run_row()), cursor=1)
    rendered = _dump(render_controls(controls, 40), 40)
    lines = rendered.splitlines()
    assert len(lines) == 3
    assert all(cell_width(line) <= 40 for line in lines)


def test_the_tag_window_gives_the_batter_the_same_run_buttons():
    """高飞被接杀后的触垒窗口：攻方还是那三个按钮，前进＝冒险多进一个垒。"""
    from client.games.baseball.controls import MODE_PREVIEW, Form, plan_for
    from client.games.baseball.diamond import situation_label
    from client.games.baseball.view import Board
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _tag_room([3])
    batter = room.batting_player()
    data = _room_data(room, batter)
    assert situation_label(Board.parse(data)) == '触垒'
    assert data['run_order'] == 'stop'              # 接杀后指令回到「停止」，光标也在那

    handler.on_room_update(data, ctx)
    assert [item['label'] for item in snapshot()['menu']] == [
        '撤回', '停止', '前进']
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '停止'
    handler.on_nav('right', ctx)
    assert sent[-1] == '/run go'

    # 守方在触垒窗口没有按键可发（球由防守方自动传出去）：只摆下一球的表单当预告
    fielding = Board.parse(_room_data(room, room.fielding_player()))
    assert situation_label(fielding) == '等触垒'
    assert plan_for(fielding, Form.initial(fielding)).mode == MODE_PREVIEW


def test_steal_is_part_of_the_swing_and_runs_during_the_delivery():
    """出牌阶段的盗垒：打击表单里那一项和别的设置一样留在本地，
    确定时随 /swing 一起交；起跑的人在投打动画里跑。"""
    client = _Client()
    room = _room()
    room.bases = [1]
    batter = room.batting_player()
    client.update(room, batter)
    assert client.labels == ['预判', '挥棒', '盗垒', '确定']

    def snapshot() -> dict:
        return client.state.game_interaction.snapshot('baseball')

    assert snapshot()['menu'][2]['desc'] == '保持'      # 还没排盗垒
    client.press('down', 'down', 'enter')               # 一路挪到盗垒
    assert client.labels == ['领跑者盗垒', '保持', '全体盗垒', '返回']
    client.press('up', 'enter')                         # 领跑者盗垒
    assert client.sent == []                            # 选值不发指令，留到确定
    assert snapshot()['menu'][2]['desc'] == '领跑者盗垒'

    client.press('down', 'enter', 'enter')              # 确定 → 是
    assert client.sent[-1] == '/swing four_seam standard lead'

    # 服务端收下之后，投球动画期间跑者就在动
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                           steal='lead'))
    _through_countdown(room)
    progress = []
    while room.phase == 'delivery':
        data = _room_data(room, batter)
        if data['runners']:
            progress.append(data['runners'][0]['progress'])
        room.delivery_step()
    assert progress == sorted(progress) and progress[-1] > progress[0]


def test_pressing_hit_sets_the_timing_from_the_frame():
    """击球是实时反应：时机不看选项，看你按下去的那一帧（早按＝提前）。"""
    assert rules.swing_timing(0, 9) == 'early'
    assert rules.swing_timing(4, 9) == 'early'      # 前 45% 内 = 提前
    assert rules.swing_timing(5, 9) == 'normal'
    assert rules.swing_timing(7, 9) == 'normal'
    assert rules.swing_timing(8, 9) == 'late'
    assert rules.swing_timing(9, 9) == 'late'
    # 挥棒段里按：球已经到本垒，一律算「延后」（用户 2026-10-15 定）
    assert rules.swing_timing(1, 3, rules.DELIVERY_SWING) == 'late'

    def press(frame: float, claim=None) -> str:
        """服务端推进到第 frame 帧后按下击球；claim＝客户端上报的帧（缺省＝如实报）。"""
        room = _room()
        fielder, batter = room.fielding_player(), room.batting_player()
        room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
        room.set_swing(batter, rules.SwingCall('four_seam', 'standard',
                                               'normal'))
        _through_countdown(room)
        while (room.delivery.stage == rules.DELIVERY_PITCH
                and room.delivery.frame < frame):
            room.delivery_step()
        room.swing_now(batter, frame if claim is None else claim)
        return room.exchange.swing.timing

    # 如实按：第几帧按就是哪一档
    assert press(1) == 'early'
    assert press(5) == 'normal'
    assert press(8) == 'late'
    # 挥棒段里按：球已经到本垒，一律算「延后」
    assert press(9) == 'late'

    # 延迟补偿（2026-10-17 定）：服务端已到第 8 帧，客户端如实报自己看到的第 7 帧
    # （差 1 帧，在 280ms 容差内）→ 按第 7 帧算，不吃网络延迟的亏
    assert press(8, claim=7) == 'normal'
    # 伪造：服务端在第 8 帧却谎报第 0 帧想拿「提前」→ 最多往回认 2 帧 → 第 6 帧＝正常
    assert press(8, claim=0) == 'normal'
    # 伪造：服务端在第 2 帧却谎报第 9 帧想拿「延后」→ 报未来按服务端帧 → 提前
    assert press(2, claim=9) == 'early'
    # 乱报：不是有限数字（NaN / 解析失败传 None）→ 一律按服务端当前帧算
    assert press(5, claim=float('nan')) == 'normal'

    room = _room()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    for _ in range(5):
        room.delivery_step()
    room.swing_now(room.batting_player(), None)     # 客户端不报帧＝按服务端帧
    assert room.exchange.swing.timing == 'normal'

    # 按晚了 / 按早了都只是"没对上"，不是打不到球
    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('changeup', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('changeup', 'standard', 'normal'))
    _through_countdown(room)
    room.delivery_step()
    assert room.swing_now(batter, 3)[0] is True     # 变速球本来就该晚点按
    assert room.swing_now(batter, 4)[0] is False    # 一球只能按一次


def test_the_hit_key_stays_for_the_whole_delivery():
    """击球键在投打过程里一直留着：球到了本垒（挥棒段）也不消失（用户 2026-10-15 要求）。

    消失过就会误触旁边的选项；留着的时候按下算「延后」，所以那一下照旧是挥棒。
    """
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == ['击球']
    assert snapshot()['title'] == ''                # 不是"准备"那种预告态

    while room.delivery.stage == rules.DELIVERY_PITCH:
        room.delivery_step()
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == ['击球']
    assert snapshot()['my_turn'] is True            # 挥棒段里也真能按
    handler.on_nav('enter', ctx)                    # 这一按＝延后
    assert sent[-1].startswith('/hit ')
    assert [item['label'] for item in snapshot()['menu']] != ['击球']


def test_the_hit_key_is_released_as_soon_as_the_batter_confirms():
    """交完打击牌就立刻出「击球」键；球没投出来之前按不动、也不给提示（用户 2026-10-15 定）。

    键在"等对手交牌"和"倒数 3→2→1"期间都要看得见（玩家先站好位），但开投那一刻才亮、
    才能按；提前按回车什么都不发生（不发货、不弹提示）。
    """
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    def keys() -> list[str]:
        return [item['label'] for item in snapshot()['menu']]

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()

    # ① 还没交牌：打者那边是打击表单
    handler.on_room_update(_room_data(room, batter), ctx)
    assert snapshot()['root_kind'] == 'swing'
    assert '击球' not in keys()

    # ② 我交完牌（对手还没交）：击球键已经出来，但是暗的、按不动
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    handler.on_room_update(_room_data(room, batter), ctx)
    assert keys() == ['击球']
    assert snapshot()['root_kind'] == 'hit'
    assert snapshot()['my_turn'] is False
    handler.on_nav('enter', ctx)
    assert sent == []                               # 提前按：不发货

    # ③ 对手也交了，倒数 3→2→1：键还在，还是暗的，按了照样什么都不发生
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    assert room.countdown == rules.COUNTDOWN_SECONDS
    while room.countdown:
        handler.on_room_update(_room_data(room, batter), ctx)
        assert keys() == ['击球']
        assert snapshot()['my_turn'] is False
        handler.on_nav('enter', ctx)
        assert sent == []                           # 倒数期间按：不发货、无提示
        room.countdown_tick()

    # ④ 倒数数完：球在投手手上，键还是暗的、还是什么都不发生
    handler.on_room_update(_room_data(room, batter), ctx)
    assert room.armed is True                       # 等投手按「投球」
    assert room.phase == 'call'
    assert snapshot()['root_kind'] == 'hit'
    assert snapshot()['my_turn'] is False
    handler.on_nav('enter', ctx)
    assert sent == []

    # ⑤ 投手把球投出来：同一个键亮起来，按下去就是这一球的挥棒
    assert room.release_pitch(room.fielding_player())
    handler.on_room_update(_room_data(room, batter), ctx)
    assert room.phase == 'delivery'
    assert snapshot()['root_kind'] == 'hit'         # 键没换位置，只是"能按了"
    assert snapshot()['my_turn'] is True
    handler.on_nav('enter', ctx)
    assert sent[-1].startswith('/hit ')
    assert 0.0 <= float(sent[-1].split()[1]) <= rules.PITCH_ANIM_FRAMES


def test_every_phase_leaves_the_operation_panel_alive():
    """全部阶段都不许出现"空面板"或"菜单在但整块灭掉"（用户 2026-10-15 定）。

    规则：操作区永远有按钮；能按的时候是亮的（`my_turn`），
    还不能按的时候是**预告**（`preview`）——能翻菜单、能预选取值，只是发不出指令。
    例外只有一个：打者的「击球」键在球没投出来之前按不动，也**不算预告**（用户定：不给提示）。
    """
    from client.state import ModuleStateManager

    def panel(room, viewer) -> dict:
        state = ModuleStateManager()
        handler = get_handler('baseball')
        ctx, _sent = _handler_ctx(state)
        handler.on_room_update(_room_data(room, viewer), ctx)
        return state.game_interaction.snapshot('baseball')

    def check(name: str, room) -> None:
        for viewer in (room.fielding_player(), room.batting_player()):
            snap = panel(room, viewer)
            side = '守' if viewer == room.fielding_player() else '攻'
            assert snap['menu'], (name, side, '空面板')
            alive = snap['my_turn'] or snap['preview']
            if not alive:                   # 只有打者的击球键允许"亮着但不能按"
                assert [item['label'] for item in snap['menu']] == ['击球']
                assert room.phase != 'delivery'      # 投球段里它必须能按
            else:
                assert snap['menu'][0]['label'] not in ('', None)

    # 出牌 / 交牌后等对手 / 倒数 / 投打两段 / 捡球 / 传球 / 触垒
    room = _room()
    room.bases = [1]
    fielder, batter = room.fielding_player(), room.batting_player()
    check('出牌', room)
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    check('守方交完牌', room)
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
    check('两边交完', room)
    _through_countdown(room)
    check('开投', room)
    room.delivery_step()
    check('投球段', room)

    flying = _room()
    flying.bases = [1]
    flying._begin_flight(rules.HitBall(kind='line', landing=9, shown=9,
                                       ticks=5, tick_ms=100))
    check('击出飞行', flying)

    ground = _room()
    ground.bases = [1]
    _ground_play(ground, rules.HitBall(kind='ground', landing=7, shown=7,
                                       ticks=3, tick_ms=100), 7)
    check('捡球', ground)
    ground.ground.cell = ground.ground.ball
    ground.start_throw('二垒')
    check('传球途中', ground)
    check('触垒窗口', _tag_room([1]))


def test_the_pitcher_gets_the_pitch_key_as_soon_as_he_confirms():
    """守方交完牌立刻拿到「投球」键：等对手、等倒数期间都在，但球没到手上之前按不动。

    倒数数完（`armed`）键才亮，按下就是 `/release`（只是"投出去"的确认，不看时机）。
    投打动画期间他的面板换回投球表单当预告，能翻能预选（下一球先挑好）。
    """
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()

    # ① 还没交牌：投球表单，能改
    handler.on_room_update(_room_data(room, pitcher), ctx)
    assert snapshot()['root_kind'] == 'pitch'
    assert snapshot()['my_turn'] is True

    # ② 交完牌（等对手 / 等倒数）：换成「投球」键，暗的，按了什么都不发
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    handler.on_room_update(_room_data(room, pitcher), ctx)
    assert [item['label'] for item in snapshot()['menu']] == ['投球']
    assert snapshot()['root_kind'] == 'release'
    assert snapshot()['my_turn'] is False
    handler.on_nav('enter', ctx)
    assert sent == []

    # ③ 对手也交了、倒数跑完：球在手上（armed）→ 键亮起来
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    while room.countdown:
        handler.on_room_update(_room_data(room, pitcher), ctx)
        assert [item['label'] for item in snapshot()['menu']] == ['投球']
        assert snapshot()['my_turn'] is False
        handler.on_nav('enter', ctx)
        assert sent == []                       # 倒数期间按：不发货
        room.countdown_tick()
    handler.on_room_update(_room_data(room, pitcher), ctx)
    assert room.armed is True
    assert snapshot()['my_turn'] is True        # 键没换位置，只是能按了
    handler.on_nav('enter', ctx)
    assert sent[-1] == '/release'

    # ④ 投出去之后（投打动画里）：守方那边先摆跑位盘（暗着），手先放好；
    # 接球三键要等球真被打出来才加入（没球可接时不摆，2026-10-17 定）
    room.release_pitch(pitcher)
    handler.on_room_update(_room_data(room, pitcher), ctx)
    assert room.phase == 'delivery'
    assert snapshot()['root_kind'] == 'flight'
    assert [item['label'] for item in snapshot()['menu']] == [
        '左移', '停止', '右移']
    assert snapshot()['preview'] is True
    assert snapshot()['title'] == ''
    cursor = snapshot()['cursor']
    handler.on_nav('right', ctx)
    assert snapshot()['cursor'] != cursor
    assert sent[-1] == '/release'               # 预告里挪光标不发指令


def test_the_tag_window_shows_the_next_pitch_form():
    """触垒窗口守方没有动作：下一球的投球表单先摆出来当预告，不留空面板。"""
    from client.state import ModuleStateManager

    room = _tag_room([1])
    assert room.phase == 'tag'
    fielding = room.fielding_player()
    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, _sent = _handler_ctx(state)
    handler.on_room_update(_room_data(room, fielding), ctx)
    snap = state.game_interaction.snapshot('baseball')
    assert [item['label'] for item in snap['menu']][-1] == '确定'
    assert snap['my_turn'] is False and snap['preview'] is True

    state2 = ModuleStateManager()
    handler2 = get_handler('baseball')
    ctx2, _sent2 = _handler_ctx(state2)
    handler2.on_room_update(_room_data(room, room.batting_player()), ctx2)
    snap2 = state2.game_interaction.snapshot('baseball')
    assert [item['label'] for item in snap2['menu']] == [
        '撤回', '停止', '前进']
    assert snap2['my_turn'] is True


def test_the_result_symbol_appears_only_at_the_last_frame():
    """保密契约：本垒结果符号（叉/方向箭头）只在最后一帧出现。

    回归的是"按下击球就把挥空的叉写进 `last_ball`"那版实现——那个字段每帧随视图
    下发，写早了对手就提前看到结果（审计 2026-10-15 报的阻断项）。
    """
    from client.config import NF_CROSS

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    room.last_ball = ''
    _through_countdown(room)
    assert room.last_ball == ''                 # 新的一球：符号复位
    while room.phase == 'delivery':
        if room.delivery.stage == 'pitch':
            room.swing_now(batter, 9)
        room.delivery_step()
        for viewer in (fielder, batter):
            if room.phase == 'delivery':
                assert room.last_ball == '', (viewer, room.last_ball)
                data = _room_data(room, viewer)
                assert data['last_ball'] == ''
                assert NF_CROSS not in data['last_ball']
    assert room.last_ball in ('', 'whiff', 'fly', 'line', 'ground')
    # 打者不按也一样：放过去（判好坏球）不在动画期间写符号
    room2 = _room()
    f2, b2 = room2.fielding_player(), room2.batting_player()
    room2.set_pitch(f2, rules.PitchCall('changeup', 'edge', 'normal'))
    room2.set_swing(b2, rules.SwingCall('changeup', 'standard', 'normal'))
    _through_countdown(room2)
    while room2.phase == 'delivery':
        room2.delivery_step()
        if room2.phase == 'delivery':
            assert room2.last_ball == ''
    assert room2.last_ball == ''                # 放过去：空心圆，没有叉


def test_not_pressing_lets_the_pitch_go_by():
    """打者交的是"要挥"，但没按击球 = 这一球放过去（判好坏球，不是挥空）。"""
    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    for _ in range(rules.delivery_frames() + 2):
        if room.phase != 'delivery':
            break
        room.delivery_step()
    assert room.history[-1].swing.swing == 'take'
    assert room.history[-1].result.kind in ('strike', 'ball')


def test_the_verdict_word_is_coloured_by_result():
    """判定字按结果分色：安全/保送＝绿、出局/三振/双杀＝红、全垒打＝金（用户 2026-10-16 定）。"""
    from client.config import (COLOR_GAME_BALL, COLOR_GAME_MARK,
                               COLOR_GAME_READY)
    from client.games.baseball.diamond import live_slot_segments
    from client.games.baseball.view import Board

    def verdict_style(verdict: str) -> str:
        room = _room()
        room.verdict = verdict
        board = Board.parse(_room_data(room, room.fielding_player()))
        judged = live_slot_segments(board)[0]
        return judged[0][1]

    for verdict in ('safe', 'walk'):
        assert verdict_style(verdict) == f'bold {COLOR_GAME_READY}'
    for verdict in ('catch_out', 'force_out', 'tag_out', 'strikeout',
                    'double_play'):
        assert verdict_style(verdict) == f'bold {COLOR_GAME_BALL}'
    assert verdict_style('homerun') == f'bold {COLOR_GAME_MARK}'


def test_every_out_is_named_by_how_it_happened():
    """出局按方式写清：接杀 / 封杀 / 触杀（用户 2026-10-21 要求显示这些字样），棋盘判定槽和结果行都写。"""
    from client.games.baseball.diamond import live_slot_segments
    from client.games.baseball.view import Board

    def slot(verdict: str) -> str:
        room = _room()
        room.verdict = verdict
        board = Board.parse(_room_data(room, room.fielding_player()))
        return live_slot_segments(board)[0][0][0]

    assert slot('catch_out') == '接杀 FLY OUT'
    assert slot('force_out') == '封杀 FORCE OUT'
    assert slot('tag_out') == '触杀 TAG OUT'

    forced = _room()
    forced.bases = [1]
    _ground_play(forced, rules.HitBall(kind='ground', landing=8, shown=8,
                                       ticks=4, tick_ms=560), 8)
    forced.ground.cell = forced.ground.ball
    forced.start_throw('二垒')
    while forced.phase == 'throw':
        forced.throw_tick()
    assert forced.verdict in ('force_out', 'double_play')
    if forced.phase == 'ground':
        forced.hold_ball()
    assert any('封杀 二垒 一垒跑者' in line for line in forced.log)   # 出局方式写在出局那一行里

    tagged = _tag_room([3])                    # 接杀
    assert tagged.verdict == 'catch_out'
    tagged.set_run_order('stop')               # 不冒险：这一拍结束
    assert any(line.startswith('接杀 ') for line in tagged.log)


def test_the_form_remembers_the_last_choices_inside_a_match():
    """上一球选过的取值留着（用户 2026-10-16：每次都记住上次的选项）。

    新的一球不重置球种 / 区域 / 力度 / 跑者，也不重置打者的预判与挥棒；
    跑者那一项一开始就有默认值（回归"跑者显示空"那版实现）。
    """
    client = _Client()
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    client.update(room, pitcher)
    first = dict(vars(client.ui.form))
    assert first['hold'] == 'no'                 # 跑者项有默认值（不再显示空）

    # 换球种，交牌、打完这一球
    client.press('down', 'enter')                # 布阵 → 球种
    client.press('down', 'down', 'enter')        # 选到第三个球种
    chosen = client.ui.form.pitch_type
    assert chosen != first['pitch_type']
    room.set_pitch(pitcher, rules.PitchCall(chosen, 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
        client.update(room, pitcher)
    assert client.ui.form.pitch_type == chosen   # 记住了
    assert client.ui.form.hold == first['hold']


def test_the_ball_flight_is_slowed_down_but_the_tick_counts_are_the_same():
    """慢放只改每拍时长、不改拍数：判定与平衡完全不动。

    投打与其余动态阶段都慢 2 倍（70→140ms、560→1120ms）；
    传球拍数照旧按 `TICK_SECONDS` 算，所以同样的距离还是同样的拍数。
    """
    from math import ceil

    assert rules.ANIM_FRAME_MS == 140
    assert rules.TICK_MS == int(rules.TICK_SECONDS * 1000) * rules.PHASE_SLOWDOWN
    assert rules.PHASE_SLOWDOWN == 2
    assert rules.TICK_MS == 1120
    assert [info['cell_ms'] for info in rules.BALL_KINDS.values()] == [
        1760, 1920, 2240,
    ]
    assert rules.GROUND_MAX_TICKS * rules.TICK_MS == 22_400
    assert rules.runner_ticks(5) == 7
    assert 7 * rules.TICK_MS == 7_840
    assert [7 * info['cell_ms'] for info in rules.BALL_KINDS.values()] == [
        12_320, 13_440, 15_680,
    ]
    speed = rules.THROW_SPEED_BASE + 6 * rules.THROW_SPEED_PER_ARM
    assert rules.throw_ticks(40.0, 6) == ceil(40.0 / speed / rules.TICK_SECONDS)
    # 球型：拍数＝跨几格（不变），只有每格毫秒数被拉长
    span, cell_ms = rules.flight_steps('fly', 12)
    assert span == rules.FIELD_CELLS - rules.FIELD_START
    assert cell_ms == rules.BALL_KINDS['fly']['cell_ms']
    for info in rules.BALL_KINDS.values():
        assert info['cell_ms'] % rules.PHASE_SLOWDOWN == 0


def test_player_help_uses_current_ball_flight_times():
    from pathlib import Path

    help_path = Path(rules.__file__).resolve().parent / 'data' / 'help.txt'
    help_text = help_path.read_text(encoding='utf-8')
    labels = {'ground': '滚地', 'line': '平飞', 'fly': '高飞'}

    for kind, label in labels.items():
        seconds = rules.BALL_KINDS[kind]['cell_ms'] / 1000
        assert f'{label}每格 {seconds:.2f} 秒' in help_text


def test_player_help_uses_clear_runner_labels_without_renderer_internals():
    from pathlib import Path

    help_path = Path(rules.__file__).resolve().parent / 'data' / 'help.txt'
    help_text = help_path.read_text(encoding='utf-8')

    assert '撤回 / 停止 / 前进' in help_text
    assert '领跑者盗垒 / 保持 / 全体盗垒' in help_text
    assert 'ProgressTrack' not in help_text
    assert 'PitchTrack' not in help_text
    assert 'ThrowTrack' not in help_text


def test_the_slow_flight_glides_for_exactly_one_tick():
    """慢放之后球仍然逐格往前走：滑动按拍长走，整段正好是一拍，不提前停也不拖过下一拍。"""
    from client.protocol.animation import FRAME_SECONDS, Animator

    tick = rules.BALL_KINDS['fly']['cell_ms'] / 1000
    anim = Animator()
    anim.snap('ball', 1.0)
    anim.glide('ball', 2.0, tick, 10.0)
    frames, now, seen = 0, 10.0, []
    while anim.moving:
        now += FRAME_SECONDS
        anim.advance(now)
        frames += 1
        seen.append(anim.values['ball'])
    assert seen == sorted(seen) and seen[-1] == 2.0
    assert abs((now - 10.0) - tick) < FRAME_SECONDS
    assert 29 <= frames / tick <= 31


def test_handler_offers_the_hit_button_and_switches_to_running():
    """投球段给打者一个「击球」按钮；按下的瞬间按钮换成跑垒布局。"""
    from client.state import ModuleStateManager

    state = ModuleStateManager()
    handler = get_handler('baseball')
    ctx, sent = _handler_ctx(state)

    def snapshot() -> dict:
        return state.game_interaction.snapshot('baseball')

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    handler.on_room_update(_room_data(room, batter), ctx)
    while snapshot()['menu'][snapshot()['cursor']]['label'] != '确定':
        handler.on_nav('down', ctx)
    handler.on_nav('enter', ctx)
    handler.on_nav('enter', ctx)                    # 是 → 交打击牌
    assert sent[-1].startswith('/swing four_seam')

    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    _through_countdown(room)
    assert room.phase == 'delivery'
    handler.on_room_update(_room_data(room, batter), ctx)
    assert [item['label'] for item in snapshot()['menu']] == ['击球']
    assert snapshot()['my_turn'] is True            # 看球按键＝真能操作，不是预告
    handler.on_nav('enter', ctx)                    # 球到了，按！
    assert sent[-1].startswith('/hit ')
    frame = float(sent[-1].split()[1])
    assert 0.0 <= frame <= rules.PITCH_ANIM_FRAMES
    # 按下的瞬间按钮就换成跑垒布局，默认停在「前进」（击出后默认全体前进）
    assert [item['label'] for item in snapshot()['menu']] == [
        '撤回', '停止', '前进']
    assert snapshot()['menu'][snapshot()['cursor']]['label'] == '前进'


def test_holding_the_runner_cuts_the_room_steal_roll():
    """守方反制真的接到判定上：同一个骰子，盯住跑者就从"上垒"变"被抓"。"""
    speed = 5
    plain = rules.steal_chance(speed, 'no')
    held = rules.steal_chance(speed, 'yes')
    assert held < plain
    roll = (plain + held) / 2                     # 落在两个阈值之间

    def run(hold: str) -> tuple[int, bool]:
        game = _room()
        game.bases = [1]
        game.attributes[game.batting_player()].fielder.speed = speed
        game.steal = 'lead'
        game.rng = random.Random(0)
        game.rng.random = lambda: roll            # 固定骰子，只看阈值
        game._resolve_steal(hold)
        return game.outs, 2 in game.bases

    outs_plain, advanced_plain = run('no')
    outs_held, advanced_held = run('yes')
    assert (outs_plain, advanced_plain) == (0, True)
    assert (outs_held, advanced_held) == (1, False)


def _board(**changes):
    """一份棋盘视图（守方视角的开局局面），再按需要改几个字段。"""
    from dataclasses import replace

    from client.games.baseball.view import Board

    room = _room()
    board = Board.parse(_room_data(room, room.fielding_player()))
    return replace(board, **changes)


def test_runners_are_drawn_between_the_bases():
    from client.config import NF_ARROW_D, NF_ARROW_R, NF_ARROW_U
    from client.games.baseball.diamond import Infield
    from client.games.baseball.view import Runner
    from client.protocol.animation import Animator

    def square(runners: list, ratios: dict, bases=()) -> list:
        anim = Animator()
        for key, value in ratios.items():
            anim.snap(f'runner:{key}', value)
        board = _board(runners=tuple(runners), bases=tuple(bases))
        return [row.plain for row in Infield(board, anim, 26, 17).render()]

    def column(row: str, glyph: str) -> int:
        """这个字形在第几列（终端列数，不是字符下标）。"""
        return _visual(row[:row.index(glyph)])

    plain = square([Runner(1, 2, 3, 6, False, False, False),
                    Runner(3, 4, 1, 6, False, False, False)],
                   {'1>2': 0.5, '3>4': 0.15})
    assert column(plain[7], NF_ARROW_U) == 25        # 一垒→二垒：沿右边向上
    assert column(plain[3], NF_ARROW_D) == 2         # 三垒→本垒：沿左边向下

    moving = square([Runner(0, 1, 5, 6, False, False, False)], {'0>1': 0.8})
    assert column(moving[12], NF_ARROW_R) == 20      # 本垒→一垒：下边向右

    # 站稳的跑者只占角上的标记，不再画在线上
    settled = square([Runner(2, 3, 4, 6, True, False, False)], {'2>3': 0.6},
                     bases=[2])
    assert all(NF_ARROW_U not in row for row in settled)

    # 方框里落了图标也不许把边框顶出去：每一行的终端宽度都必须一样
    assert len({_visual(row) for row in settled}) == 1


def test_homerun_ball_is_drawn_at_the_wall_on_the_right():
    """本垒打墙在外野线（从左到右）的右端：球飞到头就停在墙上那几格。"""
    from client.config import NF_ONLINE
    from client.games.baseball.diamond import _WALL_GLYPH, FieldTrack
    from client.games.baseball.view import Board
    from client.protocol.animation import Animator

    room = _room()
    fielder = room.fielding_player()
    ticks, tick_ms = rules.flight_steps('fly', rules.FIELD_CELLS)
    room._begin_flight(rules.HitBall(kind='fly', landing=rules.FIELD_CELLS,
                                     shown=rules.FIELD_CELLS, ticks=ticks,
                                     tick_ms=tick_ms, homerun=True))
    while not room.flight.done:
        room.flight_step()
    data = room.get_game_data(viewer=fielder)
    assert data['flight']['homerun'] is True
    assert room.phase == 'call'                # 全垒打直接进下一个打席

    anim = Animator()
    anim.snap('ball', float(rules.FIELD_CELLS))
    row = FieldTrack(Board.parse(data), anim, 46).render()
    assert row.plain.count(NF_ONLINE) == 1
    tail = row.plain.rstrip()
    assert tail.rstrip(_WALL_GLYPH).endswith(NF_ONLINE)   # 球压在墙的第一格上
    assert tail.count(_WALL_GLYPH) >= 4


def test_wall_stays_empty_when_the_hit_stays_in_the_park():
    from client.config import NF_ONLINE
    from client.games.baseball.diamond import _WALL_GLYPH, FieldTrack
    from client.games.baseball.view import Board
    from client.protocol.animation import Animator

    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=9, tick_ms=700))
    room.flight.ball = 10
    data = room.get_game_data(viewer=room.fielding_player())
    anim = Animator()
    anim.snap('ball', 10.0)
    row = FieldTrack(Board.parse(data), anim, 46).render()
    assert row.plain.rstrip().endswith(_WALL_GLYPH)  # 墙还在，只是球没过去
    assert NF_ONLINE in row.plain[:row.plain.index(_WALL_GLYPH)]


def test_status_uses_mlb_notation():
    """局面页按美职棒：局数写成「当前局/总局数」带上下三角、球数写成 坏球-好球、值右对齐。"""
    from client.config import NF_CARET_D, NF_CARET_U

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    room.half = 'bottom'
    room.innings = 2
    room.balls, room.strikes = 3, 2
    data = _room_data(room, room.fielding_player())
    first = _dump(renderer.render_status(data).pages[0][1], 38)
    assert f'2/{DEFAULT_INNINGS} {NF_CARET_D}' in first
    assert '3-2' in first

    room.half = 'top'
    room.balls, room.strikes = 0, 1
    data = _room_data(room, room.fielding_player())
    first = _dump(renderer.render_status(data).pages[0][1], 38)
    assert f'2/{DEFAULT_INNINGS} {NF_CARET_U}' in first
    assert '0-1' in first          # 先坏球后好球
    # 两列各贴一边、左右缝各 2 格：有值的那几行都贴到同一条右边缘（34 = 36 - 2）
    widths = {cell_width(row.rstrip()) for row in first.split('\n')
              if row.strip()}
    assert max(widths) == 38 - 4 + 2, widths
    # 阶段行只写"在干什么"，不写球种 / 帧号（自己刚选的东西不再回显）
    assert '四缝线' not in first and '/9' not in first


def test_scout_page_labels_offense_defense_and_result():
    """侦察页每一球写清谁打、怎么打、结果是什么；一整行放得下，不再被「…」截断。"""
    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    room.delivery_step()
    room.swing_now(batter, 5)                   # 打者按时按下击球
    while room.phase == 'delivery':
        room.delivery_step()
    data = _room_data(room, fielder)
    second = _dump(renderer.render_status(data).pages[2][1], 38)
    assert '1 守' in second
    assert f'攻 {batter}' in second
    assert '→' in second                       # 打出去/挥空的结果
    assert '四缝线速球' in second
    assert '标准挥击' in second and '好球带边缘' in second and '标准' in second
    assert '…' not in second                   # 长球种 + 区域 + 力度也放得下
    # 结果一定是五个结局之一：好球 / 坏球（选球收棒也会记坏球）/ 挥空 / 界外 / 击中
    assert any(label in second for label in rules.RESULT_LABELS.values())


def test_scout_page_keeps_who_batted_after_the_sides_switch():
    """攻守交换之后，老的几球还写着当时的打者（以前一律写成当前的打者）。"""
    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    first_batter = room.batting_player()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(first_batter, rules.SwingCall('four_seam', 'take'))
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
    room.outs = 3
    room._change_half()
    assert room.batting_player() != first_batter
    text = _dump(renderer.render_status(
        _room_data(room, room.fielding_player())).pages[2][1], 38)
    assert f'攻 {first_batter}' in text


def test_line_score_page_shows_every_inning_and_marks_the_unplayed_ones():
    """比分页：逐局得分 + 合计，客队在前；没打到的半局写 -，打完了下半局没打写 X。"""
    renderer = RENDERER_REGISTRY['baseball']
    room = BaseballRoom('r-line', ['alice', 'bob'], {'innings': 5})
    room.start()
    away, home = room.sides['away'], room.sides['home']
    room._add_runs(2)                           # 客队第 1 局上半得 2 分
    room.outs = 3
    room._change_half()
    page = _dump(renderer.render_status(
        _room_data(room, away)).pages[1][1], 38)
    rows = [row for row in page.split('\n') if row.strip()]
    assert rows[0].split()[:6] == ['局', '1', '2', '3', '4', '5']
    assert rows[0].rstrip().endswith('合计')
    assert rows[1].split()[:4] == [away, '2', '-', '-']        # 客队：第 1 局 2 分
    assert rows[2].split()[:3] == [home, '0', '-']             # 主队：下半局已经开始
    assert all(cell_width(row.rstrip()) <= 38 - 2 for row in rows)

    room.innings, room.half = 5, 'top'
    room.score[away], room.score[home] = 0, 3
    room._change_half()                          # 末局上半结束主队领先：下半局不必打
    assert room.state == 'finished'
    page = _dump(renderer.render_status(
        _room_data(room, away)).pages[1][1], 38)
    assert page.split('\n')[2].split()[5] == 'X'               # 主队末局写 X


def test_attributes_page_uses_plain_words():
    """属性页用完整短词，不用单字缩写。"""
    renderer = RENDERER_REGISTRY['baseball']
    data = _room_data(_room(), _room().fielding_player())
    third = _dump(renderer.render_status(data).pages[3][1], 38)
    for word in ('我方投手', '控球', '球速', '变化', '我方打者', '力量',
                 '接触', '选球', '我方野手', '速度', '守备', '臂力', '布阵'):
        assert word in third, word


def test_wall_is_the_same_height_in_every_phase():
    """本垒打墙只在外野线上，而且任何阶段都在（不会忽高忽低）。"""
    from client.games.baseball.diamond import _WALL_GLYPH

    renderer = RENDERER_REGISTRY['baseball']
    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()

    def wall_cells() -> list[int]:
        rows = _dump(renderer.render_board(
            _room_data(room, fielder), None, 46, 19)['board'], 46)
        return [line.count(_WALL_GLYPH) for line in _track_lines(rows)]

    call = wall_cells()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    room.delivery_step()
    delivery = wall_cells()
    assert call == delivery, (call, delivery)
    assert call[0] == 0 and call[2] == 0        # 投打行、传球行都没有墙
    assert call[1] > 0                          # 墙只在外野线上


def test_the_three_rows_bars_line_up_and_the_wall_sits_outside():
    """三条行的左右竖线同列，墙和倒数都写在右竖线外面的留白里（用户 2026-10-15 定）。"""
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    room = _room()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'take', 'normal'))
    data = _room_data(room, room.fielding_player())
    assert data['countdown'] == rules.COUNTDOWN_SECONDS
    for width in (46, 58, 78, 88, 98):
        rows = diamond.track_rows(Board.parse(data), None, width)
        lines = [row.plain for row in rows]
        # 竖线位置按**终端列数**算（图标的字符索引和列号不是一回事）
        left = {_visual(line[:line.index(diamond._BAR_GLYPH)])
                for line in lines}
        right = {_visual(line[:line.rindex(diamond._BAR_GLYPH)])
                 for line in lines}
        assert len(left) == 1 and len(right) == 1, (width, left, right)
        # 倒数写在投打行右竖线右边、贴棋盘右边缘；墙写在最下面那条外野行上
        pitch, field = lines[0], lines[1]
        assert pitch.endswith(str(rules.COUNTDOWN_SECONDS))
        assert field.rstrip().endswith(diamond._WALL_GLYPH)
        assert diamond._WALL_GLYPH not in pitch
        # 两条竖线之间那段（格点）在三条行上等宽
        spans = {_visual(line[:line.rindex(diamond._BAR_GLYPH)])
                 - _visual(line[:line.index(diamond._BAR_GLYPH)])
                 for line in lines}
        assert len(spans) == 1, (width, spans)


def test_the_home_mark_never_touches_the_left_bar():
    """本垒结果符号和左竖线之间必须留一格：贴上去就是"相切"（用户 2026-10-15 报）。"""
    from client.games.baseball import diamond

    board = _board()
    for width in (46, 58, 78, 88, 98):
        for row in diamond.track_rows(board, None, width):
            line = row.plain
            bar = line.index(diamond._BAR_GLYPH)
            assert line[bar - 1] == ' ', (width, line)


def test_the_square_keeps_one_width_with_chinese_slots():
    """内野正方形里的中文槽（判定 / 动作）不许把行顶宽：每一行宽度必须一样。

    回归"槽里的汉字占两列、只算一格"那版实现——它让槽所在的那一行比别人宽 2 到 N 列
    （用户 2026-10-15 报的"垒包中间的文字导致没有对齐"）。
    """
    from client.games.baseball.diamond import Infield

    boards = (_board(bases=(1, 3)),
              _board(bases=(1, 3), countdown=3),
              _board(bases=(1, 3), verdict='safe'),
              _board(bases=(1, 3), countdown=2, verdict='homerun',
                     side='batting', phase='tag'))
    for board in boards:
        rows = [row.plain for row in Infield(board, None, 47, 27).render()]
        assert len({cell_width(row) for row in rows}) == 1, rows
        inside = [row for row in rows if row.count('│') == 2]
        assert len({_visual(text[:text.index('│')]) for text in inside}) == 1
        assert len({_visual(text[:text.rindex('│')]) for text in inside}) == 1


def test_the_throw_row_keeps_its_width_with_a_base_name():
    """传球行的目标垒名是两个汉字（4 列）：要占满格点，不许把这一行顶宽。

    回归"垒名只占一格"那版实现：整行比别的行宽 3 列，右竖线跟着跑（用户 2026-10-15 报）。
    """
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    room = _room()
    room.bases = [1]
    hit = rules.HitBall(kind='ground', landing=7, shown=7, ticks=4, tick_ms=100)
    _ground_play(room, hit, 7)
    room.ground.cell = room.ground.ball
    room.start_throw('二垒')
    board = Board.parse(_room_data(room, room.fielding_player()))
    for width in (46, 58, 78, 88, 98):
        rows = diamond.track_rows(board, None, width)
        lines = [row.plain for row in rows]
        assert {cell_width(line) for line in lines} == {width}, (width, lines)
        left = {_visual(line[:line.index(diamond._BAR_GLYPH)])
                for line in lines}
        right = {_visual(line[:line.rindex(diamond._BAR_GLYPH)])
                 for line in lines}
        assert len(left) == 1 and len(right) == 1, (width, left, right)


def test_the_two_lanes_are_always_on_the_board():
    """三条固定行永远在：任何阶段都是三条等宽的行，画面不变形。"""
    from client.config import (NF_CROSS, NF_HIT_FLAT, NF_HIT_HIGH,
                               NF_HIT_LOW, NF_OFFLINE, NF_USER)

    home_marks = (NF_OFFLINE, NF_CROSS, NF_HIT_HIGH, NF_HIT_FLAT, NF_HIT_LOW)
    from client.games.baseball.diamond import _WALL_GLYPH
    renderer = RENDERER_REGISTRY['baseball']
    width = 88

    def lanes(data: dict) -> list[str]:
        return [line for line in _dump(
            renderer.render_board(data, None, width, 19)['board'],
            width).split('\n')
            if line.lstrip().startswith(('投打', '外野', '传球'))]

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()

    states = {'call': _room_data(room, fielder)}
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    states['call'] = _room_data(room, fielder)      # 两边交完：还在 call，倒数开始
    assert states['call']['countdown'] == rules.COUNTDOWN_SECONDS
    _through_countdown(room)
    states['delivery'] = _room_data(room, fielder)
    flying = _room()
    flying.bases = [1]
    flying._begin_flight(rules.HitBall(kind='line', landing=9, shown=9,
                                       ticks=5, tick_ms=100))
    states['flight'] = _room_data(flying, flying.fielding_player())

    for phase, data in states.items():
        assert data['phase'] == phase, (phase, data['phase'])
        lines = lanes(data)
        assert len(lines) == 3, (phase, len(lines))
        # 三行等宽：行宽就是终端里的列数（字形一列，中日韩文字两列）
        def width_of(line: str) -> int:
            return cell_width(line)

        assert len({width_of(line) for line in lines}) == 1, (phase, lines)
        # 每行有自己的前缀，顺序是：投打 → 外野 → 传球；左边距和正方形一样
        stripped = [line.lstrip() for line in lines]
        assert stripped[0].startswith('投打') and stripped[1].startswith('外野')
        assert stripped[2].startswith('传球')
        assert len({len(line) - len(line.lstrip()) for line in lines}) == 1
        # 投打行：前缀后面就是本垒标记（空心圆/叉/方向箭头之一），不压格点
        assert any(mark in lines[0] for mark in home_marks)
        assert NF_USER not in lines[2], '不传球时不该在传球行摆人'
        # 本垒打墙只在最后的外野线上（用户 2026-10-15 定）
        assert _WALL_GLYPH in lines[1]
        assert _WALL_GLYPH not in lines[0] and _WALL_GLYPH not in lines[2]

    # 球飞出去之后：投打行前缀后面换成击出方向箭头（平飞＝右箭头）
    assert NF_HIT_FLAT in lanes(states['flight'])[0]
    assert {NF_HIT_FLAT, NF_HIT_HIGH, NF_HIT_LOW}      # 三个方向字形都在目录里


def test_the_three_rows_fill_the_board_exactly():
    """三条行铺满整块棋盘：前缀 + 结果符号一列 + 12 格 + 右端墙，一列不多不少。"""
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    for phase in ('call', 'delivery', 'flight', 'ground'):
        if phase == 'delivery':
            room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge',
                                                    'normal'))
            room.set_swing(batter, rules.SwingCall('four_seam', 'take',
                                                   'normal'))
            _through_countdown(room)
            room.delivery_step()
        elif phase == 'flight':
            room._begin_flight(rules.HitBall(kind='line', landing=9, shown=9,
                                             ticks=5, tick_ms=140))
        elif phase == 'ground':
            hit = rules.HitBall(kind='line', landing=8, shown=8,
                                ticks=4, tick_ms=140)
            room._begin_flight(hit)
            room._start_ground(hit, False, room.flight.fielder)
        board = Board.parse(_room_data(room, fielder))
        for width in (46, 58, 78, 88, 98):
            rows = diamond.track_rows(board, None, width)
            assert len(rows) == 3, (phase, width)
            widths = {cell_width(row.plain) for row in rows}
            assert widths == {width}, (phase, width, widths)
            indents = {len(row.plain) - len(row.plain.lstrip())
                       for row in rows}
            assert indents == {diamond.SQUARE_INDENT}, (phase, indents)
    assert '投打' in ' '.join(row.plain for row in
                              diamond.track_rows(board, None, 88))


def test_the_pitcher_stands_outside_the_right_bar_in_every_phase():
    """投手一直站在投打行右竖线外面（2026-10-21 用户要求：一直显示、站在线外），球道里没有他。"""
    from client.config import NF_USER
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    rooms = {'call': _room()}
    delivering = _room()
    delivering.set_pitch(delivering.fielding_player(),
                         rules.PitchCall('four_seam', 'edge', 'normal'))
    delivering.set_swing(delivering.batting_player(),
                         rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(delivering)
    delivering.delivery_step()
    rooms['pitch stage'] = delivering
    swinging = _room()
    swinging.set_pitch(swinging.fielding_player(),
                       rules.PitchCall('four_seam', 'edge', 'normal'))
    swinging.set_swing(swinging.batting_player(),
                       rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(swinging)
    while swinging.delivery.stage == rules.DELIVERY_PITCH:
        swinging.delivery_step()
    rooms['swing stage'] = swinging
    flying = _room()
    flying._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                       ticks=5, tick_ms=100))
    rooms['flight'] = flying
    grounded = _room()
    _ground_play(grounded, rules.HitBall(kind='ground', landing=7, shown=7,
                                         ticks=3, tick_ms=100), 7)
    rooms['ground'] = grounded

    for phase, room in rooms.items():
        board = Board.parse(_room_data(room, room.fielding_player()))
        for width in (46, 58, 78, 88, 98):
            track = diamond.PitchTrack(board, None, width)
            assert all(mark.glyph != NF_USER for mark in track.marks()), (
                phase, width)                          # 球道里没有投手
            line = track.render().plain
            inside, _bar, outside = line.rpartition('│')
            assert NF_USER not in inside, (phase, width)
            assert outside.index(NF_USER) == 1, (phase, width)   # 竖线外隔一格
            assert cell_width(line) == width, (phase, width)

    board = Board.parse(_room_data(rooms['call'], rooms['call'].fielding_player()))
    counting = _room()
    counting.set_pitch(counting.fielding_player(),
                       rules.PitchCall('four_seam', 'edge', 'normal'))
    counting.set_swing(counting.batting_player(),
                       rules.SwingCall('four_seam', 'standard', 'normal'))
    board = Board.parse(_room_data(counting, counting.fielding_player()))
    assert board.countdown > 0
    for width in (46, 88):
        line = diamond.PitchTrack(board, None, width).render().plain
        assert line.endswith(str(board.countdown)) and NF_USER in line   # 倒数仍贴右边缘


def test_every_ball_flight_bar_is_the_same_length():
    """契约：三条固定行（投打 / 传球 / 外野线）永远等长，且整盘高度不变。"""
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    room = _room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(fielder, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    room.delivery_step()

    throw_room = _room()
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)
    _ground_play(throw_room, hit, 8)
    throw_room.ground.cell = throw_room.ground.ball
    throw_room.start_throw('二垒')

    renderer = RENDERER_REGISTRY['baseball']
    for phase_data in (_room_data(room, fielder),
                       _room_data(throw_room, throw_room.fielding_player())):
        cells = int(phase_data['cells'])
        for width in (46, 58, 78, 88, 98):
            lines = [line for line in _dump(
                renderer.render_board(phase_data, None, width, 19)['board'],
                width).split('\n') if '外野' in line]
            lengths = {cell_width(line) for line in lines}
            assert len(lengths) == 1, (width, lengths)
            assert diamond.track_rows(Board.parse(phase_data), None, width)
            assert cells > 0


def test_the_ball_never_touches_a_dot_on_the_tracks():
    """插值滑动时球会落在两个格点之间：相邻的点必须让位，不许「球贴着点」（2026-10-17 报）。

    球和投手贴在一起不算问题：出手那几帧球本来就在投手手上。
    """
    from client.games.baseball.diamond import PitchTrack
    from client.games.baseball.view import Board
    from client.protocol.animation import Animator

    room = _room()
    room.set_pitch(room.fielding_player(),
                   rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(room.batting_player(),
                   rules.SwingCall('four_seam', 'standard', 'normal'))
    _through_countdown(room)
    board = Board.parse(_room_data(room, room.batting_player()))
    anim = Animator()
    for width in (46, 64, 80, 120):
        for tenth in range(0, 91):            # 投球段所有插值位置（0.0–9.0 帧）
            anim.snap('delivery', tenth / 10)
            row = PitchTrack(board, anim, width).render().plain
            assert f'{NF_ONLINE}·' not in row, (width, tenth, row)
            assert f'·{NF_ONLINE}' not in row, (width, tenth, row)


def test_the_pitch_track_marks_the_timing_zones_and_the_swing():
    """投打行上有三档时机的两条分界线；打者一按下击球，本垒处亮起挥棒标记（双方都看得到）。"""
    from client.config import NF_OFFLINE
    from client.games.baseball import diamond, style
    from client.games.baseball.view import Board

    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
    _through_countdown(room)
    head = ' ' * diamond.SQUARE_INDENT + '投打 '
    for width in (46, 58, 88, 98):
        board = Board.parse(_room_data(room, batter))
        track = diamond.PitchTrack(board, None, width)
        guides = track.guides()
        assert board.timing_cuts == (rules.SWING_EARLY_RATIO,
                                     rules.SWING_NORMAL_RATIO)
        assert len(guides) == 2
        assert guides == sorted(set(guides), reverse=True) and guides[-1] > 0
        line = track.render().plain
        assert line.count(diamond.GUIDE_GLYPH) == 2
        assert line.startswith(head + NF_OFFLINE)         # 还没按：空心圆

    room.swing_now(batter, 3)
    for viewer in (pitcher, batter):
        track = diamond.PitchTrack(Board.parse(_room_data(room, viewer)),
                                   None, 88)
        assert track.head().glyph == NF_ONLINE
        assert track.head().style == style.HIT
        assert track.render().plain.startswith(head + NF_ONLINE)

def test_every_command_the_client_can_send_is_one_the_server_accepts():
    """菜单→指令契约：任何阶段、任何一方的按钮发出的指令，表单每种取值拼出的完整指令，服务端都认。"""
    import itertools
    from dataclasses import replace

    from client.games.baseball.controls import Form
    from server.games.baseball.engine import (
        _PITCH_ARGS, _SWING_ARGS, _valid_args)

    arguments = {'run': rules.RUN_ORDERS, 'jump': (),
                 'throw': rules.BASE_POSITIONS, 'hold': ()}
    commands = set(BaseballEngine._COMMAND_MAP['playing'])

    delivering = _room()
    delivering.set_pitch(delivering.fielding_player(),
                         rules.PitchCall('four_seam', 'edge', 'normal'))
    delivering.set_swing(delivering.batting_player(),
                         rules.SwingCall('four_seam', 'standard'))
    _through_countdown(delivering)
    flying = _room()
    flying.bases = [1, 2]
    flying._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                       ticks=5, tick_ms=100))
    grounded = _room()
    grounded.bases = [1]
    _ground_play(grounded, rules.HitBall(kind='ground', landing=7, shown=7,
                                         ticks=3, tick_ms=100), 7)
    grounded.ground.cell = grounded.ground.ball
    scenarios = [_room(), delivering, flying, grounded, _tag_room([3])]
    scenarios[0].bases = [1]

    sent = set()
    for room in scenarios:
        for viewer in room.players:
            client = _Client()
            client.update(room, viewer)
            sent |= {item.command for item in client.ui.controls.items
                     if item.command}
    assert sent, '没有任何带指令的按钮可检查'
    for text in sent:
        name, *rest = text.removeprefix('/').split()
        assert name in commands, text
        if name in arguments:          # 按钮盘上的指令；表单的完整指令在下面逐一核对
            assert tuple(rest) == () or rest[0] in arguments[name], text

    board = _board(bases=(1,))               # 垒上有人：牵制与盗垒都是真选项
    assert {scope for scope, _ in board.values('steals')} == set(
        rules.RUN_SCOPES)
    form = Form.initial(board)
    for pitch_type, band, effort, hold in itertools.product(
            board.values('pitch_types'), board.values('bands'),
            board.values('efforts'), board.values('holds')):
        pitch = replace(form, pitch_type=pitch_type[0], band=band[0],
                        effort=effort[0], hold=hold[0])
        assert _valid_args(pitch.pitch_command(board).split()[1:],
                           _PITCH_ARGS), pitch
    for guess, swing, steal in itertools.product(
            board.values('pitch_types'), board.values('swings'),
            board.values('steals')):
        call = replace(form, guess=guess[0], swing=swing[0], steal=steal[0])
        assert _valid_args(call.swing_command(board).split()[1:],
                           _SWING_ARGS), call


def test_throw_flight_bar_advances_until_the_ball_arrives():
    """传球行上有飞行过程：球从守方一侧推进到目标垒包（右端写目标垒名）。"""
    from client.config import NF_ONLINE
    from client.games.baseball import diamond
    from client.games.baseball.view import Board
    from client.protocol.animation import Animator

    room = _room()
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)
    _ground_play(room, hit, 8)
    room.ground.cell = room.ground.ball
    assert room.start_throw('二垒') is True
    cells = rules.FIELD_CELLS

    def lane(tick_at: float | None = None) -> str:
        board = Board.parse(_room_data(room, room.fielding_player()))
        anim = Animator()
        if tick_at is not None:
            anim.snap('throw', tick_at)
        return diamond.ThrowTrack(board, anim, 88).render().plain

    start = lane(0.0).index(NF_ONLINE)
    end = lane(float(room.throw.ticks)).index(NF_ONLINE)
    assert start < end                          # 球一路飞过去，不是原地不动
    positions = [lane(float(tick)).index(NF_ONLINE)
                 for tick in range(room.throw.ticks + 1)]
    assert positions == sorted(positions)       # 只会往前走
    assert positions[-1] == end
    assert f'{room.throw.distance:.1f}' in lane()   # 右端写着这次传球的距离
    # 整条线＝这次传球的距离：球从最左一格出发、最后一拍落进最右一格
    # （不是走到一半就切阶段——用户 2026-10-16 报的"弄一半"）
    rendered = lane(float(room.throw.ticks))
    left_bar = rendered.index(diamond._BAR_GLYPH)
    right_bar = rendered.rindex(diamond._BAR_GLYPH)
    assert left_bar < start < right_bar
    # 终点落在**最后一格**里（不是走到一半就切阶段；也不是跑到竖线上）
    slot = diamond._field_cell(88, cells)
    assert left_bar + 1 + (cells - 1) * slot <= end < right_bar, (end, slot)

    # 棋盘在传球阶段确实画了这一行（传球行上有球和距离）
    board = _dump(RENDERER_REGISTRY['baseball'].render_board(
        _room_data(room, room.fielding_player()), None, 88, 19)['board'], 88)
    assert any(line.lstrip().startswith('传球') and NF_ONLINE in line
               and f'{room.throw.distance:.1f}' in line
               for line in board.split('\n'))


def test_the_throw_row_writes_the_target_and_the_distance_as_wide_as_fits():
    """传球行右边写「垒名 距离」：右侧留白放不下就先去掉垒名、再去掉单位，绝不顶宽这一行。"""
    from client.games.baseball import diamond
    from client.games.baseball.view import Board

    room = _room()
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)
    _ground_play(room, hit, 8)
    room.ground.cell = room.ground.ball
    room.start_throw('二垒')
    board = Board.parse(_room_data(room, room.fielding_player()))
    distance = f'{room.throw.distance:.1f}'
    expected = {46: f'二垒 {distance}米', 58: f'二垒 {distance}米',
                78: f'{distance}米', 88: distance, 98: f'二垒 {distance}米'}
    for width, text in expected.items():
        line = diamond.ThrowTrack(board, None, width).render().plain
        assert line.rstrip().endswith(text), (width, line)
        assert cell_width(line) == width, (width, cell_width(line))


def test_throw_to_a_forced_base_is_a_force_out_otherwise_a_tag_out():
    """真实棒球规则：被迫进垒被球先到＝封杀；自己多跑的＝触杀。"""
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)

    forced = _room()
    forced.bases = [1]                          # 一垒有人：打者把他挤到二垒
    _ground_play(forced, hit, 8)
    forced.ground.cell = forced.ground.ball
    assert forced.start_throw('二垒') is True
    while forced.phase == 'throw':
        forced.throw_tick()
    if forced.phase == 'ground':
        forced.hold_ball()
    assert forced.outs == 1
    assert any('封杀' in line for line in forced.log)
    assert any('封杀 二垒 一垒跑者' in line for line in forced.log)

    tagged = _room()
    tagged.bases = [2]                          # 二垒有人，没人挤他 → 不是被迫
    _ground_play(tagged, hit, 8)
    tagged.ground.cell = tagged.ground.ball
    assert tagged.set_run_order('go') is True    # 自己跑出去
    assert tagged.start_throw('三垒') is True
    while tagged.phase == 'throw':
        tagged.throw_tick()
    assert tagged.outs == 1
    assert any('触杀' in line for line in tagged.log)


def test_wall_sits_at_the_right_end_of_the_outfield_line():
    """外野 12 格从左到右铺开，墙紧跟在最后一格右边、一直铺到棋盘右边缘。"""
    from client.games.baseball.diamond import (
        _ROW_PREFIX_COLS, _field_cell, wall_span,
    )

    for width in (46, 58, 78, 88, 98):
        start, wall = wall_span(width, rules.FIELD_CELLS)
        assert wall >= 3, (width, wall)
        assert start + wall == width, (width, start, wall)
        assert _field_cell(width, rules.FIELD_CELLS) >= 2
    start, _ = wall_span(46, rules.FIELD_CELLS)
    assert start >= _ROW_PREFIX_COLS      # 前缀 + 结果符号那一列之后才是格点


# ── 地面连续双杀 / 高飞牺牲打 ──


def _tag_room(bases: list[int]) -> BaseballRoom:
    """造一个「高飞球被接杀、垒上有人」的场面：接杀后应该进触垒窗口。"""
    room = _room()
    hit = rules.HitBall(kind='fly', landing=8, shown=8, ticks=4, tick_ms=100,
                        quality=20)
    for _ in range(60):
        room.phase = 'call'
        room.outs = 0
        room.bases = list(bases)
        room._begin_flight(hit)
        room.set_run_order('stop')              # 三垒的人留在垒上，接杀后才有触垒窗口
        room.flight.cell = hit.landing
        room._land()
        if room.phase == 'tag':
            return room
    raise AssertionError('没能造出接杀（接杀概率不是 100%）')


def test_ground_double_play_throws_twice_on_the_same_play():
    """一垒有人打滚地球：先封杀二垒，球留在垒上再传一垒——同一拍两个出局。"""
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)
    room = _room()
    room.bases = [1]
    _ground_play(room, hit, 8)
    for runner in room.runners:
        runner.need = 99                        # 别让他们在测试里自己跑完
    room.ground.cell = room.ground.ball

    assert room.start_throw('二垒') is True
    while room.phase == 'throw':
        room.throw_tick()
    assert room.outs == 1
    assert any('封杀' in line for line in room.log)

    # 球停在二垒：不用再跑位，可以直接转传，能传的垒只有还有人被迫在跑的那个
    assert room.phase == 'ground'
    assert room.ground.base == '二垒'
    assert room.at_ball() is True
    assert [item.base for item in room.throw_options()] == ['一垒']

    assert room.start_throw('一垒') is True
    while room.phase == 'throw':
        room.throw_tick()
    assert room.outs == 2
    assert any('双杀' in line for line in room.log)
    assert room.phase == 'call'                # 这一拍结束，回到投球


def test_sacrifice_fly_scores_or_gets_thrown_out_at_the_plate():
    """高飞牺牲打：接杀后最前面的跑者可以冒险进垒，防守方马上把球传过去。"""
    scored = _tag_room([3])
    before = scored.score[scored.batting_player()]
    assert scored.set_run_order('go') is True
    assert scored.phase == 'throw'
    assert scored.throw.base == '本垒'
    assert scored.throw.distance > 0
    for runner in scored.runners:
        runner.need = 1                         # 他先到本垒
    while scored.phase == 'throw':
        scored.throw_tick()
    assert scored.score[scored.batting_player()] == before + 1
    assert scored.outs == 1                     # 只有接杀那一个出局
    assert scored.bases == []

    caught = _tag_room([3])
    assert caught.set_run_order('go') is True
    for runner in caught.runners:
        runner.need = 99                        # 球先到本垒
    while caught.phase == 'throw':
        caught.throw_tick()
    assert caught.outs == 2
    assert any('触杀' in line for line in caught.log)     # 不是被迫进垒


def test_the_batter_can_decline_the_tag_advance():
    """停止：没人冒险，跑者回原来的垒，这一拍结束。"""
    room = _tag_room([3])
    assert room.set_run_order('stop') is True
    assert room.phase == 'call'
    assert room.bases == [3]
    assert room.outs == 1
    assert not any('三垒' in line for line in room.log)    # 他没动：没有新事可记


def test_the_bot_always_answers_the_tag_window():
    """机器跑者必须给触垒窗口一个答复，否则这一拍没人推进（对局卡死）。"""
    from server.games.baseball.bot import BaseballBot

    room = _tag_room([3])
    BaseballBot.tag(room)
    assert room.phase != 'tag'


def test_the_bot_decides_once_per_hit_and_calls_off_the_ones_it_sent():
    from server.games.baseball.bot import BaseballBot

    hit = rules.HitBall(kind='fly', landing=11, shown=11, ticks=10,
                        tick_ms=700)

    def play(roll: float) -> BaseballRoom:
        room = _room()
        room.bases = [2]
        room.rng.random = lambda: roll
        room._begin_flight(hit)
        return room

    bot = BaseballBot()
    cautious = play(0.99)                           # 骰子不派人：第一拍就叫停，站着的人留在垒上
    runner = next(r for r in cautious.runners if not r.batter)
    assert runner.settled is False and cautious.order == 'go'
    bot.run(cautious)
    assert cautious.order == 'stop' and runner.settled is True

    bot = BaseballBot()                             # 机器人按房间号记「这次击球改过没有」
    bold = play(0.0)                                # 骰子派人：先让他们跑，一拍之后叫停
    runner = next(r for r in bold.runners if not r.batter)
    bot.run(bold)
    assert bold.order == 'go'
    bold._advance_runners()
    bot.run(bold)
    assert bold.order == 'stop'                     # 派出去一拍就叫停：到下一个垒就站住
    assert runner.settled is False and runner.to == 3
    bot.run(bold)
    assert bold.order == 'stop'                     # 同一次击球不再改主意


def test_the_bot_plans_a_press_frame_for_every_swing():
    """机器人排按键帧：三种挥棒都要排（它不主动放过去，放过去只属于真人玩家）。"""
    from server.games.baseball.bot import BaseballBot

    bot = BaseballBot()
    room = _room()
    batter = room.batting_player()
    for swing in rules.SWINGS:
        bot._press_frame.pop(batter, None)
        bot._plan_press(room, batter, rules.SwingCall('four_seam', swing))
        assert bot._press_frame[batter] > 0, swing
    assert room.pending == {}                       # 只排按键，不动交牌状态


def test_only_the_batting_bot_plans_a_press_frame():
    """交牌时排按键的只有打击方：投手那一次不该顺手改写打者的按键帧。"""
    from server.games.baseball.bot import BaseballBot

    bot = BaseballBot()
    room = _room()
    batter = room.batting_player()
    bot.submit(room, room.fielding_player())
    assert bot._press_frame == {}
    bot.submit(room, batter)
    assert list(bot._press_frame) == [batter]


def test_tag_window_is_a_decision_phase_not_a_timed_animation():
    """触垒窗口等攻方决定（不是定时动画）：它不排 tick，该动手的是打者。"""
    engine = BaseballEngine()
    room = _tag_room([3])
    assert room.decision_owner() == room.batting_player()
    assert room.next_tick() is None
    assert engine._tick_tasks(room) == []


def test_engine_routes_the_run_command_inside_the_tag_window():
    """服务端接线：触垒窗口里 /run 照收，转发出去之后马上排传球 tick。"""
    engine = BaseballEngine()
    room = _tag_room([3])
    engine._rooms[room.room_id] = room
    engine._player_room[room.batting_player()] = room.room_id
    result = engine.handle_command(Mock(), room.batting_player(), {},
                                   'run', 'go')
    assert room.phase == 'throw'
    assert room.throw.base == '本垒'
    kinds = [task['action'] for task in result.get('schedule', [])]
    assert 'tick' in kinds
    assert room.next_tick().ms == rules.TICK_MS


def test_a_forced_third_out_cancels_the_runs_of_the_same_play():
    """第三出局是封杀时，这一拍跑回来的分不算（美职棒记分规则）。"""
    hit = rules.HitBall(kind='ground', landing=8, shown=8, ticks=4,
                        tick_ms=560)

    def play(outs_before: int) -> int:
        room = _room()
        room.bases = [1]
        _ground_play(room, hit, 8)
        room.outs = outs_before
        room.runners.append(Runner(               # 这一拍已经有人跑回本垒
            '三垒跑者', 3, rules.HOME, rules.HOME, 1, True, scored=True))
        room.ground.cell = room.ground.ball
        before = room.score[room.batting_player()]
        assert room.start_throw('二垒') is True
        while room.phase == 'throw':
            room.throw_tick()
        if room.phase == 'ground':              # 球留在垒上等人再传：先控球收尾
            room.hold_ball()
        if outs_before == 2:
            assert any('三垒跑者回本垒不计分' in line for line in room.log)
        return room.score[room.batting_player()] - before

    assert play(2) == 0                         # 封杀＝第三出局：分不算
    assert play(1) == 1                         # 不是第三出局：分照算


# ── 局数 / 播报单行 / 手感（2026-10-21）──


def _bot_game(seed: int, innings: int = 3) -> tuple[BaseballRoom, list[str]]:
    """两个机器人打完一场：返回房间和这一路上所有的播报行。"""
    from server.games.baseball.bot import BaseballBot

    random.seed(seed)
    room = BaseballRoom('r-bots', ['A', 'B'], {'innings': innings})
    room.bots = {'A', 'B'}
    room.rng = random.Random(seed)
    now = [1000.0]
    room.clock = lambda: now[0]            # 野手按时钟跑：每一拍走过它的时长
    lines = room.start().split('\n')
    bot = BaseballBot()
    for _ in range(40000):
        if room.state == 'finished':
            break
        tick = room.next_tick()
        if tick is not None:
            now[0] += tick.ms / 1000
        phase = room.phase
        if phase == 'call':
            if room.armed:
                room.release_pitch(room.fielding_player())
            elif room.countdown:
                room.countdown_tick()
            else:
                bot.submit(room, room.fielding_player())
                bot.submit(room, room.batting_player())
        elif phase == 'delivery':
            room.delivery_step()
            if room.phase == 'delivery':
                bot.press(room)
        elif phase == 'flight':
            bot.field(room)
            bot.run(room)
            room.flight_step()
        elif phase == 'ground':
            bot.ground(room)
            bot.run(room)
            if room.phase == 'ground':
                room.ground_tick()
        elif phase == 'throw':
            room.throw_tick()
        elif phase == 'tag':
            bot.tag(room)
        lines.extend(room._drain())
    assert room.state == 'finished'
    return room, lines


def test_innings_are_a_room_setting_from_one_to_nine():
    from server.games.baseball import GAME_INFO

    setting = next(item for item in GAME_INFO['room_settings']
                   if item['key'] == 'innings')
    assert [option['value'] for option in setting['options']] == list(
        range(1, 10))
    assert setting['default'] == DEFAULT_INNINGS

    engine = BaseballEngine()
    assert engine._parse_settings('{"innings": 5}') == {'innings': 5}
    assert engine._parse_settings('{"innings": 10}') == {}     # 不在 1–9：忽略

    room = BaseballRoom('r-n', ['alice', 'bob'], {'innings': 5})
    assert room.total_innings == 5
    assert room.get_table_data()['summary'] == [['局数', '5 局']]
    assert '共5局' in room.start()
    data = room.get_game_data(viewer='alice')
    assert data['total_innings'] == 5
    assert len(data['line_score']['away']) == len(data['line_score']['home']) == 5
    assert BaseballRoom('r-d', ['a', 'b']).total_innings == DEFAULT_INNINGS


def test_the_ending_rules_follow_the_chosen_number_of_innings():
    one = BaseballRoom('r-1', ['alice', 'bob'], {'innings': 1})
    one.start()
    one.score[one.sides['home']] = 1
    one._change_half()                       # 只有 1 局：上半结束主队领先就不必再打
    assert one.state == 'finished' and one.winner == one.sides['home']

    five = BaseballRoom('r-5', ['alice', 'bob'], {'innings': 5})
    five.start()
    five.innings = 4
    five.score[five.sides['home']] = 3
    five._change_half()                      # 第 4 局不是末局：照常打下半
    assert five.state == 'playing' and five.half == 'bottom'
    five.innings, five.half = 5, 'top'
    five._change_half()                      # 末局上半结束主队领先：下半局不再进行
    assert five.state == 'finished' and five.winner == five.sides['home']

    tied = BaseballRoom('r-t', ['alice', 'bob'], {'innings': 5})
    tied.start()
    tied.innings, tied.half = 5, 'bottom'
    tied._change_half()                      # 打满仍平手：平局，不加赛
    assert tied.state == 'finished' and tied.winner == ''


@pytest.mark.parametrize('innings, ratio', [(1, 1 / 3), (3, 1), (9, 3)])
def test_rewards_scale_with_the_number_of_innings(monkeypatch, innings, ratio):
    """经验 / 金币 / 段位分都按「局数 ÷ 3」缩放（2026-10-21 用户定）。"""
    monkeypatch.setattr(PlayerManager, 'save_player_data', Mock())
    engine = BaseballEngine()
    multipliers = []
    engine._update_player_rank = (
        lambda data, outcome, has_bots=False, multiplier=1:
        multipliers.append(multiplier) or {})
    room = BaseballRoom('r-r', ['alice', 'bob'], {'innings': innings})
    room.start()
    room.score[room.sides['away']] = 2
    room._finish_match()
    winner = room.winner
    data = get_default_user_template(name=winner, password_hash='x')
    data.pop('password_hash', None)

    assert engine._settle_player(room, winner, data) is True
    exp, gold = engine._REWARDS['win']
    result = room._settlement_results[winner]
    assert result['exp'] == round(exp * ratio)
    assert result['gold'] == round(gold * ratio)
    assert multipliers == [pytest.approx(ratio)]


def test_a_press_between_two_frames_is_judged_where_the_player_saw_the_ball():
    """客户端报画面上的球位（带帧内进度）；服务端按「帧号 + 帧内进度」认，
    领先于服务端的那部分仍然不认（伪造不了更好的时机）。"""
    def press(claim: float, elapsed_ms: float) -> str:
        room = _room()
        clock = [0.0]
        room.clock = lambda: clock[0]
        pitcher, batter = room.fielding_player(), room.batting_player()
        room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
        room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
        _through_countdown(room)
        while room.delivery.frame < 4:
            room.delivery_step()
        clock[0] = elapsed_ms / 1000            # 第 4 帧开始后过了这么久
        room.swing_now(batter, claim)
        return room.exchange.swing.timing

    half = rules.ANIM_FRAME_MS / 2
    assert press(4.6, half) == 'normal'         # 球在 4.6：越过了 4.05 的分界线
    assert press(4.6, 0) == 'early'             # 同样报 4.6，但服务端这一帧才刚开始：按 4.0 算
    assert press(4.0, half) == 'early'          # 报得比实际早，在容差内照认


def test_a_fielder_command_reaches_both_screens_at_once():
    """野手改方向 / 起跳成功之后两边的屏幕马上跟上，不用等下一拍（2026-10-21）。"""
    engine, room = _engine_with_room()
    fielder, batter = room.fielding_player(), room.batting_player()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700))
    result = engine.handle_command(Mock(), fielder, {}, 'field', 'right')
    assert room.flight.fielder.heading == 1
    for viewer in (fielder, batter):
        messages = result['send_to_players'][viewer]
        updates = [m for m in messages if m['type'] == 'room_update']
        assert updates[0]['room_data']['flight']['fielder']['heading'] == 1
        assert not [m for m in messages if m['type'] == 'game']   # 只刷新棋盘，不刷播报

    # 方向没变：什么都不发
    assert engine.handle_command(Mock(), fielder, {}, 'field', 'right') == {
        'action': 'baseball_input'}
    stop = engine.handle_command(Mock(), fielder, {}, 'field', 'stop')
    assert room.flight.fielder.heading == 0 and stop['send_to_players']

    jump = engine.handle_command(Mock(), fielder, {}, 'jump', '')
    assert room.flight.fielder.jumped_at is not None
    for viewer in (fielder, batter):
        data = [m for m in jump['send_to_players'][viewer]
                if m['type'] == 'room_update'][0]['room_data']
        assert data['flight']['fielder']['air'] > 0
        assert data['flight']['fielder']['lock'] > data['flight']['fielder']['air']
    # 还在缓冲里再按回车：什么都不发生
    assert engine.handle_command(Mock(), fielder, {}, 'jump', '') == {
        'action': 'baseball_input'}
    # 进攻方的按键一律无效
    assert engine.handle_command(Mock(), batter, {}, 'jump', '') == {
        'action': 'baseball_input'}
    assert engine.handle_command(Mock(), fielder, {}, 'field', 'up') == {
        'action': 'baseball_input'}


def test_multi_line_messages_become_one_game_message_per_line():
    """上方通知栏一次只显示一行：多行的播报拆成一行一条，栏上留下最后一条。"""
    from server.games.baseball.engine import _one_line
    from server.msg_types import GAME, ROOM_UPDATE

    result = _one_line({
        'send_to_caller': [{'type': GAME, 'text': 'a\nb'},
                           {'type': ROOM_UPDATE, 'room_data': {}}],
        'send_to_players': {'x': [{'type': GAME, 'text': 'c\n\nd'}]},
    })
    assert [m['text'] for m in result['send_to_caller']
            if m['type'] == GAME] == ['a', 'b']
    assert result['send_to_caller'][-1]['type'] == ROOM_UPDATE
    assert [m['text'] for m in result['send_to_players']['x']] == ['c', 'd']


def test_long_log_lines_wrap_only_between_phrases():
    from server.games.baseball.room import LOG_COLS, _cols, _wrap

    short = ['挥空', '0-1', '时机提前', '预判错误']
    assert _wrap(short) == ['挥空 0-1 时机提前 预判错误']

    phrases = ['打者上一垒', '一垒跑者上二垒', '二垒跑者上三垒', '三垒跑者得分',
               'alice 3-2 bob'] * 3
    lines = _wrap(phrases)
    assert len(lines) >= 2
    assert all(_cols(line) <= LOG_COLS for line in lines)
    assert ' '.join(lines) == ' '.join(phrases)           # 一个词不丢
    whole = {'打者上一垒', '一垒跑者上二垒', '二垒跑者上三垒', '三垒跑者得分',
             'alice 3-2 bob'}
    for line in lines:                                    # 每一行都由整块拼成
        assert any(line == block or line.startswith(f'{block} ')
                   for block in whole), line


_FULL_WIDTH = '，。；：！？（）、'


def test_every_log_line_fits_the_notification_bar_and_says_each_fact_once():
    """跑几场机器人对局：每一行都收在栏宽里、不用中文标点；同一件事只说一次。"""
    import re

    from server.games.baseball.room import LOG_COLS, _cols

    for seed, innings in ((1, 3), (2, 5), (3, 2), (4, 4)):
        room, lines = _bot_game(seed, innings)
        assert lines
        for index, line in enumerate(lines):
            assert '\n' not in line and _cols(line) <= LOG_COLS, line
            assert not set(line) & set(_FULL_WIDTH), line
            assert not re.search(r'跑垒结果|保持|普通接球|双方均已提交|球数|出局）', line), line
            following = lines[index + 1] if index + 1 < len(lines) else ''
            if line.startswith(('未挥棒', '挥空', '界外', '收棒')) \
                    and not following.startswith(('攻守交换', '比赛结束', '第')):
                # 一球的结果、球数（或这个打席的结局）在同一行里
                # （盗垒抓到第三个出局、再见分这两种不数球的收尾除外）
                assert re.search(r'\d-\d|三振|保送', line), line
            if line.startswith(('封杀', '触杀', '盗垒失败', '接杀', '双杀')):
                assert re.search(r'\d出局', line), line      # 出局的那一行就带着出局数
            if '得分' in line and '不计分' not in line:
                near = ' '.join(lines[index:index + 2])
                assert re.search(r'[AB] \d+-\d+ [AB]', near), line   # 得分带着最新比分
        assert any(line.startswith('攻守交换 第') for line in lines)
        assert lines[0].startswith('开赛')
        assert lines[-1].startswith('比赛结束')


def test_the_pitch_line_is_the_one_line_that_stays_in_the_bar():
    """一球的结局合成一行：结果、球数（或三振 / 保送）、时机和预判；不再拆成几句。"""
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('slider', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'take', 'normal'))
    _through_countdown(room)
    while room.phase == 'delivery':
        room.delivery_step()
    assert len(room.log) == 1
    assert room.log[0].startswith('未挥棒 ')
    assert room.log[0].endswith(f' {room.balls}-{room.strikes}')


def test_the_final_report_has_the_line_score_and_the_stats():
    for seed in (5, 6):
        room, _lines = _bot_game(seed, innings=4)
        report = room.report_lines()
        away, home = room.sides['away'], room.sides['home']
        assert len(report) == 4
        assert report[0].startswith(f'客 {away}') and report[0].endswith(
            f'| {room.score[away]}')
        assert report[1].startswith(f'主 {home}')
        assert sum(runs or 0 for runs in room.line_score[away]) == room.score[away]
        assert sum(runs or 0 for runs in room.line_score[home]) == room.score[home]
        for player in (away, home):
            stats = room.stats[player]
            assert stats['homeruns'] <= stats['hits']
            assert all(count >= 0 for count in stats.values())
            assert (f'{player} 安打{stats["hits"]} 全垒打{stats["homeruns"]} '
                    f'保送{stats["walks"]} 被三振{stats["strikeouts"]}'
                    in '\n'.join(report))
        assert 'X' not in report[0]                       # 客队总是打满的


def test_settlement_ends_with_a_one_line_conclusion():
    engine = BaseballEngine()
    room = BaseballRoom('r-s', ['alice', 'bob'], {'innings': 3})
    room.start()
    away, home = room.sides['away'], room.sides['home']
    settlement = {'outcome': 'win', 'exp': 150, 'gold': 30,
                  'rank_change': {'delta': 12},
                  'score': {away: 2, home: 1}}
    line = engine._format_result(away, room, settlement)
    assert '\n' not in line
    assert line == '获胜 2-1 经验+150 金币+30 段位+12'
    loss = {**settlement, 'outcome': 'loss'}
    assert engine._format_result(home, room, loss).startswith('落败 1-2 ')   # 比分先写自己的


def test_pressing_hit_lights_the_swing_mark_before_the_server_answers():
    """按下击球的瞬间本地就把挥棒点画出来；服务端的回执晚到、甚至先到一份旧数据，也不会熄灭。"""
    from client.config import NF_ONLINE

    client = _Client()
    room = _room()
    pitcher, batter = room.fielding_player(), room.batting_player()
    room.set_pitch(pitcher, rules.PitchCall('four_seam', 'edge', 'normal'))
    room.set_swing(batter, rules.SwingCall('four_seam', 'standard'))
    _through_countdown(room)
    client.update(room, batter)
    assert not client.ui.board.delivery.swung

    client.press('enter')                         # 按下击球
    assert client.sent[-1].startswith('/hit ')
    assert client.ui.pressed and client.ui.board.delivery.swung
    renderer = RENDERER_REGISTRY['baseball']
    interaction = client.state.game_interaction.snapshot('baseball')
    drawn = _dump(renderer.render_board(_room_data(room, batter), interaction,
                                        88, 19)['board'], 88)
    assert f'投打 {NF_ONLINE}' in drawn           # 服务端数据里还没有 swung，标记照样亮着

    room.delivery_step()                          # 一份发在服务端收到按键之前的旧数据
    client.update(room, batter)
    assert client.ui.board.delivery.swung         # 没有闪回「没挥」
    assert [item.label for item in client.ui.controls.items] != ['击球']

    room.swing_now(batter, 1)                     # 服务端的回执
    while room.phase == 'delivery':
        room.delivery_step()
    client.update(room, batter)
    assert not client.ui.pressed                  # 这一球结束，状态清掉


def test_the_waiting_room_info_panel_shows_the_innings():
    """等候室的「房间」面板写出房主选的局数（游戏自己的设置走 summary，别的游戏不受影响）。"""
    import asyncio

    from textual.app import App, ComposeResult
    from textual.widgets import Static

    from client.state import ModuleStateManager
    from client.views.game.info import RoomInfoPanel

    class InfoApp(App):
        def compose(self) -> ComposeResult:
            yield RoomInfoPanel(id='room-info')

    room = BaseballRoom('r-info', ['alice'], {'innings': 7})
    plain = dict(room.get_table_data(), summary=[])

    async def verify() -> None:
        app = InfoApp()
        async with app.run_test(size=(60, 12)) as pilot:
            panel = app.query_one(RoomInfoPanel)
            state = ModuleStateManager()
            panel.bind_state(state)
            state.game_board.update_room(room.get_table_data())
            await pilot.pause()
            text = str(panel.query_one(Static).content)
            assert '局数    7 局' in text
            state.game_board.update_room(plain)
            await pilot.pause()
            assert '局数' not in str(panel.query_one(Static).content)

    asyncio.run(verify())


def _server_clock(room: BaseballRoom, start: float = 500.0) -> list[float]:
    """给房间换一只可手动拨的时钟（野手按它的时间匀速跑）。"""
    now = [start]
    room.clock = lambda: now[0]
    return now


def _advance_client(client: _Client) -> None:
    """客户端走一帧动画（和计时器到点时做的事一样）。"""
    snapshot = client.state.game_interaction.snapshot('baseball')
    client.handler._advance(snapshot)
    client.state.game_interaction.replace('baseball', snapshot)


def test_a_held_chase_direction_is_sent_once_not_every_tick():
    """方向由服务端记着：按住一个方向只发一次，之后的刷新与计时都不再重发。"""
    client = _Client()
    room = _room()
    room._begin_flight(rules.HitBall(kind='fly', landing=9, shown=9,
                                     ticks=8, tick_ms=700))
    fielder = room.fielding_player()
    client.update(room, fielder)
    client.press('right')                         # 光标落到「右移」
    assert client.sent == ['/field right']
    client.sent.clear()

    client.update(room, fielder)
    room.flight_step()                            # 计时器走了一拍
    client.update(room, fielder)
    assert client.sent == []


def test_the_fielder_glides_at_the_servers_speed_between_updates():
    """野手从服务端报的位置出发，按方向与速度匀速滑：不是一格一跳，也不等下一拍。"""
    client = _Client()
    room = _room()
    now = _server_clock(room)
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=8, tick_ms=700))
    fielder = room.fielding_player()
    chaser = room.flight.fielder
    room.steer_fielder(1)
    now[0] += 1.0                                 # 服务端 1 秒后才把数据发过来
    client.update(room, fielder)

    def field_at() -> float:
        return client.state.game_interaction.snapshot('baseball')['field_at']

    start = chaser.position(now[0])
    assert field_at() == pytest.approx(start, abs=1e-3)
    field_at_start = field_at()
    assert client.timers, '野手在跑，就该有动画帧'
    seen = []
    for _frame in range(4):                       # 每帧走一点，匀速
        client.clock[0] += 0.5
        _advance_client(client)
        seen.append(field_at())
    steps = [b - a for a, b in zip([field_at_start] + seen, seen)]
    assert all(step == pytest.approx(chaser.speed * 0.5, rel=1e-3)
               for step in steps)

    client.clock[0] += 1000                       # 一直往右：跑到边线就停
    _advance_client(client)
    assert field_at() == float(rules.FIELD_CELLS)

    room.steer_fielder(0)                         # 站住：画面停在服务端报的位置
    client.update(room, fielder)
    stopped = field_at()
    client.clock[0] += 5
    _advance_client(client)
    assert field_at() == stopped


def test_the_fielder_waits_out_the_jump_before_running_again():
    client = _Client()
    room = _room()
    now = _server_clock(room)
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=8, tick_ms=700))
    room.steer_fielder(1)
    now[0] += 1.0
    room.jump_fielder()
    client.update(room, room.batting_player())   # 对手的屏幕也看得到
    snapshot = client.state.game_interaction.snapshot
    frozen = snapshot('baseball')['field_at']
    client.clock[0] += rules.FIELDER_AIR_SECONDS + rules.FIELDER_REST_SECONDS - 0.01
    _advance_client(client)
    assert snapshot('baseball')['field_at'] == pytest.approx(frozen)   # 缓冲期间不动
    client.clock[0] += 1.01
    _advance_client(client)
    assert snapshot('baseball')['field_at'] > frozen                   # 缓冲完接着跑


def test_the_fielder_shows_whether_he_is_in_the_air_or_resting():
    from client.config import NF_USER
    from client.games.baseball import diamond, style

    client = _Client()
    room = _room()
    now = _server_clock(room)
    room._begin_flight(rules.HitBall(kind='fly', landing=10, shown=10,
                                     ticks=8, tick_ms=700))
    fielder = room.fielding_player()

    def fielder_style() -> str:
        track = diamond.FieldTrack(client.ui.board, client.ui.anim, 88)
        return next(mark.style for mark in track.marks()
                    if mark.glyph == NF_USER)

    client.update(room, fielder)
    assert fielder_style() == style.FIELDER                       # 平时是己方的绿
    now[0] += 1
    room.jump_fielder()
    client.update(room, fielder)
    assert fielder_style() == style.HEAD                          # 在空中
    client.clock[0] += rules.FIELDER_AIR_SECONDS + 0.01
    _advance_client(client)
    assert fielder_style() == style.DIM                           # 落地缓冲
    client.clock[0] += rules.FIELDER_REST_SECONDS
    _advance_client(client)
    assert fielder_style() == style.FIELDER


def test_the_throw_menu_appears_the_moment_the_fielder_reaches_the_ball():
    """画面上的野手一跑到球位，传球菜单就出来，不等服务端的下一拍。"""
    client = _Client()
    room = _room()
    now = _server_clock(room)
    _ground_play(room, rules.HitBall(kind='line', landing=9, shown=9,
                                     ticks=4, tick_ms=100), cell=5)
    fielder = room.fielding_player()
    room.steer_fielder(1)
    client.update(room, fielder)
    assert client.labels == ['左移', '停止', '右移']
    travel = (9 - 5) / room.ground.fielder.speed

    client.clock[0] += travel - 0.05
    _advance_client(client)
    assert client.labels == ['左移', '停止', '右移']             # 还差一点
    client.clock[0] += 0.1
    _advance_client(client)
    assert client.ui.board.ground.at_ball
    assert client.labels[0].startswith('传')

    now[0] += travel + 0.01                       # 服务端的时钟走到了，也认这一传
    assert room.at_ball() is True


def test_the_landing_range_narrows_smoothly_toward_the_next_tick():
    """落点范围这一拍朝下一拍的窄范围滑，滑完正好下一拍到来；球落地时收成一点。"""
    client = _Client()
    room = _room()
    hit = rules.HitBall(kind='fly', landing=9, shown=8, spread=2.0, ticks=4,
                        tick_ms=1000)
    room._begin_flight(hit)
    fielder = room.fielding_player()
    client.update(room, fielder)
    values = client.state.game_interaction.snapshot('baseball')
    assert (client.ui.anim.values['span_low'],
            client.ui.anim.values['span_high']) == (6.0, 10.0)

    client.clock[0] += 0.5
    _advance_client(client)
    low, high = (client.ui.anim.values['span_low'],
                 client.ui.anim.values['span_high'])
    assert 6.0 < low < 6.75 and 9.75 < high < 10.0     # 半拍：滑到一半

    client.clock[0] += 0.5
    _advance_client(client)
    assert (client.ui.anim.values['span_low'],
            client.ui.anim.values['span_high']) == pytest.approx((6.75, 9.75))
    assert values                                       # 只是确认能取到交互状态

    room.flight_step()
    client.update(room, fielder)
    assert client.ui.anim.values['span_low'] == pytest.approx(6.75)
