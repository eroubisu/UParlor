---
description: "Use when editing Python implementation or tests. Enforces Pylance-grounded changes, import boundaries, error handling, and focused validation."
applyTo: "Client/**/*.py, Server/**/*.py, tests/**/*.py, tools/**/*.py"
---
# Python changes

- Use the workspace interpreter and Pylance facts for types, references, diagnostics, and call sites.
- Prefer existing helpers and protocols over new wrappers.
- Keep Python 3.10 compatibility; do not use syntax introduced after 3.10.
- Catch only expected exceptions. If a framework boundary requires a broad catch, log or surface the failure.
- After changing signatures, inspect every semantic caller.
- Run the smallest relevant pytest selection. Run `pwsh -File tools/check.ps1` only when required by
  the workspace policy for cross-module/shared-engine/governance work or commit/release readiness.
