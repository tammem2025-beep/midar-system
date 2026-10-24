# Backward-compatible launcher alias retained for existing local workflows.
$ErrorActionPreference = "Stop"
$officialLauncher = Join-Path $PSScriptRoot "run-m-windows.ps1"
if (-not (Test-Path -LiteralPath $officialLauncher -PathType Leaf)) {
    throw "The official launcher run-m-windows.ps1 is missing."
}
& $officialLauncher @args
exit $LASTEXITCODE
