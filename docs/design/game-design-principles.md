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
- `Esc` and `Ctrl+[` leave INSERT mode while retaining unsubmitted text in that field's context.
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

## Interface language

- The supported minimum terminal size is 88 columns by 32 rows. During play, the record panel remains
  across the top. The left column contains only the board and that game's hand/action region; the right
  column contains game status, chat, and room operations in that order.
- Every game explicitly declares its hand/action-region height and computes its status-panel height
  from current game content. The framework provides no default game-region height. Chat receives the
  remaining right-column height, while the shared room-operation panel is six rows total: two frame
  rows and four content rows.
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

## Recording new preferences

A preference belongs here when it is durable, player-facing, and expected to influence more than one
implementation decision. Examples include interaction style, game feel, visual identity, balance
philosophy, and acceptable randomness.

Do not record one-off feature requirements, temporary experiments, or technical implementation rules
here. When a new preference conflicts with an existing one, resolve the conflict with the user rather
than silently keeping both.
