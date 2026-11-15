# Contributing to UParlor

UParlor is developed with VS Code and Copilot, but every change remains the developer's responsibility.
Repository instructions, checks, review, and human verification are the trust boundary.

## Setup

Development happens on macOS only (Python 3.10+).
The game itself must keep running on every operating system, so never add OS-specific behavior to
`Client/` or `Server/` code.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e "Client[test]" -e "Server[test]"
python tools/check.py
```

Use Nerd Font Mono v3 for UI work. Editor settings are personal and not tracked.

Enable the repository hooks once per clone: `git config core.hooksPath .githooks`. Pre-commit rejects
oversized code commits; pre-push runs `python tools/check.py --require-tracked`.

## Workflow

The canonical human/AI workflow is [WORKFLOW.md](WORKFLOW.md). Keep this file focused on technical
contribution details and do not duplicate the operating procedure here. The review checklist lives in
the pull request template.

## Dependencies

Add a runtime dependency only when the implementation imports it. Remove it when its last caller is
deleted. Client dependencies belong in `Client/pyproject.toml`; server dependencies belong in
`Server/pyproject.toml`. Do not add a package solely to replace a small standard-library operation.

## Publication

Uploading, deploying, pushing, and remote copying require an explicit user instruction. A passing
release checklist authorizes readiness; it does not authorize deployment.
