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
- Implement choices according to the design document's selection-first interaction principle, including
  its scoped exception for the game operation panel
  ([game design principles](../../docs/design/game-design-principles.md#selection-first-interaction)).
- Declare every renderer glyph and use only the centralized Nerd Font character contract.
- 排版量宽一律用 `window_engine.text.cell_width()`（rich 的 `cell_len`）：中日韩文字两列，
  **其余全部一列**——Nerd 图标、`─ │ ╭ · █` 等文本符号、Powerline 连接符都只占一格。
  不要自己造宽字形名单、也不要把图标按两列占位：每让一格，带图标的那一行就和别的行错开一格
  （用户 2026-10-15 报的字符重叠与"没对齐"就是这么来的）。依据是字体契约 **Nerd Font Mono v3**
  （见 README / CONTRIBUTING），并已用 fontTools 实测玩家机器上的 Sarasa Term SC Nerd Font：
  `a`=500、`中`=1000、Font Awesome 与 Octicons 图标全部 500。
- 两列状态面板统一用共享的 `make_status_table()`，不要自己算间距（等于重复 rich 的一遍排版）。
- 固定宽度的行/栏必须**按同一套格点**排：同一区块里的每一行要么都用点阵、要么都用轨道，
  别一行密一行疏；行宽由格点数决定，不随内容增减变化，并且同一块棋盘的左边距要一致
  （棒球那边是 `ProgressTrack.indent` 和正方形共用 `_SQUARE_INDENT`）。
- 固定宽度区块里的行宽要能在测试里量出来：行相邻的字符串宽度必须相等（用 `cell_width` 量），
  一行的格数在代码里只有一处定义，别让每行各抄一份算术。
- Hold `lobby._lock` for every game-state mutation, including bot callbacks.
- Put rewards in `rewards.json` and follow [rules.md](../rules.md) section 1.
- Update the matching manual game handbook.
