# Known risks

This file records verified limitations, not speculative defects.

## Release readiness

The health review on 2026-10-14 re-confirmed the risks below while removing dead code; no new release
blocker was found. The owner explicitly accepted the plaintext-transport risk on 2026-10-14 rather
than changing the default server address or adding TLS, so the control below still stands.

## Plaintext network transport

Passwords, chats, and session messages currently use unauthenticated plaintext TCP while the server
defaults to all interfaces.

**Control:** do not expose the server to untrusted networks. Require authenticated TLS with hostname
and certificate verification before public deployment.

## Public iOS handle relay

The public relay lets a phone control a client through the game port; the session token is carried in
plaintext HTTP, and the pairing code is displayed rather than typed, so anyone who learns the token
URL can reach the same page. Enforced limits: keys and pasted text are rejected until the phone
confirms pairing, the token only exists while that client has the handle enabled, it rotates on every
enable and reconnect, and request bodies, response sizes, and per-session concurrency are capped.

**Control:** never print the relay URL in public; disable the handle when not in use. Add a typed
pairing code and HTTPS before treating the phone as a trusted second factor.

## Non-atomic local persistence

Several client companion/config and server chat/DM writers truncate final files directly; interruption
can corrupt data, and some readers silently replace malformed content with empty defaults.

**Control:** back up important local data and migrate these writers to a shared atomic replacement
helper with explicit corruption reporting.

Client “clear chat history” is intentionally a current-State UI boundary, not a retention/deletion
operation. Server chat and DM logs remain the only durable chat records; the companion can inspect only
the current account-stamped ChatState projection.

## Broad exception boundaries

The current client, window engine, and AI companion contain broad exception handlers, including silent
UI and shutdown fallbacks. Some protect framework or best-effort boundaries; others may hide defects.

**Control:** new broad catches are prohibited without logging/UI reporting and review. Existing catches
should be narrowed only when the affected flow is being changed and its expected exceptions are known.

## Interactive coverage

Automated tests primarily cover imports, registration, pure logic, window-engine contracts, companion
state, and terminal text. They do not prove real terminal composition, IME behavior, multiplayer
timing, full game rules, or third-party LLM behavior.

**Control:** execute the mapped handbooks in `docs/testing/07-release-checklist.md`.

## Font dependency

Built-in icon alignment assumes Nerd Font Mono v3, where every icon occupies one cell; only CJK
text is two cells wide (measured 2026-10-15: Sarasa Term SC Nerd Font, `a`=500 / `中`=1000 / icons
= 500 units). Ordinary fonts may show missing private-use glyphs, and Nerd Font builds with
double-width icons (some non-Mono builds) would break row alignment.

**Control:** document the font requirement and run UI-03/UI-04 for releases that change rendering.
