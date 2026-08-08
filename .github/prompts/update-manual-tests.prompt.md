---
name: "Update UParlor manual tests"
description: "Update developer-run manual test cases for a user-visible UParlor change after inspecting its implementation and existing handbooks."
agent: "agent"
argument-hint: "Feature, bug fix, or changed behavior"
---
For ${input:change:the current user-visible change}:

1. Inspect the implementation and existing files under [manual testing](../../docs/testing/README.md).
2. Update only the affected handbook and release coverage map.
3. Use stable case IDs with prerequisites, steps, expected result, and safe evidence.
4. Do not duplicate shared setup or request secrets in evidence.
5. Summarize which manual cases changed and why.
