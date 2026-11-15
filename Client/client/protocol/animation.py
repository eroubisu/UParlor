"""游戏动画的共用件：按名字登记的数值滑动，加一条每帧一次的计时链。

服务端是离散的一拍一拍；客户端把每一拍摊成约 30fps 的连续滑动。滑动按**时间**走
（拍长 = 滑动时长），所以整段动画正好在服务端下一拍到来之前走完，不会提前停住干等，
也不会因为计时器抖动而越走越慢。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

FRAME_SECONDS = 1 / 30      # 约 30fps：再快终端也画不出来，白烧 CPU


@dataclass
class _Glide:
    start: float
    end: float
    began: float       # 开始滑动的时刻（秒）
    seconds: float


class Animator:
    """一组按名字登记的数值：`values[name]` 是此刻的当前值，`advance` 每帧推进一次。"""

    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.looping = False                  # 每帧计时链是否正在跑（防止重复起链）
        self._targets: dict[str, float] = {}
        self._glides: dict[str, _Glide] = {}

    @property
    def moving(self) -> bool:
        return bool(self._glides)

    def glide(self, name: str, target: float, seconds: float, now: float,
              origin: float | None = None) -> None:
        """从当前值滑向 target；目标没变就什么都不做。

        第一次出现的值没有"当前值"：从 `origin` 起滑（没给就直接站在目标上）。
        """
        if self._targets.get(name) == target:
            return
        start = self.values.get(name, target if origin is None else origin)
        self._targets[name] = target
        if seconds <= 0 or start == target:
            self.snap(name, target)
            return
        self.values[name] = start
        self._glides[name] = _Glide(start, target, now, seconds)

    def snap(self, name: str, value: float) -> None:
        """立刻站到 value 上，正在进行的滑动作废。"""
        self.values[name] = self._targets[name] = value
        self._glides.pop(name, None)

    def forget(self, name: str) -> None:
        for table in (self.values, self._targets, self._glides):
            table.pop(name, None)

    def forget_missing(self, prefix: str, keep: set[str]) -> None:
        """清掉 `prefix` 开头、但不在 keep 里的值（比如已经不存在的跑者）。"""
        for name in [n for n in self.values
                     if n.startswith(prefix) and n not in keep]:
            self.forget(name)

    def advance(self, now: float) -> bool:
        """推进到 now；返回是否还有值在滑动。"""
        for name, glide in list(self._glides.items()):
            ratio = (now - glide.began) / glide.seconds
            if ratio >= 1:
                self.values[name] = glide.end
                del self._glides[name]
            else:
                self.values[name] = (glide.start
                                     + (glide.end - glide.start)
                                     * max(0.0, ratio))
        return self.moving


def start_frames(ctx, game_type: str,
                 advance: Callable[[dict], bool]) -> None:
    """从现在起每帧调用一次 `advance(交互状态快照)`，它返回 False 就停。

    交互上下文一换（`generation` 变了，比如退出游戏）旧的计时链自动作废。
    """
    interaction = ctx.state.game_interaction
    generation = interaction.generation(game_type)

    def frame() -> None:
        if interaction.generation(game_type) != generation:
            return
        snapshot = interaction.snapshot(game_type)
        if snapshot is None:
            return
        moving = advance(snapshot)
        interaction.replace(game_type, snapshot)
        if moving:
            ctx.set_timer(FRAME_SECONDS, frame)

    ctx.set_timer(FRAME_SECONDS, frame)
