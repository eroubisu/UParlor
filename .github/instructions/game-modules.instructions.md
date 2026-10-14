---
description: "Use when adding or modifying UNO, Ludo, or future game engines, rooms, renderers, handlers, commands, rewards, bots, and game metadata."
applyTo: "Client/client/games/**/*.py, Server/server/games/**/*.py, Server/server/games/**/*.json, Server/server/games/**/*.txt"
---
# Game module contract

- Follow [extension contracts](../../docs/architecture/extension-contracts.md).
- Follow the player-facing [game design principles](../../docs/design/game-design-principles.md).
- Keep framework code game-agnostic; use `register_game`, `register_renderer`, and `register_handler`.
- 房间外壳（建房/进出/准备/邀请/踢人/断线/Bot/结算编排）来自 `core.room_engine`；游戏只写玩法钩子，禁止复制外壳代码。
- Client renderer and handler IDs must match the server `GAME_INFO.id`.
- Implement choices according to the design document's selection-first interaction principle.
- Declare every renderer glyph and use only the centralized Nerd Font character contract.
- Hold `lobby._lock` for every game-state mutation, including bot callbacks.
- Put rewards in `rewards.json` and follow [rules.md](../rules.md) section 1.
- Update the matching manual game handbook.
