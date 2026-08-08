---
description: "Use when writing or updating developer-run manual test cases, release checklists, test evidence, or regression plans for the TUI."
applyTo: "docs/testing/**/*.md"
---
# Manual test documentation

- Give every case a stable ID, prerequisites, steps, expected result, and required evidence.
- Test observable behavior, not implementation details.
- Include failure and recovery paths where applicable.
- Never ask testers to record passwords, API keys, tokens, or private chat content.
- Mark destructive, paid-LLM, multi-client, and long-running cases explicitly.
- Link shared setup instead of copying it into every handbook.
