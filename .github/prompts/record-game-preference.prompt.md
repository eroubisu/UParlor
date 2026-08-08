---
name: "Record UParlor game preference"
description: "Record a durable UParlor game-design, interaction, visual, balance, or player-experience preference stated by the user."
agent: "agent"
argument-hint: "The durable preference to remember"
---
Record ${input:preference:the preference stated in this chat} without relying on chat memory:

1. Read [game design principles](../../docs/design/game-design-principles.md).
2. Decide whether this is durable and player-facing. If it is only a task requirement, do not persist it.
3. Search for conflicts and duplicate rules.
4. Update the single canonical section, moving any duplicate preference out of other documents.
5. Update a scoped AI instruction only when enforcement needs a task trigger; link instead of copying.
6. Report the exact rule recorded and where. Ask the user only when the preference is ambiguous or conflicts.
