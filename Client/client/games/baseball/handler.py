"""棒球客户端处理器 — 棋盘下方的操作区 + 球的平滑动画。

操作区是一级盘（本次行动的设置项 / 按钮盘）加二级菜单（选值，最后一项固定是「返回」）；
最后一项「确定」会再问一次，确认后才发完整指令。飞行与捡球阶段换成按钮盘：方向键仍然只挪光标，
光标落到哪个按钮、那个按钮的策略才生效（传垒不可撤销，仍然要回车）。
服务端每一拍给一次位置，客户端把这一拍摊成连续滑动（服务端仍是唯一权威）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ...protocol.animation import Animator, start_frames
from ...protocol.handler import GameHandlerContext, register_handler
from .controls import MODE_ACT, MODE_IDLE, Controls, Form, Item
from .view import Board


@dataclass
class Ui:
    """交互状态：处理器写、渲染器读（框架按字典存，键是 `'ui'`）。"""

    board: Board                   # 操作区是照它搭的：回车时按同一份局面算指令
    form: Form
    controls: Controls = field(default_factory=Controls)
    anim: Animator = field(default_factory=Animator)
    waiting: bool = False          # 刚发过一条不可撤销的指令：等服务端回执，期间不再响应
    shift_unsent: bool = False     # 预告期间挑的布阵：守方开始下一球时再同步给服务端
    pressed: bool = False          # 自己已按下击球、回执还在路上：先按「已挥棒」画到这一球结束
    delivery_stage: str = ''


class BaseballHandler:
    """把棒球事件转换为当前 ModuleStateManager 的 State 变更。"""

    game_type = 'baseball'
    clock = staticmethod(time.monotonic)

    def companion_events(self, previous: dict, current: dict, player: str
                         ) -> list[str]:
        events = []
        if (previous.get('room_state') != 'finished'
                and current['room_state'] == 'finished'):
            events.append('玩家赢得棒球比赛' if current['winner'] == player
                          else '棒球比赛结束')
        return events

    def handle_event(self, event: str, data: dict,
                     ctx: GameHandlerContext) -> bool:
        if event != 'select_menu':
            return False
        # 玩法菜单由客户端按阶段自己生成；这里只会是房间级确认菜单（放弃）
        ctx.show_select_menu(
            title=data['title'], items=data['items'],
            empty_msg=data['empty_msg'],
        )
        return True

    # ── 交互状态的存取 ──

    def _ui(self, ctx: GameHandlerContext) -> Ui | None:
        snapshot = ctx.state.game_interaction.snapshot(self.game_type)
        return snapshot['ui'] if snapshot else None

    def _store(self, ctx: GameHandlerContext, ui: Ui) -> None:
        ctx.state.game_interaction.replace(self.game_type, {'ui': ui})

    # ── 房间状态刷新 ──

    def on_room_update(self, room_data: dict,
                       ctx: GameHandlerContext) -> None:
        if room_data['room_state'] not in ('playing', 'finished'):
            ctx.state.game_interaction.reset(self.game_type)
            return
        board = Board.parse(room_data)
        ui = self._ui(ctx) or Ui(board, Form.initial(board))
        if board.delivery is None:
            ui.pressed = False
        elif ui.pressed:
            board = board.with_swing()
        ui.board = board
        ui.waiting = False
        if board.finished:                     # 结算后画面停在最后一帧，操作区清空
            ui.controls = Controls()
            self._store(ctx, ui)
            return
        ui.controls.sync(board, ui.form)
        self._sync_shift(board, ui, ctx)
        self._sync_animations(board, ui)
        starts_loop = ui.anim.moving and not ui.anim.looping
        if starts_loop:
            ui.anim.looping = True
        self._store(ctx, ui)
        if starts_loop:
            start_frames(ctx, self.game_type, self._advance)

    def _sync_shift(self, board: Board, ui: Ui,
                    ctx: GameHandlerContext) -> None:
        """预告期间挑的布阵，等守方真的开始下一球就同步给服务端。"""
        if (ui.shift_unsent and board.fielding_side and board.phase == 'call'
                and not board.ready_fielding):
            ui.shift_unsent = False
            ctx.send_command(f'/shift {ui.form.shift}')

    # ── 动画：画面球位＝服务端真实位置，只晚一个网络延迟 ──
    # 服务端每一拍把东西挪一步；客户端收到时就朝"下一拍的位置"滑，滑完正好下一拍到来。
    # 球出手 / 击出的瞬间就开始动，落地也不会在最后一格突然跳一下
    # （只往前看一步，真实落点依旧保密：球走到哪一拍，画面才走到哪）。
    # 野手不一样：他是玩家自己按出来的，服务端给的是位置、方向和速度，客户端按时间匀速滑。

    def _sync_animations(self, board: Board, ui: Ui) -> None:
        anim = ui.anim
        now = self.clock()
        seconds = board.tick_ms / 1000
        flight = board.flight

        if board.phase == 'flight' and flight and not flight.done:
            anim.glide('ball', float(flight.ball + 1), seconds, now,
                       origin=float(flight.ball))
            self._shrink_span(flight, anim, seconds, now)
        else:
            anim.forget('ball')
            for name in ('span_low', 'span_high'):
                anim.forget(name)

        self._sync_fielder(board, anim, now)

        # 新出现的跑者从当前进度起滑；已经在走的从当前位置接着走
        names = set()
        for runner in board.runners:
            name = f'runner:{runner.key}'
            names.add(name)
            anim.glide(name, runner.lead_ratio, seconds, now,
                       origin=runner.ratio)
        anim.forget_missing('runner:', names)

        delivery = board.delivery if board.phase == 'delivery' else None
        if delivery is None:
            ui.delivery_stage = ''
            anim.forget('delivery')
        else:
            if delivery.stage != ui.delivery_stage:     # 换段：帧号归零，动画从头
                ui.delivery_stage = delivery.stage
                anim.snap('delivery', float(delivery.frame))
            anim.glide('delivery',
                       float(min(delivery.frame + 1, delivery.frames)),
                       seconds, now, origin=float(delivery.frame))

        if board.phase == 'throw' and board.throw:
            throw = board.throw
            anim.glide('throw', float(min(throw.done + 1, throw.ticks)),
                       seconds, now, origin=float(throw.done))
        else:
            anim.forget('throw')

    def _shrink_span(self, flight, anim: Animator, seconds: float,
                     now: float) -> None:
        """落点范围这一拍往下一拍的窄范围滑：球飞近的过程里它一路收窄。"""
        for name, current, upcoming in (
                ('span_low', flight.span[0], flight.span_next[0]),
                ('span_high', flight.span[1], flight.span_next[1])):
            anim.glide(name, upcoming, seconds, now, origin=current)

    def _sync_fielder(self, board: Board, anim: Animator, now: float) -> None:
        """野手从服务端报的位置出发，按方向与速度匀速滑；起跳的空中 / 缓冲倒计时也在这里。"""
        fielder = board.fielder
        if fielder is None:
            for name in ('field', 'air', 'lock'):
                anim.forget(name)
            return
        anim.snap('field', fielder.pos)
        target = fielder.destination(board.cells)
        if target != fielder.pos:
            # 缓冲期间不动，缓冲完才开始跑
            anim.glide('field', target,
                       abs(target - fielder.pos) / fielder.speed,
                       now + fielder.lock)
        for name, left in (('air', fielder.air), ('lock', fielder.lock)):
            if left > 0:
                anim.snap(name, left)
                anim.glide(name, 0.0, left, now)
            else:
                anim.forget(name)

    def _advance(self, snapshot: dict) -> bool:
        """动画帧：把所有在滑的值推进到此刻；画面上的野手一跑到球位就先换成传球菜单。"""
        ui = snapshot['ui']
        ui.anim.looping = ui.anim.advance(self.clock())
        ground = ui.board.ground
        if (ui.board.phase == 'ground' and ground and not ground.at_ball
                and ui.anim.values.get('field') == ground.ball):
            ui.board = ui.board.with_arrival()
            ui.controls.sync(ui.board, ui.form)
        return ui.anim.looping

    # ── 菜单导航 ──

    def on_nav(self, direction: str, ctx: GameHandlerContext) -> None:
        ui = self._ui(ctx)
        if ui is None or ui.waiting or ui.controls.mode == MODE_IDLE:
            return
        controls = ui.controls
        if direction == 'enter':
            item = controls.enter(controls.mode, ui.board, ui.form)
            if item is not None:
                self._press(item, ui, ctx)
        else:
            item = controls.navigate(direction, controls.mode)
            if item is not None:
                self._fire(item, ui, ctx)
        self._store(ctx, ui)

    def _fire(self, item: Item, ui: Ui, ctx: GameHandlerContext) -> None:
        """选中即执行：光标落下的按钮立刻生效，不用回车。"""
        if item.move is None:
            ctx.send_command(item.command)
            return
        # 追球是「一直往那边跑」，直到你选「停止」——不是走一格就完
        ui.controls.move = item.move
        ctx.send_command(f'/field {item.move or "stop"}')

    def _press(self, item: Item, ui: Ui, ctx: GameHandlerContext) -> None:
        """回车按下了一项：击球 / 投球 / 布阵 / 一条完整指令。"""
        controls = ui.controls
        if item.action == 'hit':
            # 把客户端插值出来的这一帧报上去（延迟参考），时机档由服务端校验后定档
            ctx.send_command(f'/hit {ui.anim.values["delivery"]:.2f}')
            controls.after_hit()
            ui.pressed = True                      # 挥棒点不等回执，按下就亮
            ui.board = ui.board.with_swing()
        elif item.action == 'release':
            ctx.send_command('/release')           # 只是投出的确认，不看时机
            ui.waiting = True
        elif item.action == 'set':                 # 只有布阵会走到这里：不消耗行动
            if controls.mode == MODE_ACT:
                ctx.send_command(f'/shift {item.value}')
            else:
                ui.shift_unsent = True
        else:
            if item.command:                       # 捡球时的移动键没有回车动作
                ctx.send_command(item.command)
            if not item.fires_on_cursor:
                ui.waiting = True
            if item.action == 'submit':
                controls.rest_on_submit = True
            # 从子菜单里发出的动作（「确定 → 是」）发完就回到当前阶段的菜单：
            # 定完还停在"是/否"上既看不到下一步，也挡着操作（用户 2026-10-15 要求）
            if controls.stack:
                controls.close_to_root()


register_handler(BaseballHandler())
