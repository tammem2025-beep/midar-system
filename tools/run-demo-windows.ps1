param([switch]$LAN)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $PyLauncher) { throw "Python 3.12 or 3.13 is required. Run the official M launcher first." }
    & $PyLauncher.Source -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the demo Python environment." }
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    & $Python -m pip install -r (Join-Path $ProjectRoot "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Failed to install demo dependencies." }
}

$DataDir = Join-Path $ProjectRoot "demo-data"
$Database = Join-Path $DataDir "m-demo.db"
$EnvFile = Join-Path $DataDir ".env"
$HasDatabase = Test-Path -LiteralPath $Database -PathType Leaf
$HasEnv = Test-Path -LiteralPath $EnvFile -PathType Leaf
if (!$HasDatabase -and !$HasEnv) {
    & $Python (Join-Path $ProjectRoot "tools\seed_demo.py") --data-dir $DataDir
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the isolated sample database." }
} elseif (!$HasDatabase -or !$HasEnv) {
    throw "The demo directory is incomplete. Preserve it for inspection; this launcher will not overwrite existing data. Review demo-data and restore the missing file from a backup if available."
}

$HostAddress = if ($LAN) { "0.0.0.0" } else { "127.0.0.1" }
if ($LAN) {
    Write-Host "LAN DEMO PREVIEW: private Wi-Fi only; HTTP is not encrypted. Never use real or sensitive data." -ForegroundColor Yellow
    $LanAddresses = @(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.InterfaceAlias -notmatch "Loopback" } |
        Select-Object -ExpandProperty IPAddress -Unique)
    Write-Host "On this PC use http://127.0.0.1:8001" -ForegroundColor Green
    if ($LanAddresses.Count -gt 0) {
        Write-Host "From another device on the same trusted Wi-Fi, try:" -ForegroundColor Cyan
        $LanAddresses | ForEach-Object { Write-Host ("  http://" + $_ + ":8001") -ForegroundColor Cyan }
    }
} else {
    Write-Host "Starting isolated M demo at http://127.0.0.1:8001" -ForegroundColor Green
}

$env:M_PROJECT_DIR = $ProjectRoot
Push-Location (Join-Path $ProjectRoot "backend")
try {
    & $Python -m uvicorn app.main:app --host $HostAddress --port 8001 --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) { throw "Demo server stopped with an error." }
} finally {
    Pop-Location
}
