"""棒球房间状态机 — 局数、出局、垒包、球数与逐格飞行。

只维护状态与文案；投打/守备的数学在 rules.py，各阶段的数据在 state.py，
命令与调度在 engine.py，机器人决策在 bot.py。
"""

from __future__ import annotations

import logging
import math
import random
import time
import unicodedata

from . import rules
from .state import (
    Delivery, Exchange, Fielder, Flight, Pickup, PitchRecord, Relay, Runner,
    Tag, Throw, ThrowOption, Tick,
)

logger = logging.getLogger(__name__)

DEFAULT_INNINGS = 3
OUTS_PER_HALF = 3
BALLS_FOR_WALK = 4
STRIKES_FOR_OUT = 3
PITCH_RECENT = 10          # 侦察板保留的最近球数
MAX_STAMINA = 100
STAMINA_PER_PITCH = 7
STAMINA_FULL_EFFORT = 13
STAMINA_TIRED = 35
# 上方通知栏一次只显示一行，最窄窗口（88 列）扣掉边框、缩进与时间戳后约剩 74 列：
# 播报的每一行都收在这个宽度里，放不下的在词组之间换行（最后一行就是留在栏上的那句）
# 播报的写法：词组之间一个空格，不用中文标点连句子；计数一律 `1-2`（坏球-好球）、`2出局`、`A 4-2 B`
LOG_COLS = 70
# 播报里不许出现的中文标点（2026-10-22 定：词组之间只用一个空格，不用标点连句子）
LOG_FORBIDDEN_PUNCTUATION = frozenset('，；：。！？（）、')
STAT_KEYS = ('hits', 'homeruns', 'walks', 'strikeouts')

# 下发给客户端的取值文案：菜单由客户端生成，文字以服务端为准
_LABELS = {
    'pitch_types': [[key, rules.PITCH_TYPE_LABELS[key]]
                    for key in rules.PITCH_TYPES],
    'bands': [[key, rules.BAND_LABELS[key]] for key in rules.BANDS],
    'efforts': [[key, rules.EFFORT_LABELS[key]] for key in rules.EFFORTS],
    'holds': [[key, rules.HOLD_LABELS[key]] for key in rules.HOLDS],
    'swings': [[key, rules.SWING_LABELS[key]] for key in rules.SWINGS],
    'steals': [[key, label] for key, label in rules.STEAL_LABELS.items()],
    'shifts': [[key, rules.SHIFT_LABELS[key]] for key in rules.SHIFTS],
}
# 击球时机三档的分界（占投球段的比例）：客户端在投打行上画出分界线
_TIMING_CUTS = [rules.SWING_EARLY_RATIO, rules.SWING_NORMAL_RATIO]


def _cols(text: str) -> int:
    """终端里占几列：汉字与全角符号两列，其余一列。"""
    return sum(2 if unicodedata.east_asian_width(char) in 'WF' else 1
               for char in text)


def log_violations(line: str) -> list[str]:
    """一行播报违反了哪些写法规则（空表示合规）：单行、≤ LOG_COLS 列、无中文标点、
    词组之间只有一个空格、首尾无空白。"""
    problems = []
    if '\n' in line:
        problems.append('不是单行')
    if _cols(line) > LOG_COLS:
        problems.append(f'超过 {LOG_COLS} 列')
    if LOG_FORBIDDEN_PUNCTUATION.intersection(line):
        problems.append('含中文标点')
    if line != line.strip() or '  ' in line:
        problems.append('空格不规范')
    return problems


def _wrap(phrases: list[str]) -> list[str]:
    """把一串词组装成几行：词组之间一个空格，一行放不下就换行，但不在词组中间断开。

    播报不用标点连句子：每个词组自成一块（`封杀 一垒 打者 2出局`），换行也只发生在块与块之间。
    """
    lines: list[str] = []
    current = ''
    for phrase in phrases:
        joined = f'{current} {phrase}' if current else phrase
        if current and _cols(joined) > LOG_COLS:
            lines.append(current)
            current = phrase
        else:
            current = joined
    if current:
        lines.append(current)
    return lines


def _fielding(hit: rules.HitBall, position: float, airborne: bool,
              jumped: bool) -> list[str]:
    """接球判定那一刻的事实：落点、野手在哪；起跳过的再补一句时机（只陈述，不评价）。"""
    phrases = [f'落点{rules.field_label(hit.landing)}',
               f'野手{rules.field_label(position)}']
    if jumped:
        phrases.append(f'{rules.jump_label(hit.kind)}'
                       f'{"恰好" if airborne else "过早"}')
    return phrases


class BaseballRoom:
    """一场 1v1 棒球对局。players 顺序即建房顺序，开局随机定先后攻。"""

    max_players = 2
    min_players = 2

    def __init__(self, room_id: str, players: list[str],
                 settings: dict | None = None):
        self.room_id = room_id
        self.players = list(players)
        self.host = self.players[0]
        self.ready: set[str] = set()
        self.bots: set[str] = set()
        self.ranked = False
        self.rank_tier = 1
        self.total_innings: int = (settings or {}).get(
            'innings', DEFAULT_INNINGS)
        self.clock = time.monotonic     # 按键时折算帧内进度用；测试里换成假时钟
        self.reset_match()

    # ── 生命周期 ──

    def is_bot(self, name: str) -> bool:
        return name in self.bots

    def is_full(self) -> bool:
        return len(self.players) >= self.max_players

    def add_bot(self) -> tuple[bool, str]:
        if self.is_full():
            return False, '房间已满。'
        index = 1
        while f'Bot_{index}' in self.players:
            index += 1
        name = f'Bot_{index}'
        self.players.append(name)
        self.bots.add(name)
        return True, name

    def reset_match(self) -> None:
        self.state = 'waiting'          # waiting / playing / finished
        self.rng = random.Random()
        self.innings = 1
        self.half = 'top'              # top=先攻（客队）
        self.outs = 0
        self.bases: list[int] = []
        self.balls = 0
        self.strikes = 0
        self.score = {p: 0 for p in self.players}
        # 逐局得分：None＝这半局还没打（或下半局不必再打）
        self.line_score: dict[str, list[int | None]] = {
            p: [None] * self.total_innings for p in self.players}
        self.stats = {p: dict.fromkeys(STAT_KEYS, 0) for p in self.players}
        self._contact_outs = 0                  # 这次击球开始时的出局数
        self._hit_error = False                 # 这次击球野手有没有脱手（失误上垒不算安打）
        self.sides = {'away': '', 'home': ''}
        self.attributes = {p: rules.roll_attributes(random.Random())
                           for p in self.players}
        self.stamina = {p: MAX_STAMINA for p in self.players}
        self.shift = {p: 'standard' for p in self.players}
        self.phase = 'call'                     # call/delivery/flight/ground/throw/tag
        self.pending: dict[str, rules.PitchCall | rules.SwingCall] = {}
        self.exchange: Exchange | None = None   # 这一球的投打（开投后才有）
        self.delivery: Delivery | None = None
        self.countdown = 0                      # 两边交牌后的倒数秒数（3→2→1 才开投）
        self.armed = False                      # 倒数完了、等投手按「投球」
        self.verdict = ''                       # 这一拍的判定（安全/出局/全垒打…）
        self.runners: list[Runner] = []         # 本次击球后的跑者
        self.order = rules.DEFAULT_RUN_ORDER    # 攻方此刻的跑垒指令（back / stop / go）
        self.plays = 0                          # 击出过几次球（机器人据此一次击球只下一次令）
        self.steal = ''                         # 本球排好的盗垒：''/lead/all
        self.flight: Flight | None = None
        self.ground: Pickup | Relay | None = None
        self.throw: Throw | None = None
        self.tag: Tag | None = None
        self.throw_outs = 0                     # 这次击球靠传球拿下几个出局（双杀用）
        self.last_ball = ''                     # 本垒上的结果符号（保持到下一球）
        self.history: list[PitchRecord] = []    # 侦察板
        self.log: list[str] = []
        self.winner = ''
        self._result_pending: set[str] = set()
        self._settled_players: set[str] = set()
        self._settlement_results: dict = {}
        self._settlement_retry_scheduled = False

    def start(self) -> str:
        """开局：随机定先后攻。"""
        self.reset_match()
        order = list(self.players)
        random.shuffle(order)
        self.sides['away'], self.sides['home'] = order
        self.state = 'playing'
        self.line_score[self.sides['away']][0] = 0
        self._push('开赛', f'{self.batting_player()} 先攻',
                   f'{self.fielding_player()} 后攻', f'共{self.total_innings}局')
        return '\n'.join(self._drain())

    # ── 角色 ──

    def batting_player(self) -> str:
        return self.sides['away' if self.half == 'top' else 'home']

    def fielding_player(self) -> str:
        return self.sides['home' if self.half == 'top' else 'away']

    def decision_owner(self) -> str:
        """当前必须做决定的玩家；动画与传球途中无人需要按菜单行动。

        出牌阶段（`call`）双方同时出牌：先让还没交牌的机器人动起来，
        所以这里返回"还没交牌的机器人"，没有机器人时返回还没交牌的玩家。
        """
        if self.state != 'playing':
            return ''
        if self.phase == 'call':
            if self.armed:              # 倒数完了：等投手按「投球」（机器人也是他）
                pitcher = self.fielding_player()
                return pitcher if self.is_bot(pitcher) else ''
            waiting = [p for p in self.players if p not in self.pending]
            bots = [p for p in waiting if self.is_bot(p)]
            return (bots or waiting or [''])[0]
        if self.phase == 'ground':
            return self.fielding_player()
        if self.phase == 'tag':
            return self.batting_player()
        return ''

    def current_player(self) -> str:
        """房间外壳用它判断该谁行动（飞行阶段返回空）。"""
        return self.decision_owner()

    def pitcher_attributes(self, player: str) -> rules.PitcherAttributes:
        """带上体力修正的投手属性：累了（≤35）控球球速各 −1，力竭（≤0）再 −1。"""
        base = self.attributes[player].pitcher
        stamina = self.stamina[player]
        penalty = (stamina <= STAMINA_TIRED) + (stamina <= 0)
        return rules.PitcherAttributes(
            control=max(1, base.control - penalty),
            velocity=max(1, base.velocity - penalty),
            breaking=base.breaking)

    def _fielder(self) -> rules.FielderAttributes:
        return self.attributes[self.fielding_player()].fielder

    def _runner_speed(self) -> int:
        return self.attributes[self.batting_player()].fielder.speed

    # ── 决策阶段 ──

    def _push(self, *phrases: str) -> None:
        """记一条播报：词组之间一个空格，一行放不下就在词组之间换行。"""
        lines = _wrap([phrase for phrase in phrases if phrase])
        for line in lines:
            for problem in log_violations(line):
                logger.warning('棒球播报违反写法规则（%s）：%r', problem, line)
        self.log.extend(lines)

    def _drain(self) -> list[str]:
        lines, self.log = self.log, []
        return lines

    def _add_runs(self, runs: int) -> None:
        """记一次得分：总分和这一局的分一起加。"""
        batter = self.batting_player()
        self.score[batter] += runs
        frames = self.line_score[batter]
        frames[self.innings - 1] = (frames[self.innings - 1] or 0) + runs

    def _score_text(self) -> str:
        away, home = self.sides['away'], self.sides['home']
        return f'{away} {self.score[away]}-{self.score[home]} {home}'

    def _outs_text(self) -> str:
        return f'{self.outs}出局'

    def set_shift(self, player: str, shift: str) -> tuple[bool, list[str]]:
        """布阵是这次投球的设置项：交牌前随时可改，不会推进阶段。"""
        if (self.phase != 'call' or player != self.fielding_player()
                or player in self.pending):
            return False, ['现在不能布阵']
        self.shift[player] = shift
        self._push(f'布阵 {rules.SHIFT_LABELS[shift]}')
        return True, self._drain()

    def set_pitch(self, player: str, call: rules.PitchCall
                  ) -> tuple[bool, list[str]]:
        """提交投球选择：交牌即锁定，两边都交了才开动画。"""
        if (self.phase != 'call' or player != self.fielding_player()
                or player in self.pending):
            return False, ['现在不是投球时机']
        if self.flight and self.flight.done:
            self.flight = None          # 上一次全垒打的球到这儿就清掉
        if not self.bases:
            call.hold = 'no'            # 垒上没人，没有跑者可牵制
        self.pending[player] = call
        return self._start_when_both_ready()

    def set_swing(self, player: str, call: rules.SwingCall
                  ) -> tuple[bool, list[str]]:
        """提交打击选择：交牌即锁定；两边都交了先倒数，再播两段动画。"""
        if (self.phase != 'call' or player != self.batting_player()
                or player in self.pending):
            return False, ['现在不是打击时机']
        if not self.bases:
            call.steal = 'hold'         # 垒上没人，没有盗垒可排
        self.pending[player] = call
        return self._start_when_both_ready()

    def _start_when_both_ready(self) -> tuple[bool, list[str]]:
        """两边都交牌了就开始倒数（3→2→1），倒数完才真的开投。

        打者交的是"预判球种 + 挥棒方式 + 盗垒"，时机不再是选项：等他按下击球那一刻才算得出来
        （见 `swing_now`）。整球结果照旧只在最后一帧揭晓。

        **交牌留在 `pending` 里不清**：倒数期间谁也不能再改（`set_*` 靠它拦人），
        但两个灯继续亮着（`ready_sides` 也读它），所以"双方都交了"看得见。
        """
        if (self.fielding_player() in self.pending
                and self.batting_player() in self.pending
                and not self.countdown):
            self.countdown = rules.COUNTDOWN_SECONDS
        return True, self._drain()

    def countdown_tick(self) -> None:
        """倒数一跳（每秒一次）：数到 0 就把球交给投手——**他自己按下投球才投出去**。

        倒数完不是自动投：投手那边亮起「投球」键，按下才开投（用户 2026-10-16 定：
        确定之后的按钮只是"投出"的确认，按下的时机不影响任何判定）。
        """
        self.countdown -= 1
        if self.countdown <= 0:
            self.armed = True

    def release_pitch(self, player: str) -> bool:
        """投手按下「投球」：这一球现在投出去。"""
        if (not self.armed or self.phase != 'call'
                or player != self.fielding_player()):
            return False
        self._begin_delivery()
        return True

    def _begin_delivery(self) -> None:
        """这一球真的开投（投球段 → 挥棒段 → 揭晓）。"""
        self.armed = False
        pitcher = self.fielding_player()
        pitch = self.pending[pitcher]
        swing = self.pending[self.batting_player()]
        cost = (STAMINA_FULL_EFFORT if pitch.effort == 'full'
                else STAMINA_PER_PITCH)
        self.stamina[pitcher] = max(
            0, self.stamina[pitcher]
            - round(cost * rules.PITCH_PROFILES[pitch.pitch_type].stamina))
        self.pending.clear()
        self.exchange = Exchange(pitch, swing)
        self.verdict = ''                    # 新的一球：判定槽清空（槽位不动，只是留白）
        self.last_ball = ''                  # 新的一球：本垒上的结果符号复位
        self.steal = '' if swing.steal == 'hold' else swing.steal
        self.runners = self._steal_runners(self.steal)   # 盗垒的人跟着投球动画起跑
        self.delivery = Delivery(tick_at=self.clock())
        self.phase = 'delivery'

    def _steal_runners(self, scope: str) -> list[Runner]:
        """起跑盗垒的人：在投打动画里跑，成功与否等投球结果揭晓。"""
        bases = sorted(self.bases)
        if scope == 'lead':
            bases = bases[-1:]
        if scope == '':
            bases = []
        return [Runner.start(f'{rules.BASE_LABELS[base]}跑者', base,
                             rules.delivery_frames(), forced=True)
                for base in bases]

    def _resolve_swing(self, swing: rules.SwingCall) -> None:
        """把这一球判出来——结果只存进 `exchange.result`，动画最后一帧才揭晓。

        **不能在这里写 `last_ball`**：那个字段每帧随视图下发，写早了等于提前把结果
        告诉对手（保密契约，见 `_apply_pitch_result`）。
        """
        self.exchange.swing = swing
        self.exchange.result = rules.resolve_pitch(
            self.exchange.pitch, swing,
            self.pitcher_attributes(self.fielding_player()),
            self.attributes[self.batting_player()].batter, self.rng,
        )

    def swing_now(self, player: str, frame: float | None
                  ) -> tuple[bool, list[str]]:
        """打者按下击球：这一按的时机档由他按下的那一帧决定（球来得快就得早按）。

        挥棒段（球已经到本垒）里按也照挥——那一下就是「延后」（用户 2026-10-15 定），
        所以击球键在整个投打过程里都不消失。按了就是要打：交牌时的「等球」
        在这一按之下改成接触挥（预判球种照旧用他交的那个）。

        时机帧由**服务端校验**（2026-10-17 用户定档：防作弊 + 补偿网络延迟）：
        客户端报来的帧最多只往回认 `HIT_LATENCY_TOLERANCE_FRAMES` 帧（≈280ms，
        盖得住网络延迟）；报未来、报得比这还早、或报的不是数字，都按服务端
        当前帧算——伪造一个完美时机在这下行不通。
        """
        anim = self.delivery
        if (self.phase != 'delivery' or anim is None
                or player != self.batting_player() or anim.swung
                or self.exchange.result is not None):
            return False, ['现在不能击球']
        anim.swung = True
        # 这一帧已经走了多久：按键落在两帧之间时，服务端的"现在"是帧号加上帧内进度
        now_frame = anim.frame + self._frame_progress(anim)
        if frame is None or not math.isfinite(frame):
            press_frame = now_frame
        else:
            earliest = max(0.0, now_frame - rules.HIT_LATENCY_TOLERANCE_FRAMES)
            press_frame = min(max(frame, earliest), now_frame)
        planned = self.exchange.swing
        self._resolve_swing(rules.SwingCall(
            planned.guess, planned.swing,
            rules.swing_timing(press_frame, anim.frames, anim.stage),
            planned.steal))
        return True, self._drain()

    def _frame_progress(self, anim: Delivery) -> float:
        """当前这一帧走了几分之几（0 ≤ 值 < 1）。"""
        elapsed = (self.clock() - anim.tick_at) * 1000
        return min(0.999, max(0.0, elapsed / rules.ANIM_FRAME_MS))

    def ready_sides(self) -> dict[str, bool]:
        """两边是否都已经交牌（棋盘中间槽里的两个灯）。"""
        return {
            'fielding': self.fielding_player() in self.pending,
            'batting': self.batting_player() in self.pending,
        }

    def delivery_step(self) -> None:
        """推进一帧投打动画：投球段（球从右往左）→ 挥棒段（打者符号变化）→ 揭晓。

        打者整段都能按击球（球到了本垒再按＝延后），没按才在动画走完时按「放过去」判好坏球。
        """
        self._advance_runners()          # 盗垒的人跟着投球动画一起跑
        if not self.delivery.advance():
            self.delivery.tick_at = self.clock()
            return
        self.delivery = None
        exchange = self.exchange
        if exchange.result is None:
            # 打者一次都没按：这一球就放过去了（按好坏球判，不是挥空）
            swing = exchange.swing
            self._resolve_swing(rules.SwingCall(swing.guess, 'take',
                                                'normal', swing.steal))
        self.exchange = None
        self._apply_pitch_result(exchange)

    def _apply_pitch_result(self, exchange: Exchange) -> None:
        pitch, swing, result = exchange.pitch, exchange.swing, exchange.result
        # 揭晓这一刻才写本垒结果符号（挥空画叉，其余回到空心圆；击中的方向在
        # `_begin_flight` 里写）——写早了就是提前泄密，见 `_resolve_swing`。
        self.last_ball = 'whiff' if result.kind == 'swing_miss' else ''
        self.history.append(PitchRecord(pitch, swing, result,
                                        self.batting_player()))
        del self.history[:-PITCH_RECENT]
        facts: list[str] = []
        if swing.swing != 'take':
            read = '正确' if swing.guess == pitch.pitch_type else '错误'
            facts = [f'时机{rules.TIMING_LABELS[swing.timing]}', f'预判{read}']
        if result.kind == 'contact':
            self._push(result.message, *facts)
            self._carry_steal()
            self._begin_flight(result.hit)
            return

        if self.steal:
            self._resolve_steal(pitch.hold)   # 盗垒先结算，球数照记
            if self.outs >= OUTS_PER_HALF:
                self._push(result.message, *facts)
                self._change_half()
                return
            if self._walk_off():
                self._push(result.message, *facts)
                self._finish_walk_off()
                return

        if result.kind in ('strike', 'swing_miss'):
            self.strikes += 1
        elif result.kind == 'foul':
            self.strikes = min(self.strikes + 1, STRIKES_FOR_OUT - 1)
        elif result.kind == 'ball':
            self.balls += 1

        # 留在上方通知栏的就是这一行：结果、球数（或这个打席的结局）、时机事实
        if self.strikes >= STRIKES_FOR_OUT:
            self.verdict = 'strikeout'
            self.outs += 1
            self.stats[self.batting_player()]['strikeouts'] += 1
            ending = ['三振', self._outs_text()]
        elif self.balls >= BALLS_FOR_WALK:
            self.verdict = 'walk'
            self.stats[self.batting_player()]['walks'] += 1
            ending = ['保送']
        else:
            ending = [f'{self.balls}-{self.strikes}']
        self._push(result.message, *ending, *facts)
        if self.verdict == 'strikeout':
            self._after_play()
        elif self.verdict == 'walk':
            self._walk()
        else:
            self.phase = 'call'

    # ── 飞行 ──

    def _begin_flight(self, hit: rules.HitBall) -> None:
        fielder = self.fielding_player()
        speed = self.attributes[fielder].fielder.speed
        self.runners = self._hit_runners()
        self.bases = []
        self.tag = None
        self.throw_outs = 0
        self._contact_outs = self.outs
        self._hit_error = False
        self.last_ball = hit.kind              # 本垒符号＝击出方向（高飞/平飞/滚地）
        self.flight = Flight(
            hit=hit, fielder=Fielder(
                pos=float(rules.shift_start(self.shift[fielder])),
                speed=rules.flight_run_speed(speed, hit.ticks, hit.tick_ms),
                at=self.clock()))
        self.steal = ''
        self.order = rules.DEFAULT_RUN_ORDER
        for runner in self.runners:
            runner.go()                      # 击出后默认全体前进：站着的人也立刻起跑
        self.plays += 1
        self.phase = 'flight'

    def _hit_runners(self) -> list[Runner]:
        """击球瞬间生成跑者：打者自动跑向一垒，被挤的人跟着跑，其余原地待命。"""
        need = rules.runner_ticks(self._runner_speed())
        forced = rules.forced_bases(self.bases)
        runners = [Runner.start(f'{rules.BASE_LABELS[base]}跑者', base, need,
                                forced=base in forced)
                   for base in sorted(self.bases)]
        runners.append(Runner.start('打者', 0, need, forced=True, batter=True))
        return runners

    def flight_step(self) -> None:
        """推进一拍：球正好前进一格，跑者同时往前跑；球到落点就判接球。"""
        landed = self.flight.advance()
        self._advance_runners()
        if landed:
            self._land()

    def set_run_order(self, order: str) -> bool:
        """进攻方的跑垒指令（光标落下就生效，随时可以改）。

        前进＝一个垒接一个垒往前跑，直到你改成别的、或跑回本垒；停止＝跑到下一个垒就站住
        （半路上的人先跑完这一段）；撤回＝半路上的人调头跑回刚离开的垒。
        接杀后的触垒窗口里它只有两种意思：前进＝冒险多进一个垒（高飞牺牲打，防守方会传杀），
        其余＝保持。盗垒不走这里：它随打击一起交牌。
        """
        if order not in rules.RUN_ORDERS:
            return False
        if self.phase == 'tag':
            return self._resolve_tag(order == 'go')
        if self.phase not in ('flight', 'ground', 'throw') or not self.runners:
            return False
        self.order = order
        for runner in self.runners:
            if not runner.live:
                continue
            if order == 'go':
                runner.go()
            elif order == 'stop':
                runner.halt()
            else:
                runner.retreat()
        return True

    def _push_runners(self) -> None:
        """球滚开：垒上所有人自动多跑一个垒（与指令无关的白送一垒）。"""
        for runner in self.runners:
            if runner.live:
                runner.push()

    @staticmethod
    def _left_early(runner: Runner) -> bool:
        """提前离垒的人：不是打者、已经离开了垒、又不是被挤着必须跑的那一段。

        球被接杀时，他们有被双杀的风险，也不能再借触垒窗口冒险。
        """
        return (not runner.batter and runner.live and not runner.settled
                and not runner.pinned)

    def _carry_steal(self) -> None:
        """球打进场内：盗垒的人一直在跑，击球这一刻已经到了下一个垒（不用再掷成功率）。

        击出后的跑者从这个新垒位起算；要是这一垒是本垒，这一分当场记下。
        """
        if not self.steal:
            return
        moved = {runner.origin for runner in self.runners}
        bases = []
        for base in sorted(self.bases):
            if base not in moved:
                bases.append(base)
                continue
            name = f'{rules.BASE_LABELS[base]}跑者'
            if base >= 3:
                self._add_runs(1)
                self._push('盗垒成功', f'{name}得分', self._score_text())
            else:
                bases.append(base + 1)
                self._push('盗垒成功', f'{name}上{rules.base_name(base + 1)}')
        self.bases = bases
        self.runners = []

    def _resolve_steal(self, hold: str) -> None:
        """盗垒结算：投球结果出来时，提前起跑的人要么上垒要么被触杀。

        盗垒不是被迫进垒，所以被抓是**触杀**（守方把球传到垒上时人还没回来）。
        投手这一球要是盯住了跑者，成功率会大幅下降（代价是分心、更好打）。
        """
        scope = self.steal
        self.steal = ''
        bases = sorted(self.bases)
        targets = bases if scope == 'all' else bases[-1:]
        chance = rules.steal_chance(self._runner_speed(), hold)
        for base in reversed(targets):          # 从最前面的人开始，垒位不会打架
            name = f'{rules.BASE_LABELS[base]}跑者'
            target = rules.base_name(base + 1)
            if self.rng.random() < chance:
                if base >= 3:
                    self._add_runs(1)
                    self._push('盗垒成功', f'{name}得分', self._score_text())
                else:
                    self._push('盗垒成功', f'{name}上{target}')
            else:
                self.outs += 1
                self._push('盗垒失败', '触杀', target, name,
                           self._outs_text())
                bases.remove(base)
        remaining = set(bases)
        for base in reversed(targets):
            if base not in remaining:
                continue
            target = base + 1
            while target in remaining:
                target += 1
            remaining.discard(base)
            if target <= 3:
                remaining.add(target)
        self.bases = sorted(remaining)
        self.runners = []

    def _land(self) -> None:
        flight = self.flight
        hit = flight.hit
        fielder = self.fielding_player()
        chaser = flight.fielder
        now = self.clock()
        position = chaser.position(now)
        airborne = chaser.airborne(now)
        result = rules.resolve_fielding(
            hit, position, airborne, self.attributes[fielder].fielder,
            self.shift[fielder], self.rng)
        facts = _fielding(hit, position, airborne,
                          chaser.jumped_at is not None)
        flight.done = True
        if result.homerun:
            # 飞出墙外：外野手接不到，垒上跑者与本垒打者一起得分。
            # 飞行状态先留着（球停在墙外），下一次投球时再清掉。
            self.verdict = 'homerun'
            self._homerun()
            return
        if not result.caught:
            # 落地不算安打：野手得跑到落点捡球，再决定传哪个垒。
            # 滚地球是地面球，野手拦下来还得传垒，打者要在一垒被封杀才算出去；
            # 而且**滚地是滚到野手脚下的**（不是飞过去让他追），所以捡球从他站的地方开始。
            self._push('滚地球' if hit.kind == 'ground' else '落地', *facts,
                       '失误' if result.error else '')
            self._hit_error = result.error
            self.flight = None
            self._start_ground(hit, result.error, chaser)
            return

        outs, call = rules.resolve_caught(
            any(self._left_early(runner) for runner in self.runners),
            sum(1 for runner in self.runners if not runner.batter),
            self.outs, self.attributes[fielder].fielder,
            self._runner_speed(), self.rng,
        )
        self.verdict = 'double_play' if outs >= 2 else 'catch_out'
        early = {runner.origin for runner in self.runners
                 if self._left_early(runner)}
        self._back_to_bases(outs)
        self.order = 'stop'
        self._push(call, *facts, self._outs_text())
        self.flight = None
        self.pending.clear()
        candidates = [runner for runner in self.runners
                      if not runner.batter and not runner.out
                      and runner.origin not in early]
        # 第三出局是打者（接杀）时，这一拍跑回来的分一律不算（美职棒记分规则）
        kill = self.outs >= OUTS_PER_HALF
        if candidates and not kill:
            # 触垒再进垒窗口：没提前离垒的人可以冒险多进一个垒（高飞牺牲打），
            # 防守方会马上把球传到他会去的那个垒。攻方可以不动（保持）。
            self.tag = Tag(cell=position, kind=hit.kind)
            self.phase = 'tag'
            return
        self._end_play(count_runs=not kill)

    def _resolve_tag(self, advance: bool) -> bool:
        """触垒进垒：最前面那个没提前离垒的跑者冒险多进一个垒，防守方传杀他。

        其余跑者跟着各进一个垒（防守方这次传球只够杀一个人）；不冒险＝保持，跑者返回原垒。
        """
        if self.phase != 'tag':
            return False
        tag = self.tag
        self.tag = None
        candidates = [runner for runner in self.runners
                      if not runner.batter and not runner.out]
        lead = max(candidates, key=lambda runner: runner.origin, default=None)
        if not advance or lead is None:
            self._end_play()
            return True
        for runner in candidates:
            if runner is not lead:
                runner.to = runner.origin + 1
                runner.progress = 0
                runner.need = 1                 # 防守方这次只够杀一个人
                runner.settled = False
        lead.to = lead.origin + 1
        lead.progress = 0
        lead.need = rules.runner_ticks(self._runner_speed())
        lead.settled = False
        base = rules.base_name(lead.to)
        distance = rules.throw_distance(tag.cell, tag.kind, base)
        ticks = rules.throw_ticks(distance, self._fielder().arm)
        self._push('触垒', f'{lead.name}冲{base}', f'{round(distance, 1)}米')
        self.throw = Throw(base, round(distance, 1), ticks, ticks)
        self.phase = 'throw'
        return True

    def _back_to_bases(self, outs: int) -> None:
        """接杀后：打者出局，其他人回原来的垒；双杀再带走一个提前离垒的人。"""
        doubled = next((runner for runner in self.runners
                        if self._left_early(runner)), None)
        if outs >= 2 and doubled is not None:
            doubled.out = True
            doubled.how = '回垒不及'
        for runner in self.runners:
            if runner.batter:
                runner.out = True
                runner.how = '接杀'
            elif not runner.out:
                runner.return_to_origin()
        self.outs += outs

    def _homerun(self) -> None:
        """全垒打：垒上所有人加打者一起得分，垒位清空（击出那一行已经说了全垒打）。"""
        runs = max(1, sum(1 for runner in self.runners if not runner.out))
        self._add_runs(runs)
        batter = self.stats[self.batting_player()]
        batter['homeruns'] += 1
        batter['hits'] += 1
        self.bases = []
        self.runners = []
        self.steal = ''
        self.pending.clear()
        self._push('全垒打', f'得分{runs}', self._score_text())
        self._after_play()

    # ── 捡球 → 传球 ──

    def _start_ground(self, hit: rules.HitBall, error: bool,
                      chaser: Fielder) -> None:
        """球落地：跑者接着跑（击球时就已经在跑），进入捡球阶段。

        滚地球是滚到野手脚下的，他站住就能捡；落地球他从当时的位置接着跑，
        朝球位跑到了就自动停住。
        """
        now = self.clock()
        if hit.kind == 'ground':
            chaser.place(float(hit.landing), now)
        chaser.retune(rules.ground_run_speed(self._fielder().speed),
                      float(hit.landing), now)
        self.ground = Pickup(hit=hit, fielder=chaser, error=error)
        if error:
            self._push_runners()              # 脱手：球滚开，垒上的人趁机多跑一个垒
        self.phase = 'ground'

    def ground_tick(self) -> None:
        """捡球阶段推进一拍（转传之后球已经在垒上，不需要再跑）。"""
        timed_out = self.ground.step()
        self._advance_runners()
        if self._play_over():
            self._end_play('跑者到垒')
        elif timed_out:
            self._end_play('守方控球')

    def _chaser(self) -> Fielder | None:
        """此刻场上能操作的野手（飞行中、捡球中；转传时球在垒上，没有）。"""
        if self.phase == 'flight':
            return self.flight.fielder
        if self.phase == 'ground':
            return self.ground.fielder
        return None

    def steer_fielder(self, heading: int) -> bool:
        """追球：按方向匀速跑（-1 左 / 0 站住 / 1 右）；方向没变返回 False。

        没有总量上限——想追就一直追，只是追不快（球比人快）。
        """
        chaser = self._chaser()
        return chaser is not None and chaser.steer(heading, self.clock())

    def chase_to(self, target: float) -> None:
        """机器野手：朝某一格跑，到了就停。"""
        chaser = self._chaser()
        if chaser is not None:
            chaser.run_to(target, self.clock())

    def jump_fielder(self) -> bool:
        """起跳：只在球还在飞时有用。空中那一段接球范围更大但更糙，球要正好在这时到；
        跳完要缓一缓才能再跑再跳。"""
        if self.phase != 'flight' or self.flight.done:
            return False
        return self.flight.fielder.jump(self.clock())

    def at_ball(self) -> bool:
        """野手是否已经拿到球（跑到了球位，或者转传时球在垒上）。"""
        return self.phase == 'ground' and self.ground.at_ball(self.clock())

    def throw_options(self) -> list[ThrowOption]:
        """可传的垒包与距离（米）——落点到各垒，或转传时从球所在的垒算。

        转传只列还有人被迫在跑的垒——球在垒上，随手传个空垒没有意义。
        """
        if self.phase != 'ground':
            return []
        if isinstance(self.ground, Relay):
            targets = [rules.base_name(base)
                       for base in self._forced_targets()]
        else:
            targets = rules.BASE_ORDER
        arm = self._fielder().arm
        options = []
        for base in targets:
            distance = self.ground.distance_to(base)
            options.append(ThrowOption(base, round(distance, 1),
                                       rules.throw_ticks(distance, arm)))
        return options

    def start_throw(self, base: str) -> bool:
        """把球传向某个垒包（必须已经站到球的位置，或球在垒上可以转传）。"""
        if (self.phase != 'ground' or not self.ground.at_ball(self.clock())
                or base not in rules.BASE_POSITIONS):
            return False
        distance = self.ground.distance_to(base)
        ticks = rules.throw_ticks(distance, self._fielder().arm)
        self.throw = Throw(base, round(distance, 1), ticks, ticks,
                           self.throw_options())
        self.ground = None
        self.phase = 'throw'
        self._push(f'传{base}', f'{round(distance, 1)}米')
        return True

    def throw_tick(self) -> None:
        """传球途中：每个 tick 跑者继续推进，球到垒时判定。"""
        self.throw.left -= 1
        self._advance_runners()
        if self.throw.left <= 0:
            self._resolve_throw(self.throw.base)

    def _resolve_throw(self, base: str) -> None:
        index = rules.base_number(base)
        target = next((runner for runner in self.runners
                       if runner.to == index and not runner.settled
                       and not runner.out), None)
        force = False
        if target is None:
            self.verdict = 'safe'
            result = [f'传{base}', '安全']
        else:
            force = index in self._forced_bases() and not target.back
            call = '封杀' if force else '触杀'
            target.out = True
            target.how = call
            self.outs += 1
            self.throw_outs += 1
            self.verdict = ('double_play' if self.throw_outs >= 2
                            else 'force_out' if force else 'tag_out')
            result = [call, base, target.name,
                      '双杀' if self.throw_outs >= 2 else '',
                      self._outs_text()]
        self.throw = None
        if self.outs >= OUTS_PER_HALF:
            # 第三出局是封杀或打者出局时这一拍跑回来的分不算（触杀算）
            self._end_play(*result, count_runs=not force)
            return
        if target is not None and self._forced_targets():
            # 还有人被迫在跑：球留在垒上，可以再传一次（连续双杀）
            self._push(*result)
            self.ground = Relay(base)
            self.phase = 'ground'
            return
        self._end_play(*result)

    def _forced_bases(self) -> set[int]:
        """还有人被迫在跑的垒包（被迫进垒关系用跑者身上的起点垒重建）。

        被迫进垒（打者把一垒的人挤到二垒、再挤下去，打者自己也算）→ 球先到垒就是封杀；
        不是被迫、自己多跑的（盗垒、多要一个垒）→ 只有触杀才算，球到垒时人还没回来才出局。
        """
        origins = sorted(runner.origin for runner in self.runners
                         if not runner.batter)
        return {base + 1 for base in rules.forced_bases(origins)} | {1}

    def _forced_targets(self) -> dict[int, Runner]:
        """还有哪些被迫在跑的人可以被传杀：目标垒包 → 那个跑者。"""
        found: dict[int, Runner] = {}
        for target in sorted(self._forced_bases()):
            runner = next((item for item in self.runners
                           if item.to == target and not item.settled
                           and not item.out and not item.back), None)
            if runner is not None:
                found[target] = runner
        return found

    def hold_ball(self) -> bool:
        """不传：直接把球控在内野，结束这次击球。"""
        if self.phase != 'ground':
            return False
        self._end_play('守方控球')
        return True

    def _advance_runners(self) -> None:
        for runner in self.runners:
            runner.step(self.order == 'go')

    def _play_over(self) -> bool:
        return all(runner.settled or runner.out for runner in self.runners)

    def _end_play(self, *lead: str, count_runs: bool = True) -> None:
        """结束这次击球：结算得分、把跑者记回 bases，播报一行结果。

        `lead` 是这一行开头的词组（传球结果、守方控球…）；后面接**还没说过的事**：
        接杀 / 封杀 / 触杀的出局在出局那一行里已经说了，原地没动的跑者也不用再提，
        剩下的就是谁上了哪个垒、谁得分、比分。
        `count_runs=False` 用于第三出局是打者出局或封杀的场合——这一拍跑回来的分不算。
        """
        runs = 0
        occupied: list[int] = []
        results: list[str] = []
        for runner in self.runners:
            name = runner.name
            if runner.out:
                if runner.how == '回垒不及':       # 双杀里被带走的那个人，出局行里没点他的名
                    results.append(f'{name}回垒不及')
                continue
            # 防守方不再争抢，跑者至少得到一个垒
            base = min(runner.to, runner.at + 1)
            if base >= rules.HOME:
                if count_runs:
                    runs += 1
                    results.append(f'{name}得分')
                else:
                    results.append(f'{name}回本垒不计分')
            elif base > 0:
                occupied.append(base)
                if base != runner.origin:
                    results.append(f'{name}上{rules.BASE_LABELS[base]}')
        if runs:
            self._add_runs(runs)
        self._push(*lead, *results, self._score_text() if runs else '')
        if (self.runners and not self._hit_error
                and self.outs == self._contact_outs
                and any(runner.batter and not runner.out
                        for runner in self.runners)):
            self.stats[self.batting_player()]['hits'] += 1   # 上垒又没人出局、没有失误＝安打
        self.bases = sorted(occupied)
        self.runners = []
        self.ground = None
        self.throw = None
        self.flight = None
        self.tag = None
        self.throw_outs = 0
        self.pending.clear()
        self._after_play()

    # ── 保送 / 换局 ──

    def _walk(self) -> None:
        starting_bases = sorted(self.bases)
        forced = rules.forced_bases(starting_bases)
        outcome = rules.place_runners(sorted(forced), batter_base=1, advance=1)
        held_bases = set(starting_bases) - forced
        self.bases = sorted(set(outcome.bases) | held_bases)
        if outcome.runs:
            self._add_runs(outcome.runs)
        # 打者上一垒是保送的题中之意（击球那一行已经写了「保送」），这里只说被挤动的人
        results = []
        for base in starting_bases:
            name = f'{rules.BASE_LABELS[base]}跑者'
            if base not in forced:
                continue
            if base + 1 > 3:
                results.append(f'{name}得分')
            else:
                results.append(f'{name}上{rules.BASE_LABELS[base + 1]}')
        self._push(*results, self._score_text() if outcome.runs else '')
        self._after_play()

    def _after_play(self) -> None:
        if self._walk_off():
            self._finish_walk_off()
            return
        if self.outs >= OUTS_PER_HALF:
            self._change_half()
            return
        self.balls = 0
        self.strikes = 0
        self.runners = []
        self.order = rules.DEFAULT_RUN_ORDER
        self.steal = ''
        self.ground = None
        self.throw = None
        self.phase = 'call'

    def _home_leads(self) -> bool:
        return (self.score[self.sides['home']]
                > self.score[self.sides['away']])

    def _walk_off(self) -> bool:
        """末局下半主队取得领先：比赛立刻结束（再见分），不必打满三个出局。"""
        return (self.innings >= self.total_innings and self.half == 'bottom'
                and self._home_leads())

    def _finish_walk_off(self) -> None:
        self._finish_early(f'第{self.innings}局下半 {self.batting_player()} '
                           f'取得领先 提前结束')

    def _change_half(self) -> None:
        self.outs = 0
        self.bases = []
        self.runners = []
        self.steal = ''
        self.ground = None
        self.throw = None
        self.tag = None
        self.throw_outs = 0
        self.flight = None
        self.delivery = None
        self.exchange = None
        self.countdown = 0
        self.verdict = ''
        self.last_ball = ''
        self.balls = 0
        self.strikes = 0
        self.pending.clear()
        if self.half == 'top':
            if self.innings >= self.total_innings and self._home_leads():
                self._finish_early(
                    f'第{self.innings}局上半 {self.sides["home"]} 已领先 '
                    f'不打下半局')
                return
            self.half = 'bottom'
        else:
            if self.innings >= self.total_innings:
                self._finish_match()
                return
            self.innings += 1
            self.half = 'top'
        self.line_score[self.batting_player()][self.innings - 1] = 0
        self._push('攻守交换',
                   f'第{self.innings}局{"上" if self.half == "top" else "下"}半',
                   f'{self.batting_player()} 进攻')
        self.phase = 'call'

    def _finish_early(self, reason: str) -> None:
        """不必打满的终局（下半局不进行 / 再见分）：先说明原因，再走统一的结算。"""
        self._push(reason)
        self._finish_match()

    def _finish_match(self) -> None:
        self.state = 'finished'
        self.phase = 'finished'
        away, home = self.sides['away'], self.sides['home']
        if self.score[away] == self.score[home]:
            self.winner = ''
            self._push('比赛结束', self._score_text(), '平手')
        else:
            self.winner = away if self.score[away] > self.score[home] else home
            self._push('比赛结束', self._score_text(), f'胜者 {self.winner}')

    def report_lines(self) -> list[str]:
        """终局战报：逐局比分和双方的安打 / 全垒打 / 保送 / 三振（一行一条，不含奖励）。"""
        lines = []
        for side, tag in (('away', '客'), ('home', '主')):
            player = self.sides[side]
            cells = ' '.join('X' if runs is None else str(runs)
                             for runs in self.line_score[player])
            lines.append(f'{tag} {player}  {cells} | {self.score[player]}')
        for side in ('away', 'home'):
            player = self.sides[side]
            stats = self.stats[player]
            lines.append(
                f'{player} 安打{stats["hits"]} 全垒打{stats["homeruns"]} '
                f'保送{stats["walks"]} 被三振{stats["strikeouts"]}')
        return lines

    # ── 计时 ──

    def next_tick(self) -> Tick | None:
        """下一拍的种类与时长；现在没有计时中的阶段就返回 None。"""
        if self.state != 'playing' or self.armed:
            return None
        if self.countdown > 0:
            return Tick('countdown', rules.COUNTDOWN_TICK_MS)
        if self.phase == 'delivery':
            return Tick('delivery', rules.ANIM_FRAME_MS)
        if self.phase == 'flight':
            return Tick('flight', self.flight.hit.tick_ms)
        if self.phase in ('ground', 'throw'):
            return Tick(self.phase, rules.TICK_MS)
        return None

    # ── 视图 ──

    def _runner_view(self) -> list[dict]:
        return [runner.view() for runner in self.runners]

    def _base_distances(self) -> dict[str, float]:
        """球被打出去之后：四个垒包各自的传球距离（米），给玩家提前判断该传哪。

        **用玩家看得见的那个球位算**：飞行阶段用落点范围的正中，不是真实落点——
        真实落点是要保密的信息（范围一路收窄、到落点才收成一点），拿它算距离等于把落点卖了。
        球还没被打出去（或这一球已经结束）时返回空，棋盘上的垒名行就不显示距离。
        """
        if self.flight and not self.flight.done:
            hit = self.flight.hit
            estimate = self.flight.estimate()
            return {base: round(rules.throw_distance(estimate, hit.kind, base), 1)
                    for base in rules.BASE_ORDER}
        if isinstance(self.ground, Pickup):
            return {base: round(self.ground.distance_to(base), 1)
                    for base in rules.BASE_ORDER}
        if self.throw:
            return {option.base: option.distance
                    for option in self.throw.options}
        return {}

    def _view(self, viewer: str) -> dict:
        fielding = self.fielding_player()
        now = self.clock()
        ground = (self.ground.view(self.throw_options(), now)
                  if self.ground else None)
        tick = self.next_tick()
        return {
            'game_type': 'baseball',
            'room_state': self.state,
            # 距离下一拍多久：客户端按它把这一拍摊成连续滑动（没有计时中的阶段就是一个标准拍）
            'tick_ms': tick.ms if tick else rules.TICK_MS,
            'run_order': self.order,
            'innings': self.innings,
            'total_innings': self.total_innings,
            'line_score': {side: list(self.line_score[self.sides[side]])
                           for side in ('away', 'home')},
            'half': self.half,
            'outs': self.outs,
            'bases': list(self.bases),
            'balls': self.balls,
            'strikes': self.strikes,
            'score': dict(self.score),
            'away': self.sides['away'],
            'home': self.sides['home'],
            'batting': self.batting_player(),
            'fielding': fielding,
            'phase': self.phase,
            'viewer_side': ('batting' if viewer == self.batting_player()
                            else 'fielding'),
            'shift': self.shift[fielding],
            'shift_label': rules.SHIFT_LABELS[self.shift[fielding]],
            'field_start': rules.shift_start(self.shift[fielding]),
            'cells': rules.FIELD_CELLS,
            'stamina': self.stamina[fielding],
            'winner': self.winner,
            'players': list(self.players),
            'flight': self.flight.view(now) if self.flight else None,
            'runners': self._runner_view(),
            'ready': self.ready_sides(),
            'countdown': self.countdown,
            'armed': self.armed,
            'base_distances': self._base_distances(),
            'verdict': self.verdict,
            'last_ball': self.last_ball,
            'delivery': self.delivery.view() if self.delivery else None,
            'ground': ground,
            'throw': self.throw.view() if self.throw else None,
            'labels': _LABELS,
            'timing_cuts': _TIMING_CUTS,
            'history': [record.view() for record in self.history],
            'attributes': self.attributes[viewer].view(),
        }

    def get_game_data(self, viewer: str | None = None) -> dict:
        if self.state == 'waiting':
            return self.get_table_data()
        return self._view(viewer or self.players[0])

    def get_table_data(self) -> dict:
        return {
            'game_type': 'baseball',
            'room_state': self.state,
            'room_id': self.room_id,
            'host': self.host,
            'players': list(self.players),
            'max_players': self.max_players,
            'ready': sorted(self.ready),
            'bots': sorted(self.bots),
            'summary': [['局数', f'{self.total_innings} 局']],
        }
