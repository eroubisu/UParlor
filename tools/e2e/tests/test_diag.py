"""Diagnostic: intercept sent commands to verify they actually get sent."""
from ..game_actions import enter_game, create_room
from ..actions import open_menu, menu_select
from ..checks import get_location

_sent_commands = []


def log(msg):
    print(msg, flush=True)


async def test_diag_room_flow(pilot):
    app = pilot.app

    # Monkey-patch to capture sent commands
    orig_send_command = app.send_command
    def patched_send_command(text):
        _sent_commands.append(text)
        log(f"[CMD] send_command('{text}')")
        return orig_send_command(text)
    app.send_command = patched_send_command

    await enter_game(pilot, "holdem")
    log(f"[1] entered, loc={get_location(app)}")
    log(f"[1] commands sent so far: {_sent_commands}")

    # create
    _sent_commands.clear()
    await open_menu(pilot)
    await menu_select(pilot, "create")
    await pilot.pause(2.0)
    log(f"[2] after create, loc={get_location(app)}, sent={_sent_commands}")

    # bot
    _sent_commands.clear()
    await open_menu(pilot)
    await menu_select(pilot, "bot")
    await pilot.pause(0.3)
    await menu_select(pilot, "1")
    await pilot.pause(2.0)
    log(f"[3] after bot, loc={get_location(app)}, sent={_sent_commands}")

    # start
    _sent_commands.clear()
    await open_menu(pilot)
    await menu_select(pilot, "start")
    await pilot.pause(3.0)
    log(f"[4] after start, loc={get_location(app)}, sent={_sent_commands}")

    loc = get_location(app)
    assert loc == "holdem_playing", f"Expected holdem_playing, got {loc}"
