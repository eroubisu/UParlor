# _cjk_patch.py -- Fix CJK double-width character rendering in Textual compositor
#
# Upstream issue: https://github.com/Textualize/textual/issues/6357
# Reference fix:  https://github.com/0x7c13/textual/pull/1
# Workaround by:  @kaaass (https://github.com/kaaass)
# Based on Textual version: 8.1.1

"""Monkey-patch Textual compositor to fix CJK characters disappearing in overlays.

When an overlay widget (tooltip, Select dropdown, toast) overlaps an underlying
widget's border, the compositor's cut system divides rendering strips at every
widget boundary.  ``Segment.split_cells()`` replaces double-width CJK characters
that straddle a cut position with two spaces, causing them to vanish.

The fix filters out "internal cuts" -- cut positions where the current (highest-
priority) widget wins both adjacent chop buckets -- before calling
``strip.divide()``, so CJK characters are never split unnecessarily.  Skipped
bucket positions receive a zero-width placeholder to prevent lower-priority
widgets from claiming them.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Sequence, cast

from textual.geometry import Region
from textual.strip import Strip

if TYPE_CHECKING:
    from textual._compositor import Compositor

_PLACEHOLDER = Strip([], 0)


def _patched_render_chops(
    self: Compositor,
    crop: Region,
    is_rendered_line: Callable[[int], bool],
) -> Sequence[Mapping[int, Strip]]:
    cuts = self.cuts
    fromkeys = cast("Callable[[list[int]], dict[int, Strip | None]]", dict.fromkeys)
    chops: list[dict[int, Strip | None]]
    chops = [fromkeys(cut_set[:-1]) for cut_set in cuts]

    cut_strips: Iterable[Strip]

    renders = self._get_renders(crop)
    intersection = Region.intersection

    _bisect_left = bisect_left
    _bisect_right = bisect_right

    for region, clip, strips in renders:
        render_region = intersection(region, clip)
        render_x = render_region.x
        first_cut, last_cut = render_region.column_span

        for y, strip in zip(render_region.line_range, strips):
            if not is_rendered_line(y):
                continue

            chops_line = chops[y]

            line_cuts = cuts[y]
            lo = _bisect_left(line_cuts, first_cut)
            hi = _bisect_right(line_cuts, last_cut)
            final_cuts = line_cuts[lo:hi]

            if len(final_cuts) < 2:
                continue

            get = chops_line.get
            effective = [final_cuts[0]]
            for i in range(1, len(final_cuts) - 1):
                if get(final_cuts[i - 1]) is not None or get(final_cuts[i]) is not None:
                    effective.append(final_cuts[i])
            effective.append(final_cuts[-1])

            cut_strips = strip.divide([c - render_x for c in effective[1:]])

            eff_idx = 0
            eff_iter = iter(cut_strips)
            for cut in final_cuts[:-1]:
                if eff_idx < len(effective) - 1 and cut == effective[eff_idx]:
                    part = next(eff_iter, None)
                    if part is None:
                        break
                    eff_idx += 1
                    if get(cut) is None:
                        chops_line[cut] = part
                else:
                    if get(cut) is None:
                        chops_line[cut] = _PLACEHOLDER

    return cast("Sequence[Mapping[int, Strip]]", chops)


def apply() -> None:
    """Apply the CJK rendering fix.  Call once before TUI startup."""
    from textual._compositor import Compositor

    Compositor._render_chops = _patched_render_chops  # type: ignore[assignment]
