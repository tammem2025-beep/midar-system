$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$createdVenv = $false
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $launcher) {
        $selected = $false
        foreach ($version in @("-3.13", "-3.12", "")) {
            if ($version) { & $launcher.Source $version --version *> $null }
            else { & $launcher.Source --version *> $null }
            if ($LASTEXITCODE -eq 0) {
                if ($version) { & $launcher.Source $version -m venv .venv }
                else { & $launcher.Source -m venv .venv }
                if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv." }
                $createdVenv = $true
                $selected = $true
                break
            }
        }
        if (-not $selected) { throw "Install Python 3.12 or 3.13, or make a supported Python launcher available." }
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $python) { throw "Python was not found. Install Python 3.12 or 3.13 first." }
        & $python.Source -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv." }
        $createdVenv = $true
    }
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { throw "The project virtual environment was not created." }

$envPath = Join-Path $projectRoot ".env"
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    $template = Join-Path $projectRoot ".env.example"
    if (-not (Test-Path -LiteralPath $template -PathType Leaf)) { throw ".env.example is missing." }
    Copy-Item -LiteralPath $template -Destination $envPath
    $secret = (& $venvPython -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($secret)) { throw "Could not generate a local SECRET_KEY." }
    $text = [System.IO.File]::ReadAllText($envPath)
    $text = $text.Replace("REPLACE_WITH_GENERATED_SECRET", $secret)
    $utf8NoBom = New-Object System.Text.UTF8Encoding -ArgumentList $false
    [System.IO.File]::WriteAllText($envPath, $text, $utf8NoBom)
    Write-Host "Created a local .env with a random secret. Existing .env files are never overwritten." -ForegroundColor Green
}

if ($createdVenv) {
    Write-Host "Installing M dependencies into the new virtual environment..." -ForegroundColor Cyan
    & $venvPython -m pip install -r (Join-Path $projectRoot "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
} else {
    & $venvPython -c "import fastapi, uvicorn, sqlalchemy, dotenv, httpx, httpx2, PIL, jwt"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Required imports are missing; installing declared dependencies..." -ForegroundColor Yellow
        & $venvPython -m pip install -r (Join-Path $projectRoot "backend\requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }
}

Write-Host "Starting M — Digital Business Management at http://127.0.0.1:8000" -ForegroundColor Green
Push-Location (Join-Path $projectRoot "backend")
try {
    & $venvPython -m uvicorn app.main:app --reload --port 8000 --env-file (Join-Path $projectRoot ".env")
    if ($LASTEXITCODE -ne 0) { throw "M server stopped with an error." }
} finally {
    Pop-Location
}
