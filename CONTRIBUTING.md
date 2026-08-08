# Contributing to UParlor

UParlor is developed with VS Code and Copilot, but every change remains the developer's responsibility.
Repository instructions, checks, review, and human verification are the trust boundary.

## Setup

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\Client[test]" -e ".\Server[test]"
pwsh -File tools\check.ps1
```

Use Nerd Font Mono v3 for UI work. The tracked `.vscode` settings configure Pylance paths and pytest;
the recommended extensions appear when the workspace opens.

## Workflow

The canonical human/AI workflow is [WORKFLOW.md](WORKFLOW.md). Keep this file focused on technical
contribution details and do not duplicate the operating procedure here.

## Definition of done

- The exact requested outcome is demonstrably present.
- State, registration, message, locking, and character contracts remain intact.
- No duplicate implementation, dead definition, unexplained broad catch, or stale dependency was added.
- Automated checks pass on supported Python versions.
- Relevant manual cases pass with safe evidence.
- Documentation and dependency declarations match runtime behavior.

## Dependencies

Add a runtime dependency only when the implementation imports it. Remove it when its last caller is
deleted. Client dependencies belong in `Client/pyproject.toml`; server dependencies belong in
`Server/pyproject.toml`. Do not add a package solely to replace a small standard-library operation.

## Publication

Uploading, deploying, pushing, and remote copying require an explicit user instruction. A passing
release checklist authorizes readiness; it does not authorize deployment.
