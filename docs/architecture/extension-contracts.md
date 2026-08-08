# Extension contracts

These are the supported extension points. Extend them instead of adding game or feature branches to
framework code.

## Window

1. Implement a `Window` containing one or more `Panel` subclasses.
2. Declare one `WindowSpec` with a unique ID, group, mode, menu membership, preconditions, and bind
   hooks. Root-menu membership never assigns a direct shortcut key.
3. Call `register_window(WindowClass)` in the defining module.
4. Import that module from the appropriate `views/__init__.py` path so registration occurs.
5. Put business binding in `client/window_specs.py`; keep `window_engine` host-agnostic.
6. Use `icon_align = True`, ASCII `>` and `ICON_INDENT` for cursor or Nerd Font lists.

Window mode follows navigation semantics, not only measured size:

- A surface representing the player's current location or session phase is `primary`, including the
  lobby, game waiting room, and active game. It never enters the overlay stack and cannot be closed by
  the shared `Esc`/`X`/`Q` action. Leaving it requires an explicit player action and the resulting
  server-authoritative location change.
- A temporary surface shown over the current location is `floating`, including chat, online players,
  notifications, profile, settings, and their child editors. At most one floating work surface is
  visible: a replacement is measured off-screen, then atomically replaces the previous floating
  surface at presentation commit. The shared exit action closes it and returns to the primary.
- A short-lived control surface that must cover the current floating surface is `popup`, including the
  Space root menu. It uses the overlay layer, leaves the covered floating surface visible underneath,
  and restores that surface when dismissed. Selecting a floating destination from a popup replaces
  the previously covered floating surface.

### Shared window primitives

Window surfaces declare interaction through `client.window_engine`; views do not own parallel widget
state.

- Use `Divider` for every layout separator. Do not synthesize horizontal-rule text or add separator
  borders in a view. Fixed game-board/card cell borders are renderer content and remain under the
  character-width contract.
- Use `Option`, `SelectList`, and `ConfirmMenu` for every menu, candidate list, selectable action, and
  confirmation. Stable option IDs preserve selection within one context; changing context selects
  the first enabled option. Disabled rows remain visible and are skipped.
- Global interaction has exactly five action categories: direction, selection, exit, Space popup, and
  text input. The three direction mappings (arrows, WASD, HJKL), selection mappings (`Enter`, `Z`),
  and exit mappings (`Esc`, `X`, `Q`, `Ctrl+[`) remain behaviorally indistinguishable within their
  category. Views must not introduce direct feature, delete, reject, or hierarchical-back keys.
- Shifted direction mappings move focus between panels; unshifted direction mappings operate only
  inside the focused panel.
- Space opens the centered selectable root menu. Root windows are opened by focusing their menu row
  and confirming, never by a registered letter shortcut.
- Every nested selectable surface includes an explicit return row that restores its parent only after
  the shared Enter confirmation. A confirmation's negative row is that return action; it must not gain
  an additional `返回` row.
- A `select_menu` producer marks its sole hierarchy-return item with `type: "return"`, even when that
  item sends a cleanup command. Consumers detect the semantic type, never the displayed label or an
  empty command.
- Do not add view-local text that explains established navigation or confirmation keys. Such teaching
  belongs in the registered tutorial/help surfaces.
- Use `InputSpec` and `InputSession` for every text field. The engine owns visibility, password mode,
  placeholder, enabled state, focus, IME entry/exit, submission, cancellation, and per-context drafts.
  `Esc` and `Ctrl+[` leave INSERT without deleting the draft.
- A composed registered window starts inactive. An `InputSession` may keep its sticky intent and draft
  while its window is covered or measured, but it must remain disabled and must not request Textual
  focus until presentation commit makes its window and panel the active interaction target.
- `i` enters one-shot text input and `Shift+I` enters sticky text input. Character entry, cursor
  editing, backspace, and submission are accepted only while a declared input is active. Sticky input
  intent belongs to `InputSession`: it survives context changes and temporary disabled states until
  the shared leave action ends INSERT. Views must not inspect Screen mode fields or re-enter input to
  emulate this behavior.
- Tab, focus, open/close, activation, and resize lifecycle changes call `sync_primitives`; use
  `Window.focus_panel()` instead of changing focus-grid internals.
- Opening any registered window first binds its state, restores its declared default focus, and measures
  it outside the viewport. After the first content pass establishes scrollbar layout, the engine
  reflows width-sensitive content once more and moves the complete window into the viewport. Primary
  and floating replacements both keep the previous window visible and active until presentation commit.
  Every primary window is an absolute sibling canvas, so mounting or measuring another primary cannot
  consume layout space, resize it, or move it. Command refreshes address only the active target window;
  hidden game and waiting-room controls are never rewritten during a primary transition.
  Views must not override `show`/`hide`, manipulate the `visible` class, repeat cursor preparation, or
  make an unmeasured intermediate frame visible.
- Opening is a transaction: binding and off-screen measurement have no `on_open`, listener, unread,
  focus, or input side effects. Presentation commit atomically updates the overlay/primary owner,
  activation, input primitives, lifecycle hook, and public `open` event. A newer request cancels any
  uncommitted request in the same window mode, and callbacks from the cancelled presentation are inert.
- A network-driven primary transition carries every field needed by the target's first frame in one
  payload, including its State snapshot, location/path, commands, and transition notice. Target-only
  controls may be prepared off-screen; the complete target is moved on-screen before the old primary is
  hidden, while global navigation context, visible indicators, and the notice log change in that same
  presentation commit. Follow-up messages may confirm context but must not complete the first frame.
- Window activation and presentation are distinct: activation selects the interaction target, while
  presentation ends only after the final measured frame is revealed. A window whose first complete
  frame depends on asynchronous data overrides the presentation readiness gate and resumes presentation
  after rendering that data. It must provide a bounded failure fallback and ignore stale responses.
- Every `SelectList` wraps at both ends and skips disabled rows. The selected row and its scroll viewport
  must be synchronized on first presentation as well as after keyboard movement. Scroll targeting uses
  the selected option's rendered start line from `SelectList.selected_line()`, never its option index,
  because preceding Unicode labels and descriptions may wrap to multiple terminal rows.
- Use `ScrollPolicy` (normally through `Panel.update`/`append`) so content follows new output only when
  the reader was already at the bottom. Width-sensitive rendering uses the same policy so configured
  scrollbar space is reserved before the scrollbar appears; views must not define scrollbar-width
  constants or parallel stable-width calculations.
- Scrollbar appearance and disappearance are dynamic layout transitions owned by `ScrollPolicy`.
  After Textual commits the new scrollbar layout, every width-sensitive surface reflows against its
  new measured width. Chat views and other consumers must not schedule their own compensating redraws
  or freeze one scrollbar state to avoid the transition.
- Views change scrollbar reservation through `Panel.set_scrollbar_visible()`; they do not assign
  Textual scrollbar sizes directly. A scrollbar belongs only to its own scroll surface: independent
  previews and fixed regions use their measured content width and do not reserve a neighboring tab's
  scrollbar.
- `ScrollPolicy.content_width()` is the single source of truth for text width with or without a
  scrollbar. Window presentation invokes every Panel's side-effect-free `reflow_content()` after the
  scrollbar layout stabilizes; the Panel base class invokes the same method after resize. Every
  width-sensitive chat, preview, menu, tutorial, board, or detail Panel implements that method instead
  of owning resize handlers or window-specific presentation callbacks. Content rendered against an
  unmeasured width must never remain on screen.
- World-chat history uses stable message IDs. The initial projection contains at most 16 messages;
  upward pages contain 8 and carry the oldest visible ID. Clearing is a client projection operation
  and never deletes or mutates the server log: the marker filters automatic projection restoration,
  but must not become a boundary on player-requested history pages.

Tests must prove registration, group/menu placement, open/close behavior, and preconditions. Manually
test focus, resize, overlays, and Unicode rendering.

## Client State

`ModuleStateManager` and its component State objects are the UI source of truth.

- Network dispatch calls a State method.
- The method validates/mutates its own fields and calls `_notify()`.
- Widgets subscribe and render; they never assign State fields directly.
- Add a mutation method whenever a new UI-observed field is introduced.

Do not route a network message directly into multiple widgets or trigger UI refresh with external
field assignment.

## Message

- Reuse a constant from `Server/server/msg_types.py` for framework messages.
- Add a framework message only when core client dispatch must understand it.
- Game-specific messages are wrapped by `result_dispatcher.wrap_game_event` and delegated to the
  registered handler.
- Keep payload field names stable across server producer, dispatcher, State, and client consumer.

Trace and update the entire producer-to-consumer chain when changing a payload.

### Chat presentation

- The server owns the chat style catalog, validates persisted catalog IDs and owned chat titles, and
  resolves colors before sending them to clients. Clients never accept sender-provided Rich markup.
- Chat logs persist canonical sender names rather than formatted display names or style snapshots.
  Live messages and history responses attach the sender's current validated name, chat title, level,
  and resolved style.
- `ChatState` stores structured entries and the latest sender presentation registry. Views group adjacent
  entries at render time so a new message can move the previous bottom border without mutating history.
- Incoming entries use the canonical `sender.name` as their State registry and grouping key. Legacy
  level-prefixed log names may be recognized only by the server history migration and must not become
  a second client identity.
- Powerlevel10k-compatible edge heads, separators, and square/round frame glyphs remain centralized in
  `Client/client/config.py`. Edge heads and inter-segment separators use separate validated catalogs;
  wrapping and width fitting use `window_engine.text`.
- Different-background segment transitions use the Powerlevel10k main separators: an empty direct
  boundary for vertical, `U+E0BC` for slanted, and `U+E0B4` for round. Same-background subseparator
  glyphs are not substituted into these transitions.
- The standalone chat-style editor sends no update while browsing. Its final confirmation sends one
  catalog-ID payload; the status response remains the source of truth.

## Game

The same `game_id` must identify every surface.

### Server

1. Create `Server/server/games/<game_id>/`.
2. Declare `GAME_INFO` with ID, display metadata, player bounds, `start_policy`, engine factory,
   settings, and optional bot scheduler. `start_policy.minimum_players` is the hard gameplay
   minimum; `start_policy.underfilled` is `forbid` or `confirm` and applies when the current count is
   below the room's configured capacity.
3. Subclass `BaseGameEngine`; use `_GLOBAL_COMMANDS` and `_COMMAND_MAP`.
4. Put selectable commands in `data/commands.json`, help in `data/help.txt`, and rewards in
   `data/rewards.json`.
5. Register the module once in `Server/server/games/__init__.py`.
6. Return the Rich Result Protocol; never send sockets from the game engine.

Every state mutation, including a Timer/Bot callback, must run while holding `lobby._lock`.

### Client

1. Create `Client/client/games/<game_id>/renderer.py` and `handler.py`.
2. Renderer: set `game_type`, a registered Nerd Font `icon`, declared `glyphs`, and `render_board`.
3. Handler: set the same `game_type`, implement `handle_event`, and optional navigation/update hooks.
4. Register both objects and import the package from `Client/client/games/__init__.py`.
5. Keep game-specific rendering and navigation inside the package.

Framework modules may look up a renderer/handler by ID; they may not branch on a concrete game ID.

### Game completion checklist

- Server game, client renderer, and client handler are all registered.
- IDs and command states match.
- The game declares and enforces its start player requirement; underfilled starts never proceed
  without the policy-defined submenu.
- All choices use `select_menu`; no manual command arguments are required.
- Renderer registration accepts every glyph and rejects emoji presentation.
- Disconnect, forfeit, room cleanup, Bot delay, result persistence, and reward idempotency are covered.
- A numbered game handbook under `docs/testing/` and release mapping exist.

## Character and layout

- Built-in UI/game icons come from `Client/client/config.py` and target Nerd Font Mono v3.
- Renderer glyphs are one terminal cell, declared, and centrally allowed.
- Built-in layout does not use emoji presentation, ZWJ, flags, modifiers, or keycap sequences.
- User text remains Unicode and is measured/wrapped through `window_engine.text`.
- Fixed game cells validate their cell width at the producer.

Never reimplement East Asian width or iterate code points to wrap visible text.

## Persistence and concurrency

- Player files use atomic replacement; storage managers own their internal locks.
- `lobby._lock` protects game/lobby state.
- `server.lock` protects `clients` and `_name_to_socket` writes.
- When nested, acquire `lobby._lock` before `server.lock`.
- Delayed callbacks revalidate room/player identity after acquiring the lock.

Manual tests must include a disconnect during Bot or network activity whenever concurrency behavior
changes.
