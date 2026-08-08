# Known risks

This file records verified limitations, not speculative defects.

## Release readiness

The full repository health audit on 2026-08-02 rated the current worktree **not release-ready**.
Release remains blocked by the plaintext transport defect and the other unresolved risks below.

## Plaintext network transport

Passwords, chats, and session messages currently use unauthenticated plaintext TCP while the server
defaults to all interfaces.

**Control:** do not expose the server to untrusted networks. Require authenticated TLS with hostname
and certificate verification before public deployment.

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

## Large refactor baseline

The current `refactor` worktree contains a large deletion of archived games and substantial uncommitted
client/server changes. Until reviewed and split into coherent commits, regression attribution is weak.

**Control:** do not publish from an unreviewed worktree. Review and commit cleanup, infrastructure,
window engine, companion, UNO, and Ludo as separable changes where history permits.

## Font dependency

Built-in icon alignment assumes Nerd Font Mono v3. Ordinary fonts may show missing private-use glyphs.

**Control:** document the font requirement and run UI-03/UI-04 for releases that change rendering.
