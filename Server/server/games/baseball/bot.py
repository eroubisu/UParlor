"""棒球机器人的决策。

只读房间、只调用房间公开的动作；网络、计时与加锁由 engine.BaseballScheduler 负责。
机器人防守故意偏弱（见 game-design-principles 的 Bot behaviour）：
滚地球基本打法是传一垒，偶尔抓双杀、偶尔控球不传、偶尔看错落点。
"""

from __future__ import annotations

from . import rules
from .room import OUTS_PER_HALF, BaseballRoom

# 机器人按键的帧位：按它读出来的时机档选一个比例 × 投球段总帧数
PRESS_RATIO = {'early': 0.2, 'normal': 0.6, 'late': 0.9}


class BaseballBot:
    """一个调度器共用一个：每个决策方法都带上房间，只有"打算在第几帧击球"记在这里。"""

    def __init__(self) -> None:
        self._press_frame: dict[str, float] = {}
        self._decided: dict[str, int] = {}   # 房间 → 最近一次改过主意是第几次击球

    # ── 出牌阶段 ──

    def submit(self, room: BaseballRoom, name: str) -> None:
        """交牌：机器人当守方就投球（顺手可能换布阵），当攻方就打击。"""
        rng = room.rng
        if name == room.fielding_player():
            if rng.random() < 0.5:
                room.set_shift(name, self._pick_shift(room))
            room.set_pitch(name, self._pick_pitch(room))
            return
        call = self._pick_swing(room)
        self._plan_press(room, name, call)
        room.set_swing(name, call)

    def _pick_shift(self, room: BaseballRoom) -> str:
        pulls = sum(1 for record in room.history[-4:]
                    if record.pitch.band == 'inside')
        if pulls >= 2:
            return room.rng.choice(('right', 'left'))
        return room.rng.choice(('standard', 'standard', 'infield', 'deep'))

    def _pick_pitch(self, room: BaseballRoom) -> rules.PitchCall:
        """选球种：偏好最快的球，领先球数靠滑球/指叉找挥空，累了改用省力球种。"""
        rng = room.rng
        ahead = room.strikes >= 2
        band = 'outside' if rng.random() < (0.35 if ahead else 0.18) else (
            'inside' if rng.random() < 0.45 else 'edge')
        effort = 'full' if (ahead and rng.random() < 0.5) else 'normal'
        recent = {record.pitch.pitch_type for record in room.history[-3:]}
        choices = [t for t in rules.PITCH_TYPES if t not in recent] \
            or list(rules.PITCH_TYPES)
        tired = room.stamina[room.fielding_player()] <= 45
        weights = []
        for pitch_type in choices:
            weight = 3 if pitch_type == 'four_seam' else 2
            if ahead and pitch_type in ('slider', 'splitter'):
                weight += 2                    # 两好球：拿变化大的球找挥空
            if tired and pitch_type in ('changeup', 'cutter'):
                weight += 2                    # 累了就投省力的球
            weights.append(weight)
        # 垒上有人时偶尔盯一下跑者（机器人保持弱度，不做最优解）
        hold = 'yes' if room.bases and rng.random() < 0.35 else 'no'
        pitch_type = rng.choices(choices, weights)[0]
        return rules.PitchCall(pitch_type, band, effort, hold)

    def _pick_swing(self, room: BaseballRoom) -> rules.SwingCall:
        """选挥棒：三垒有人时压滚地球换分，两好球时收着打（要碰到球）；顺手决定盗不盗垒。"""
        rng = room.rng
        recent = room.history[-6:]
        counts = {t: 0 for t in rules.PITCH_TYPES}
        for record in recent:
            counts[record.pitch.pitch_type] += 1
        guess = max(counts, key=counts.get) if recent else rng.choice(
            rules.PITCH_TYPES)
        if rng.random() < 0.3:
            guess = rng.choice(rules.PITCH_TYPES)
        if 3 in room.bases and room.outs < 2 and rng.random() < 0.45:
            swing = 'ground'                   # 三垒有人：压滚地球，多半换一分
        elif room.strikes >= 2:
            swing = 'standard' if rng.random() < 0.7 else 'power'
        else:
            swing = rng.choice(('standard', 'standard', 'power', 'ground'))
        return rules.SwingCall(guess, swing, steal=self._pick_steal(room))

    @staticmethod
    def _pick_steal(room: BaseballRoom) -> str:
        """两出局前偶尔起跑盗垒（球数落后时更谨慎）。"""
        if not room.bases:
            return 'hold'
        rng = room.rng
        if rng.random() >= (0.30 if room.balls < 2 else 0.15):
            return 'hold'
        return 'all' if len(room.bases) > 1 and rng.random() < 0.3 else 'lead'

    def _plan_press(self, room: BaseballRoom, name: str,
                    call: rules.SwingCall) -> None:
        """机器人也要"看球按键"：按它读出来的时机档挑一个帧按下去，手上还有点抖。"""
        full = any(record.pitch.effort == 'full' for record in room.history[-2:])
        timing = rules.expected_timing(call.guess, 'full' if full else 'normal')
        target = PRESS_RATIO[timing] * rules.PITCH_ANIM_FRAMES
        self._press_frame[name] = target + room.rng.randint(-1, 1)

    # ── 投打动画 ──

    def press(self, room: BaseballRoom) -> None:
        """投球段里让机器人按时按下击球（打者不是机器人就不管）。"""
        batter = room.batting_player()
        target = self._press_frame.get(batter)
        if target is None or not room.is_bot(batter):
            return
        frame = float(room.delivery.frame)
        if frame >= target:
            del self._press_frame[batter]
            room.swing_now(batter, frame)

    # ── 击出之后 ──

    @staticmethod
    def field(room: BaseballRoom) -> None:
        """机器野手：朝落点范围的正中跑；球到之前的最后一次决策，够不着就起跳。"""
        flight = room.flight
        rng = room.rng
        target = flight.estimate()
        if rng.random() < 0.15:            # 偶尔看错落点
            target = max(1, min(rules.FIELD_CELLS,
                                target + rng.choice((-2, -1, 1, 2))))
        room.chase_to(target)
        gap = abs(flight.fielder.position(room.clock()) - target)
        if (flight.tick >= flight.hit.ticks - 1
                and gap > rules.BASE_COVERAGE / 2 and rng.random() < 0.75):
            room.jump_fielder()

    @staticmethod
    def ground(room: BaseballRoom) -> None:
        """机器野手捡球：朝球跑，跑到球上就传垒。

        滚地球的基本打法是**传一垒**（打者封杀）；垒上有人又在跑、而且不足两人出局时
        偶尔先传二垒抓双杀。机器人不优化，但不会在滚地球里乱传别的垒——
        那样等于白送一个上垒（用户 2026-10-15 纠正"滚地球不能接杀"之后必须这么收）。
        """
        pickup = room.ground
        if not room.at_ball():
            room.chase_to(pickup.ball)
            return
        bases = [option.base for option in room.throw_options()]
        rng = room.rng
        if not bases or rng.random() < 0.25:
            room.hold_ball()
        elif (1 in room.bases and room.outs < 2 and '二垒' in bases
                and rng.random() < 0.4):
            room.start_throw('二垒')          # 试着抓双杀
        elif '一垒' in bases:
            room.start_throw('一垒')          # 打者的封杀
        else:
            room.start_throw(rng.choice(bases))

    def run(self, room: BaseballRoom) -> None:
        """机器跑者：击出后默认全体前进；机器人每次击球只改一次主意。

        多数时候第一拍就叫「停止」，把站着的人留在垒上（只有被挤着的人跑到下一个垒）；
        落后时更敢派人，派出去的人一拍之后叫停，到下一个垒就站住。
        """
        if not room.runners:
            return
        if self._decided.get(room.room_id) != room.plays:
            self._decided[room.room_id] = room.plays
            if room.rng.random() >= (0.35 if room.outs < 2 else 0.15):
                room.set_run_order('stop')
        elif room.order == 'go':
            room.set_run_order('stop')

    @staticmethod
    def tag(room: BaseballRoom) -> None:
        """机器跑者：接杀后还没两出局就敢冒险多进一个垒（高飞牺牲打）。

        必须选一个：不选的话这一拍没人推进，攻方是人类时也一样（等人按菜单）。
        """
        risk = 0.5 if room.outs < OUTS_PER_HALF - 1 else 0.1
        room.set_run_order('go' if room.rng.random() < risk else 'stop')
