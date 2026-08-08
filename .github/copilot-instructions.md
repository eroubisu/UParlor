# UParlor workspace guidelines

## Before changing code

- Search for the existing implementation, protocol, constant, and call sites before adding anything.
- Read only instructions and contract sections relevant to the files and behavior being changed.
- Consult [rules.md](./rules.md) only for its named domains, and
  [hardcode-policy.md](./hardcode-policy.md) only when introducing or consolidating literals.
- Consult the relevant section of [extension contracts](../docs/architecture/extension-contracts.md)
  for framework boundaries, and [game design principles](../docs/design/game-design-principles.md)
  for player-facing decisions. Do not load either document wholesale for an unrelated local fix.

## Change discipline

- Make one coherent change at a time; do not mix cleanup with feature work.
- Fix shared behavior in the abstraction that owns its semantics. Do not make a view inspect host
  private state or reimplement an engine feature to repair one screen.
- Do not invent user-facing visual, wording, interaction, or product decisions. Follow explicit user
  requirements and established project rules; when neither determines a necessary choice, ask the
  user before implementing it.
- This confirmation requirement is blocking. Before changing any product, interaction, visual,
  gameplay, wording, sizing, timing, persistence, or navigation behavior that is not uniquely
  determined by the user's request or an existing rule, stop, present the concrete alternatives and
  tradeoffs, and wait for the user's explicit choice. Do not choose a default, infer consent from
  urgency, or substitute technical convenience for confirmation.
- When the user has identified behavior as a shared engine responsibility, implement it in the owning
  shared abstraction and verify every affected surface. Do not add a view-specific workaround unless
  the user explicitly chooses that scope after being shown the tradeoff.
- Do not add unrequested behavior, limits, configuration, or performance changes. If a requested fix
  appears to require one, ask the user before changing it.
- Every new class, protocol, message, helper, or setting must have a real caller.
- Preserve the State SSOT and registry-based game boundaries.
- Update an existing manual case when its expected behavior changes; add a case only when no existing
  case covers the regression.
- Use targeted diagnostics and tests for local changes. Run `pwsh -File tools/check.ps1` for
  cross-module changes, shared-engine changes, dependency/governance changes, or before commit/release.

## Durable user preferences

- When the user states a durable UParlor preference in chat, record it in the same task instead of
  relying on conversation memory.
- Put player-facing game preferences in `docs/design/game-design-principles.md`; put enforceable
  engineering constraints in the relevant `.github` rule or architecture contract.
- Do not persist one-off requests. Search for duplicates or conflicts first, and ask only when the
  intended long-term rule is ambiguous.

## Workflow guidance

- End every completed task or decision point with one concrete `下一步` for the user, based on
  `WORKFLOW.md`.
- If no user action is currently required, say so and name the next recommended repository task.
- Do not offer a vague list of optional next steps when one workflow action is clearly required.

## Release order

- Before every release, inspect the actual diff separately for client and server changes. For each
  changed package, report its current version and wait for the user to choose the next version.
- Finish every file modification, including package versions and the server's supported client
  version, before uploading or deploying. Run the release gate after those final edits.
- Publish a changed client to PyPI and deploy a changed server to the configured remote host. Do not
  publish or deploy an unchanged package.
- After publication and deployment begin, do not modify repository files. Verify the release, then
  create and push the GitHub commit from exactly the files that passed the release gate. If any file
  must change, stop and restart the release gate before uploading or deploying again.

## Safety

- Never run upload, deploy, push, `twine upload`, or remote-copy commands unless the user explicitly requests deployment or publication.
- Never store API keys, credentials, player data, logs, or generated runtime state in the repository.
- Do not hide failures with broad catches or success-shaped defaults. Report errors through the existing UI/logging path.

## Human verification

Automated tests cover contracts and pure logic. Interactive TUI, multiplayer, rendering, IME, and LLM behavior require the checklists in [manual testing](../docs/testing/README.md).

## Credit-efficient execution

- Do not launch subagents, full-workspace diagnostics, repository-wide searches, or health audits for
  a local change when direct inspection and a focused test can settle it.
- Keep the UParlor Quality Auditor opt-in. Use it only when the user requests a review/audit, before a
  release, or when a concrete cross-cutting risk cannot be resolved with focused evidence.
- Escalate validation only after focused checks fail or the change crosses shared contracts.
