---
name: "Review current UParlor change"
description: "Review the current worktree for correctness, architecture violations, dead code, dependency drift, and missing manual-test updates."
agent: "UParlor Quality Auditor"
argument-hint: "Optional focus area or expected behavior"
---
Review the current UParlor worktree, focusing on: ${input:focus:the complete current change}.

Use the repository instructions and [extension contracts](../../docs/architecture/extension-contracts.md). Check whether affected user-visible behavior is represented in [manual testing](../../docs/testing/README.md). Return findings only; do not edit files.
