[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$RequireTracked
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
$separator = [IO.Path]::PathSeparator
$env:PYTHONPATH = @(
    (Join-Path $root "Client"),
    (Join-Path $root "Server")
) -join $separator

# tests/ 只在本机保留（不进入仓库），CI 检出中不存在时跳过。
$sourceDirs = @("Client\client", "Server\server", "tools")
$hasTests = Test-Path (Join-Path $root "tests")
if ($hasTests) {
    $sourceDirs += "tests"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Label,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )
    Write-Host "`n==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked "Repository policy" {
    $policyArgs = @("tools\repo_policy.py")
    if ($RequireTracked) {
        $policyArgs += "--require-tracked"
    }
    & $python @policyArgs
}
Invoke-Checked "Python syntax" {
    & $python -m compileall -q @sourceDirs
}
Invoke-Checked "Ruff name and dead-local safety" {
    & $python -m ruff check @sourceDirs `
        --select F401,F821,F822,F823,F841 `
        --output-format concise
}
if (-not $SkipTests -and $hasTests) {
    Invoke-Checked "Pytest" { & $python -m pytest -q }
}

Write-Host "`nAll repository checks passed."
