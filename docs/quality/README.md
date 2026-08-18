# Quality system

UParlor does not claim that generated code is correct because it was generated or because tests pass.
It uses independent layers that catch different failure classes.

## Layers

1. **Workspace contracts** — `.github/copilot-instructions.md` and scoped instructions constrain AI
   changes before code is written.
2. **Editor facts** — tracked VS Code/Pylance configuration supplies interpreter, import, diagnostic,
   reference, and type information.
3. **Impact resolver** — `tools/impact.py` turns target paths or the current diff into the smallest
   known test, handbook, contract, and gate scope without an AI repository survey.
4. **Repository gate** — `tools/check.ps1` checks whitespace in tracked and visible untracked files,
   tracked artifacts, JSON, customization frontmatter, syntax, Ruff's zero-noise name/dead-local
   rules, and pytest. Broader Ruff rule families remain audit-only until their baseline noise is
   resolved.
5. **CI** — GitHub Actions repeats the same gate on Python 3.10 and 3.13.
6. **Optional read-only review** — the UParlor Quality Auditor checks explicitly requested,
   release-level, or evidence-backed cross-cutting risks.
7. **Human behavior tests** — `docs/testing/` verifies TUI, multiplayer, IME, rendering, and LLM
   behavior.
8. **Dependency maintenance** — Dependabot exposes Python and workflow drift as reviewable changes.

No one layer replaces another.

Tracked contracts, tests, design decisions, and known risks are durable project memory. Chat history,
agent memory, and transient task notes are not authoritative. A repeated machine-recognizable failure
must become a focused test or policy check instead of another instruction paragraph.

## Local command

```powershell
pwsh -File tools\check.ps1
```

`-SkipTests` is allowed only for a quick policy/syntax probe, not as final verification.
After staging the intended change, use `-RequireTracked` to ensure every required governance file is
in the Git index. CI always enables this mode.

## Periodic audit

Install the separate audit dependencies and run the deterministic ratchet before a release or during
an explicitly requested health review:

```powershell
python -m pip install -e ".\Client[audit]"
python tools\quality_audit.py
```

The tracked [quality baseline](quality-baseline.json) identifies existing severe-complexity functions,
allows two required framework callback parameters, caps duplicate groups, and sets the current coverage
floor. Improvements pass without editing the baseline; new or worsened debt fails with exact identities.
The audit is intentionally absent from routine `check.ps1` and CI because it reruns coverage and broad
analysis. Update the baseline only after a reviewed improvement lowers an entry or an explicit decision
accepts new debt.

Run the AI quality auditor only when explicitly requested, before a release, or when focused
investigation finds a cross-cutting risk. Its selected scope may cover:

- unused definitions and duplicated logic
- broad exception catches and silent fallbacks
- State mutation paths
- lock ownership/order and delayed callbacks
- client/server registration symmetry
- imported versus declared dependencies
- stale documentation and missing manual cases
- tracked runtime data or secrets

Record accepted debt in [known risks](known-risks.md), with an owner or trigger for reconsideration.
