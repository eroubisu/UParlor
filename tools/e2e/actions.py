"""actions.py — 操作原语：全部通过 pilot.press() 实现"""

from __future__ import annotations

import asyncio
from typing import Callable


# ── 等待工具 ──

async def wait_for(pilot, check_fn: Callable, timeout: float = 10, interval: float = 0.3):
    """轮询等待条件满足，超时则断言失败"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        await pilot.pause(interval)
        if check_fn():
            return
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"wait_for 超时 ({timeout}s): {check_fn.__name__}")


# ── 文本输入 ──

async def type_text(pilot, text: str):
    """逐字符输入文本"""
    for ch in text:
        await pilot.press(ch)
    await pilot.pause(0.05)


# ── 登录 ──

async def login(pilot, username: str = "", password: str = ""):
    """完整登录流程：输入用户名→回车→输入密码→回车→等待成功

    登录面板启动时已自动进入 INSERT 模式，无需额外按 i。
    用户名/密码默认从 app._e2e_username/_e2e_password 读取（由 harness 设置）。
    """
    from .checks import is_logged_in

    app = pilot.app
    username = username or getattr(app, '_e2e_username', 'e2e1')
    password = password or getattr(app, '_e2e_password', 'test123')
    # 等待屏幕加载 + 服务器连接建立 + 收到初始 login_prompt
    await pilot.pause(1.5)

    # 已在 INSERT 模式，直接输入用户名
    await type_text(pilot, username)
    await pilot.press("enter")
    await pilot.pause(1.0)

    # 服务器提示输入密码，输入密码
    await type_text(pilot, password)
    await pilot.press("enter")

    # 等待登录成功
    await wait_for(pilot, lambda: is_logged_in(app), timeout=10)


# ── Vim 模式 ──

async def enter_insert(pilot, sticky: bool = False):
    """进入 INSERT 模式"""
    await pilot.press("I" if sticky else "i")
    await pilot.pause(0.1)


async def exit_insert(pilot):
    """退出到 NORMAL 模式"""
    await pilot.press("escape")
    await pilot.pause(0.1)


# ── 指令菜单 ──

async def open_menu(pilot):
    """打开指令菜单 (p)，如果已打开则跳过"""
    app = pilot.app
    if getattr(app.screen, '_cmd_select_mode', False):
        return
    await pilot.press("p")
    await pilot.pause(0.2)


async def close_menu(pilot):
    """关闭指令菜单 (escape)"""
    await pilot.press("escape")
    await pilot.pause(0.1)


async def menu_nav(pilot, direction: str, count: int = 1):
    """在菜单中导航 (J/K/H/L 或 w/a/s/d)"""
    key_map = {"up": "k", "down": "j", "left": "h", "right": "l"}
    key = key_map.get(direction, direction)
    for _ in range(count):
        await pilot.press(key)
        await pilot.pause(0.05)


async def menu_select(pilot, label: str):
    """在 hint bar 中通过导航选中目标项并回车。

    CMD_SELECT 模式下 wasd 被截获为导航键，不能用 type_text 过滤。
    改用 L/H 切换 tab、J/K 选择 item、Enter 确认。
    """
    app = pilot.app
    board = app.screen.get_module('game_board')
    if not board:
        raise RuntimeError("menu_select: game_board not found")
    bar = board._hint_bar()
    if not bar:
        raise RuntimeError("menu_select: hint_bar not found")

    target = label.lower()

    # 在子菜单模式中，直接在 _current_items 里找
    if bar._nav_stack:
        items = bar._current_items()
        idx = _find_item_index(bar, items, target)
        if idx is None:
            names = [bar._item_name(it) for it in items]
            raise RuntimeError(f"menu_select: '{label}' not in sub-menu {names}")
        for _ in range(idx - bar._selected_idx):
            await pilot.press("J")
            await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.2)
        return

    # 根模式：找到包含目标的 tab 和 item index
    for tab_i, (_, tab_items) in enumerate(bar._tabs):
        idx = _find_item_index(bar, tab_items, target)
        if idx is not None:
            # 导航到目标 tab
            moves = (tab_i - bar._active_tab) % len(bar._tabs)
            for _ in range(moves):
                await pilot.press("L")
                await pilot.pause(0.05)
            # 导航到目标 item
            for _ in range(idx):
                await pilot.press("J")
                await pilot.pause(0.05)
            await pilot.press("enter")
            await pilot.pause(0.2)
            return
    # 未找到
    all_names = []
    for _, tab_items in bar._tabs:
        all_names.extend(bar._item_name(it) for it in tab_items)
    raise RuntimeError(f"menu_select: '{label}' not in tabs {all_names}")


def _find_item_index(bar, items, target: str):
    """在 items 列表中找到 target 的索引。先精确匹配，再部分匹配。"""
    # 精确匹配
    for i, it in enumerate(items):
        if bar._item_name(it).lower() == target:
            return i
    # 部分匹配（target 包含在 item name 中）
    for i, it in enumerate(items):
        if target in bar._item_name(it).lower():
            return i
    return None


# ── 面板导航 ──

async def nav(pilot, direction: str, count: int = 1):
    """面板内导航 (hjkl)"""
    key_map = {"left": "h", "down": "j", "up": "k", "right": "l"}
    key = key_map.get(direction, direction)
    for _ in range(count):
        await pilot.press(key)
        await pilot.pause(0.05)


async def nav_outer(pilot, direction: str, count: int = 1):
    """面板间切换 (HJKL)"""
    key_map = {"left": "H", "down": "J", "up": "K", "right": "L"}
    key = key_map.get(direction, direction)
    for _ in range(count):
        await pilot.press(key)
        await pilot.pause(0.05)


# ── 指令输入 ──

async def send_command(pilot, cmd: str):
    """模拟用户输入指令：i → 输入 → 回车"""
    await pilot.press("i")
    await pilot.pause(0.1)
    await type_text(pilot, cmd)
    await pilot.press("enter")
    await pilot.pause(0.3)


# ── Space 菜单 ──

async def open_space_menu(pilot):
    """打开 Space 菜单"""
    await pilot.press("space")
    await pilot.pause(0.2)


async def close_space_menu(pilot):
    """关闭 Space 菜单"""
    await pilot.press("escape")
    await pilot.pause(0.1)


async def space_open_panel(pilot, panel_idx: int):
    """通过 Space 菜单打开指定面板

    面板顺序（0-indexed）: 聊天(0) 记录(1) 角色(2) 用户(3) 游戏(4) 背包(5) 旅伴(6) 通知(7)
    """
    await open_space_menu(pilot)
    # 根级第一项是"面板"，已默认选中，直接回车进入
    await pilot.press("enter")
    await pilot.pause(0.1)
    # 导航到目标面板
    for _ in range(panel_idx):
        await pilot.press("j")
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause(0.3)


async def space_window_action(pilot, action_idx: int):
    """通过 Space 菜单执行窗口操作

    操作顺序（0-indexed）: 横分(0) 纵分(1) 关闭(2) 刷新(3)
    """
    await open_space_menu(pilot)
    # 导航到"窗口"
    await pilot.press("j")
    await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause(0.1)
    # 导航到目标操作
    for _ in range(action_idx):
        await pilot.press("j")
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause(0.3)


# ── 面板定位辅助 ──

async def focus_panel(pilot, panel_name: str):
    """尝试通过 HJKL 切换到目标面板"""
    from .checks import get_focused_panel
    app = pilot.app
    for _ in range(8):
        if get_focused_panel(app) == panel_name:
            return
        await pilot.press("L")
        await pilot.pause(0.1)
    # 再试反方向
    for _ in range(8):
        if get_focused_panel(app) == panel_name:
            return
        await pilot.press("H")
        await pilot.pause(0.1)
