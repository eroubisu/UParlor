# UParlor game design principles

This is the canonical record of durable player-facing game preferences. It describes what UParlor
should feel like; technical architecture belongs in `docs/architecture/`, and AI execution rules
belong in `.github/`.

## Terminal-native presentation

- Built-in UI and game symbols use monochrome Nerd Font Mono v3 glyphs that Rich can recolor.
- Do not use colored emoji for built-in presentation.
- New UI surfaces inherit the existing monochrome palette; do not introduce an accent color unless
  the user explicitly requests it.
- Focus is communicated quietly and consistently: the single active window's current panel uses the
  bright monochrome border, while every inactive window and panel retains the dim border.
- Color is part of a card or piece's background, not a color name appended to its text.
- Disabled cards and pieces retain their inherent color with a dimmed background.
- User-authored chat remains full Unicode.
- The tutorial follows the account, not the device (2026-11-15): it opens after login unless that account
  chose "下次登录不再显示教程" on the last page. The choice is a circle item identical to the other choice
  circles, off by default, and only an Esc exit with it selected remembers it; the server stores it on the
  account. Nothing about the tutorial is remembered before login. The whole tutorial occupies one fixed,
  centered 60x18 area on every page; the focus-practice page splits that same area between the tutorial
  panel and the target panel instead of growing it. The first and last
  pages link to the project page.
- The login and register username boxes use their dim placeholder text to tell a new player how to start
  (press i; new users switch to the register tab).
- An input field's input method follows the player: leaving INSERT remembers whether Chinese or English was
  in use and entering INSERT restores it (Chinese when nothing is remembered). Regaining window focus while
  typing never forces English.
- The client detects the player's operating system and adapts platform-dependent behavior to it
  (for example, input-method switching on Windows and macOS). The game stays playable everywhere;
  a platform without an adaptation degrades to no automatic switching, never to an error.
- An input field declares its input method through `InputSpec.english_ime`. Fields that do not need
  Chinese (the login username and password) keep the English input method when INSERT starts; every
  other field switches to the Chinese one. The server's username rule (Latin letters and digits only)
  and the login field's declaration are tied together by a test.

## Player chat presentation

- World, room, private, and companion chat use the same Powerline-inspired framed message groups.
- Adjacent messages from the same sender share one frame regardless of elapsed time. The player title is
  one line with three fixed segments: player name, a dedicated owned chat title, and level.
- Every message shows a tertiary-gray `HH:MM:SS` timestamp right-aligned on its final line. The final message and its
  time are embedded in the group's bottom border; when they cannot fit together, the time gets its own
  right-aligned bottom-border line.
- `Space` opens the root menu; selecting `档案` opens the player's profile. Its chat-style action
  opens a separate editor with
  identity, color, connector, frame, and confirmation tabs; a live preview remains below the tab
  content. Players may choose each title segment's foreground/background color, frame color, body
  color, square or rounded frame corners, and separate left, inter-segment, and right shapes.
- Connector terms and glyphs follow Powerlevel10k: angled, vertical, slanted, and round separators;
  edge heads additionally support flat and blurred `░▒▓` / `▓▒░` transitions. Choices come only from
  the project palette and catalog.
- Chat titles must be owned, and player name and level are authoritative server values. Arbitrary markup,
  colors, glyphs, and identity text are not accepted.
- Existing messages render with the sender's latest style rather than storing a style snapshot per
  message. Public and private logs store canonical sender identity, text, and time only.
- Opening world chat presents at most the latest 16 visible messages. At the top, one further upward
  action reveals `向上加载历史消息`; the next upward action loads 8 earlier messages, repeating until no
  earlier visible history remains.
- World-chat settings clear only the player's local projection, never the server log. The clear
  boundary persists for that player across window reopen, logout, and client restart; messages sent
  after the boundary remain visible. Explicit upward history loading may reveal messages before the
  clear boundary for the current view; reopening the chat applies the clear boundary again.

## Selection-first interaction

- Global operation is limited to five action categories: direction, selection, exit, Space popup, and
  text input. No feature, deletion, rejection, or game command owns a direct letter shortcut.
- Arrows, WASD, and HJKL are equivalent direction mappings. Unshifted directions navigate only inside
  the focused panel; their shifted forms move focus between panels.
- Enter and Z are equivalent selection mappings. Enter confirms the current selection or submits text
  while already in INSERT mode; it never starts editing a text field.
- Text entry starts with `i` for one submission or `Shift+I` for continued entry. Ordinary character
  and editing keys have meaning only while text input is active.
- If an action requires a choice, the command itself takes no manually typed argument.
- Open a `select_menu`; choosing an entry sends the complete command.
- Menu rows use `> label` on the left and an optional description on the right.
- Menus, confirmations, candidate lists, text fields, and layout dividers share the window engine's
  primitives. Their cursor width, wrapping, disabled behavior, draft handling, and lifecycle refresh
  must not vary by window.
- Ordinary product surfaces do not explain established keys or selection mechanics inline. Consistent
  behavior teaches itself; explicit control instruction belongs only in the tutorial and help.
- Space opens one centered root-menu popup. Its rows are navigated and confirmed like every other
  menu; root features never display or respond to `S`, `A`, `O`, `P`, or other direct shortcuts.
- `Esc`, `X`, and `Q` are equivalent physical mappings of one exit/cancel action for the three supported
  control schemes; product behavior must never distinguish them.
- This shared action closes only temporary popup windows. It never leaves the lobby, a game waiting
  room, an active game, or another surface that represents the player's current location.
- Returning within a hierarchy is always a visible selectable row. The player focuses `返回` and uses
  the shared confirm action; no dedicated key performs hierarchical back navigation.
- In a confirmation, the visible negative choice performs that return and no additional `返回` row is
  shown beneath the affirmative and negative choices.
- The game operation panel displays action labels only. Command descriptions belong in help or records,
  not as a second explanatory column beside every operation.
- The game operation panel is the single scoped exception to confirmation-first selection, settled with
  the user on 2026-10-15: direction keys still only move the cursor and wrap within their own option
  row exactly like every menu, but the option the cursor lands on takes effect immediately when it is
  **reversible** (fielder movement, runner commands). **Irreversible actions** — throw to a
  base, pitch, swing, and the fielder's jump (Enter) — keep their own rules: pitch/swing/throw use the
  shared Enter confirmation, the jump is a timed action whose moment counts. A reversible choice is always changed by
  moving the cursor again; no key may change it on the player's behalf.
- Simultaneous secret selection is allowed when both sides must commit blind, settled with the user on
  2026-10-15 for baseball's pitch/swing: each side opens its own menu at the same time, the two choices
  stay invisible to each other, submitting locks that ball (a setting such as the defensive shift may
  still be changed before submitting), and the exchange starts only when both have submitted. The
  game's status panel shows one ready indicator per side; the room shell's one-at-a-time turn model is
  not required for it.
- `Esc` and `Ctrl+[` leave INSERT mode while retaining unsubmitted text in that field's context.
- Confirmation is one mechanism. A server declares which commands need confirming in
  `_CONFIRMED_COMMANDS` (forfeit, invite, kick) and sends the shared `build_confirm_menu` request; the client
  always shows it with the shared `ConfirmMenu`, the same component chat, notifications and settings use, so
  every yes/no confirmation looks and behaves the same. Forfeit asks exactly once on every path (the forfeit
  button, Back, Quit) and in every game.
- Ctrl+C is a system-level exit binding, blocked by default through local settings. Settings exposes
  both the blocking toggle and a selectable, confirmed `退出 UParlor` action.
- Text fields remain single-line and horizontally follow the cursor when content exceeds the visible
  width; entered text is never hidden beyond a stationary viewport.
- Player-selection menus default to friends unless the operation inherently requires a wider set.
- A game's hard minimum and a room's configured capacity are distinct. Below the hard minimum,
  starting is forbidden. Between the hard minimum and configured capacity, each game explicitly
  chooses either prohibition or confirmation. The resulting submenu and outcome are written to the
  record panel.
- A command refresh within the same operation context preserves the selected command. Entering a
  different context resets selection to its first actionable command.

## Baseball pacing

- Pitch and swing animation frames remain 140ms each, and the ready countdown remains one second per
  step. Other timed baseball phases use a 2× slowdown: ball flight, ground pickup, throws, and runner
  progress. Client-side interpolation is time-driven at about 30 frames per second through the shared
  `Animator`; this must not change server tick counts or game outcomes.
- Runner progress is concurrent with the ball: its elapsed time depends on which phase's ticks advance
  it, so a ground-phase base time must not be presented as the total time for an entire play.

## Baseball board layout

Settled with the user on 2026-11-15.

- Every element of the board stays at its own fixed position whether or not it is lit or has
  content; an empty element still occupies its space and nothing else may take it over.
- The diamond's live slots, top to bottom, are verdict / countdown / ready lights (or ball position)
  / current action. The verdict has its own slot and never replaces the ready lights, so after a
  play both are visible during the next ball's preparation.
- A base name never moves when its throw distance appears. The distance is written beside the name:
  to its right for the left-hand bases, to its left for the right-hand bases, never wider than the
  square.

## Baseball language and outcomes

- Player-facing baseball text uses concise, formal, standard baseball terminology. Avoid colloquial
  phrasing and unexplained shorthand.
- Each resolved play identifies every runner whose situation changed by role and starting base, exactly
  once, in the line that states what happened to them (out with the out count, scored, or advanced to
  the named base). A runner who did not move, or an out already announced, is not repeated. Symbols or
  final base occupancy alone are insufficient.
- Runner controls (replaced 2026-10-21 at the user's request, superseding the earlier "+1 base" labels):
  baserunning is a **continuous order**, not a count of extra bases. One row of three buttons —
  撤回 / 停止 / 前进 — applies to all runners together and takes effect the moment the cursor lands on it:
  前进 keeps runners running base after base until the order changes, 停止 stops them at the next base
  they reach (a runner already between bases finishes that leg), 撤回 turns runners who are between bases
  back to the base they just left (the way back takes as long as they had already run). After a hit the
  default order is 前进 (the user's 2026-10-21 decision: all runners go by default and the batter stops
  them), so runners standing on base leave at once unless 停止 is pressed that moment; the tag-up window
  after a caught fly is a fresh decision whose cursor starts on 停止. Runners forced to advance
  (including the batter) cannot turn back or stay on their first leg. The user chose one row for all
  runners over a lead-runner/other-runners split, accepting the loss of lead-only sends for easier
  operation.

## Baseball rules and feedback

Settled with the user on 2026-10-17 during the baseball polish pass.

- Standard ending: if the home team leads when the top of the last inning ends, the bottom half is not
  played; a home-team lead in the bottom of the last inning ends the game at once (walk-off); a tie
  after the last inning is a draw with no extra innings. Both early endings state their reason in the
  log before settlement.
- A setting is offered only when it has something to act on: the pitcher's "runner" (pickoff) item and
  the batter's steal item exist only while a base is occupied, and the server treats them as the
  neutral value otherwise.
- A steal is part of the batter's secret submission: the opponent must see no trace of it before the
  pitch is released.
- Hit feedback states facts and never evaluates or advises: after a swing, the log records the timing
  band and whether the pitch pick was right (`时机提前 预判正确`); the pitch track draws the
  two timing-band dividers (`┆`) and lights a solid mark at home plate when the batter presses.
- After the first submit of a match, the next pitch form's cursor rests on 「确定」 so repeating the
  same ball takes two Enter presses; the first pitch still starts on the first item.
- Both pitch and swing forms list their settings first and 「确定」 last.

## Baseball feel, rooms and the notification bar

Settled with the user on 2026-10-21 during the baseball improvement pass.

- Animation follows the server clock: every timed thing (ball, runners, pitch frames, throws) glides
  toward its **next tick's position** and arrives as that tick arrives, so the picture is the server's
  real position delayed only by network latency. Movement starts the instant a pitch is released or a
  ball is hit, and nothing jumps on the last cell. The true landing cell stays secret (the client only
  ever looks one step ahead). This replaces the older "never ahead of the last reported position" rule.
- A player's own real-time key (chase move, hit) gets feedback as soon as the server confirms it, not on
  the next tick; pressing hit lights the swing mark locally at once. Waits that belong to the normal game
  flow (the countdown, a bot thinking before it submits or releases) are not shortened.
- The innings count is chosen by the host when creating the room (1–9, default 3) through the shared
  `room_settings` mechanism; the last inning is whatever was chosen. Experience, gold and rank points are
  scaled by innings ÷ 3 so a 1-inning match cannot be farmed.
- The top record bar shows **one line at a time** and defaults to the newest record. Every baseball
  message is therefore a single line of at most 70 columns, one message per line, and the **last line of
  each broadcast is the news**: result + count (or the at-bat outcome) + timing fact in one line,
  scoring lines carry the running score, outs carry the out count, and the half-inning change follows
  the third out. Settlement ends with a one-line conclusion; the line score and stats come before it.
- **Log writing (settled 2026-10-22 at the user's request: no Chinese punctuation, no sentence-by-sentence
  prose).** A baseball log line is a row of short phrases separated by single spaces — no `，；：。！？（）`,
  no connecting particles — and wraps only between phrases. Each fact appears **once**: an out is stated
  on its own line and later summary lines list only results not yet announced; instructions and menu
  prompts are not log content. Counts are `1-2` (balls-strikes), outs `2出局`, the scoreboard
  `bob 4-2 alice` (away first); only the settlement conclusion puts the **player's own score first**.
  The shared lobby/room messages and the UNO/Ludo texts have not been converted to this style.
- **The record bar is scrollable** (settled 2026-10-22). It keeps every record, one record per row (an
  overlong tail ends with `…`; the Records window shows it whole). When the bar has focus, ↑/↓ move one
  record at a time and the bottom border shows `n/total`; while reviewing, new records never pull the view
  away, and returning to the newest record or leaving the bar resumes following the newest. The Records
  window keeps appending while it is open (it still opens on the latest 16). This is the shared
  `LogPanel`, so lobby, waiting room and every game behave the same way.
- The throw track writes the target base and the throw's total distance at its right end (`二垒 15.7米`),
  degrading to distance only and then the bare number when the space is too narrow; it never widens
  the row.
- The scout page does not truncate a pitch line and records who batted for every pitch.

### Baseball fielding (settled with the user on 2026-10-21)

- The fielder **runs continuously at a steady speed** (cells per second), like the ball moves; he never
  hops one cell at a time. The server keeps position, heading, speed and jump time and derives the
  position from the clock; the cursor landing on left/stop/right sets the heading once.
- The fielding pad is only 左移 / 停止 / 右移. **Enter is a timed jump** that widens the catch reach but
  lowers catching precision; not pressing is small-reach, high-precision. The jump's **timing counts**
  (the ball must arrive while he is in the air), and after a jump he must **recover** (no running, no
  second jump) for a moment. There is no three-way catch-action choice and no "best action" hint.
- Outs are named by how they happened — 接杀 FLY OUT, 封杀 FORCE OUT, 触杀 TAG OUT (and 双杀 DOUBLE PLAY) — in the
  board's verdict slot and in the out line itself (`封杀 二垒 一垒跑者 1出局`) that stays on the one-line top bar.
- The pitcher stands **outside the right bar** of the pitch row (one gap after the bar, mirroring the home-result
  symbol on the left) and is shown in every phase, not only during the pitch; the ball starts from the last cell.
- The landing is shown as a **range that starts wide and narrows as the ball approaches**, collapsing onto
  the true landing cell on arrival; a harder hit starts wider. The range always contains the true
  landing but is never centred on it. It is drawn as a thin gold line on the outfield row that
  collapses into the dashed circle.

## Interface language

- The supported minimum terminal size is 88 columns by 32 rows. During play, the record panel remains
  across the top. The left column contains only the board and that game's hand/action region; the right
  column contains game status, chat, and room operations in that order.
- Every game explicitly declares its hand/action-region height and computes its status-panel height
  from current game content. The framework provides no default game-region height. Chat receives the
  remaining right-column height, while the shared room-operation panel is six rows total: two frame
  rows and four content rows. A game may instead pin a **fixed** status height when a stable chat area
  matters more than content-fitting and the user has chosen that trade-off (baseball, 2026-10-16:
  fixed 8 rows — the panel must not grow or shrink between phases; the spare rows go to chat).
- Sending a game command never clears or replaces the visible hand/action content while awaiting the
  authoritative server update. The existing content remains in place but cannot be submitted again;
  the next game update or selection response restores interaction.
- UNO uses a 40-column right rail and a status height of current player count plus seven rows. Two
  prompt rows are always reserved because the server rules permit at most two simultaneous prompts,
  so prompt changes never move the surrounding layout or the player-list origin. No rows are reserved
  for absent players. The status panel never scrolls or truncates valid maximum-width content.
- A game-to-waiting or waiting-to-lobby transition keeps the old primary's last complete frame unchanged
  while the target reads the updated SSOT off-screen. Only the target presentation commit replaces it;
  intermediate lobby, cleared-room, or waiting-state frames are never shown.
- A game's options state **what they are, never what they are worth** (user decision, 2026-10-15).
  Menus show a value's name and, in the top-level form, the currently chosen value; they never print
  an option's probability, effect, or trade-off. Working out what an option does — from the rules, the
  record panel, and what actually happened in play — is the game. A menu that does the arithmetic for
  the player removes the thing being played. Balance the mechanics so thinking pays; do not print the
  answer. (Baseball briefly shipped effect hints in its second-level menus and the user removed them.)
- A fixed-format game board must remain fully visible without a scrollbar at the minimum terminal size.
  Changing status or action prompts scrolls only inside that game's declared region and never resizes
  the board.

- Companion replies become visible only after their psychological-state evaluation completes. Each
  persisted reply stores the mood shown with that reply; later mood changes never relabel history.
- Companion mood has inertia: ordinary evaluations require repeated evidence to change the primary
  mood, and one interaction cannot sharply change intensity. Only an extreme evaluation may switch
  the primary mood immediately.

- Player-facing wording is concise, formal, and unambiguous.
- Avoid conversational phrases when a stable product term can describe the same action.
- The last row of a setting menu is the submit row and is named `确定`; it never repeats the action
  name (`投球` / `打击`) and never explains itself. A submenu's first row is its own name
  (`球种`, `盗垒`, …); the root menu and the button pads have no title row. (Settled with the user,
  2026-10-15.)
- Destructive or session-changing choices state the affected object and result explicitly.
- When a remote action ends the current account session, block further interaction and present explicit
  choices to return to login or exit the client.

## Companion interaction

- The companion opens on `对话` with a `设置` tab. Selecting a companion adds a `状态` tab that
  exposes relationship values and current mood, but not private thoughts or its impression of the player.
- The chat tab has no setup wizard. It remains non-interactive until the API service, model, current
  companion, and enable switch are ready.
- The current companion name appears in the chat panel's lower-right subtitle; no name is shown when
  none is selected.
- When a companion exists, the status tab is present on the first render. Players may submit another
  message while a reply is pending; each message keeps its own reply position, and tabs, scrolling,
  settings, and status remain operable.
- Player and companion messages use the shared framed chat groups. The companion title has two segments,
  companion name and current mood, and reuses the player's first two segment styles and connector
  choices. Each companion message has at most one leading, indented, subdued italic action line followed
  by one continuous speech block. The model must generate this as one structured reply; the client never
  truncates, merges, or hides a second generated action or speech block.
- Settings use focus-and-Enter rows. Choices such as provider, model, and current companion open a
  submenu instead of requiring typed arguments.
- Companion configuration exists only on the companion window's `设置` tab; the global Settings
  window does not duplicate a companion-settings entry.
- API keys are persisted only after the user explicitly chooses `保存并验证` and validation succeeds.
- The supported providers are Gemini and DeepSeek. Models come from the validated provider's model
  list rather than free-form input.
- Creating a companion uses a separate, gated window: free description, name, personality, speech
  style, appearance, backstory, and final confirmation. Each generated attribute page offers four
  contextual choices plus regenerate. Pressing `i` on an attribute page adds the submitted value to
  that page's choices; it does not select the value automatically.
- A later creation page stays locked until the current page is confirmed. Revisiting and changing an
  earlier choice preserves that page's candidates, committed selection, and later choices. Backward
  navigation never calls the AI; generation occurs only on first advancing to a page without candidates
  or when the player explicitly selects regenerate.
- The chat display restores the selected companion's persisted visible conversation after reopening
  the window or client.
- Relationship and mood state use one structured semantic evaluation after each completed reply. The
  evaluator considers the character, prior state, complete interaction, and actual reply; code must not
  classify specific player wording or invent a positive relationship change when evaluation is absent
  or neutral. An already open status page refreshes when evaluation finishes.
- Selecting a companion opens an action submenu for selection or confirmed deletion. Deletion removes
  that companion's profile, conversation, memory, and state.
- Proactive conversation considers both elapsed silence and important events. External important events
  include incoming private messages, friend requests, invitations, and system notices; each game
  declares its own important events through its registered client handler.
- A game produces at most one proactive companion notification per match, when the match completes.
  Turn-by-turn progress remains available through an on-demand observation tool and never causes a
  reply by itself.
- Unread proactive replies have a distinct monochrome footer badge. Opening the companion window clears
  that badge without deleting conversation history; the badge uses the companion paw glyph.
- Internal proactive trigger context is never visible or persisted as player conversation.
- When the player speaks before a queued proactive event is delivered, that event becomes context for
  the player's reply and is consumed; it must not produce a second assistant message afterward.

## Rewards and economy

- Baseline experience is **50 EXP per expected minute**.
- Coin multipliers are approximately **0.15× for solo** and **0.20–0.25× for PvP**.
- A game's expected experience is calibrated from its average duration.
- Across one match, total awarded coins must exceed total lost coins.
- Concrete values live in that game's `data/rewards.json`, never in engine code.

## Bot behaviour

- A robot opponent stays exactly as weak as the user chose: never strengthen a bot's policy because
  a mechanic "looks unused" in bot games. Weaker robot defence is the point, not a gap to close.
  Baseball's fielder therefore keeps picking its throw target **at random** (user decision, 2026-10-15),
  which is why force-outs and the second throw of a ground double play stay rare in bot-vs-bot play.
  Baseball's bot pitcher likewise only sometimes holds a runner (35% when a base is occupied) instead
  of always countering a steal.

## Recording new preferences

A preference belongs here when it is durable, player-facing, and expected to influence more than one
implementation decision. Examples include interaction style, game feel, visual identity, balance
philosophy, and acceptable randomness.

Do not record one-off feature requirements, temporary experiments, or technical implementation rules
here. When a new preference conflicts with an existing one, resolve the conflict with the user rather
than silently keeping both.
