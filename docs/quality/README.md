# Quality system

UParlor does not claim that generated code is correct because it was generated or because tests pass.
It uses independent layers that catch different failure classes.

## Layers

1. **Workspace contracts** — `.github/copilot-instructions.md` and scoped instructions constrain AI
   changes before code is written.
2. **Editor facts** — tracked VS Code/Pylance configuration supplies interpreter, import, diagnostic,
   reference, and type information.
3. **Repository gate** — `tools/check.ps1` checks whitespace in tracked and visible untracked files,
   tracked artifacts, JSON, customization frontmatter, syntax, and pytest.
4. **CI** — GitHub Actions repeats the same gate on Python 3.10 and 3.13.
5. **Optional read-only review** — the UParlor Quality Auditor checks explicitly requested,
   release-level, or evidence-backed cross-cutting risks.
6. **Human behavior tests** — `docs/testing/` verifies TUI, multiplayer, IME, rendering, and LLM
   behavior.
7. **Dependency maintenance** — Dependabot exposes Python and workflow drift as reviewable changes.

No one layer replaces another.

## Local command

```powershell
pwsh -File tools\check.ps1
```

`-SkipTests` is allowed only for a quick policy/syntax probe, not as final verification.
After staging the intended change, use `-RequireTracked` to ensure every required governance file is
in the Git index. CI always enables this mode.

## Periodic audit

Run the quality auditor before a release, when explicitly requested, or when focused investigation
finds a cross-cutting risk. Do not run it automatically for routine local fixes. Its selected scope may
cover:

- unused definitions and duplicated logic
- broad exception catches and silent fallbacks
- State mutation paths
- lock ownership/order and delayed callbacks
- client/server registration symmetry
- imported versus declared dependencies
- stale documentation and missing manual cases
- tracked runtime data or secrets

Record accepted debt in [known risks](known-risks.md), with an owner or trigger for reconsideration.
