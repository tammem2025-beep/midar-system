# M updater for the existing Windows installation.
# Downloads the latest successful Windows artifact for the exact current main commit,
# verifies the installer SHA-256, backs up local data, updates in place, then launches M.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# Windows PowerShell 5.1 compatibility: use TLS 1.2 for GitHub HTTPS endpoints.
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
}

$Owner = 'tammem2025-beep'
$Repo = 'midar-system'
$ApiBase = "https://api.github.com/repos/$Owner/$Repo"
$Headers = @{
    Accept = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent' = 'M-Update-PowerShell'
}
$ExpectedAppId = '9B603A66-E9BC-4E6F-A106-4A6F75430C9E'
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ('M-Update-' + [Guid]::NewGuid().ToString('N'))
$Succeeded = $false

try {
    Write-Host ''
    Write-Host 'M updater - existing installation' -ForegroundColor Cyan
    Write-Host 'Checking the current GitHub version and Windows build...' -ForegroundColor Gray

    $mainRef = Invoke-RestMethod -Uri "$ApiBase/git/ref/heads/main" -Headers $Headers -Method Get
    $mainSha = [string]$mainRef.object.sha
    if ($mainSha -notmatch '^[a-fA-F0-9]{40}$') {
        throw 'GitHub returned an invalid main commit SHA. No changes were made.'
    }

    $runsUri = "$ApiBase/actions/workflows/release-windows.yml/runs?branch=main&status=success&per_page=50"
    $runList = Invoke-RestMethod -Uri $runsUri -Headers $Headers -Method Get
    $matchingRuns = @($runList.workflow_runs | Where-Object {
        $_.head_sha -eq $mainSha -and $_.status -eq 'completed' -and $_.conclusion -eq 'success'
    } | Sort-Object -Property created_at -Descending)
    if ($matchingRuns.Count -eq 0) {
        throw 'There is no successful Windows build for the latest main commit yet. Open https://github.com/tammem2025-beep/midar-system/actions and retry after the Windows build succeeds.'
    }
    $run = $matchingRuns[0]

    $artifactsUri = "$ApiBase/actions/runs/$($run.id)/artifacts?per_page=100"
    $artifactList = Invoke-RestMethod -Uri $artifactsUri -Headers $Headers -Method Get
    $matchingArtifacts = @($artifactList.artifacts | Where-Object {
        $_.name -eq 'M-Windows-x64-Installer' -and $_.expired -eq $false
    } | Sort-Object -Property created_at -Descending)
    if ($matchingArtifacts.Count -eq 0) {
        throw 'The successful build has no unexpired installer artifact. No files were changed.'
    }
    $artifact = $matchingArtifacts[0]
    if ($artifact.workflow_run.head_sha -and $artifact.workflow_run.head_sha -ne $mainSha) {
        throw 'The installer artifact does not match the current main commit. Refusing to install an older build.'
    }

    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    $artifactZip = Join-Path $TempRoot 'M-Windows-x64-Installer-artifact.zip'
    $extractDir = Join-Path $TempRoot 'extracted'
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

    Write-Host "Downloading Windows build from run $($run.id) ..." -ForegroundColor Gray
    $downloaded = $false
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $artifact.archive_download_url -Headers $Headers -OutFile $artifactZip -UseBasicParsing
            if ((Test-Path -LiteralPath $artifactZip) -and (Get-Item -LiteralPath $artifactZip).Length -gt 5000000) {
                $downloaded = $true
                break
            }
            throw 'The downloaded artifact was unexpectedly small.'
        } catch {
            if ($attempt -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
    if (-not $downloaded) { throw 'Could not download the installer artifact.' }

    Expand-Archive -LiteralPath $artifactZip -DestinationPath $extractDir -Force
    $installer = Get-ChildItem -LiteralPath $extractDir -Filter 'M-Setup-*-Windows-x64.exe' -File -Recurse | Select-Object -First 1
    $checksumFile = Get-ChildItem -LiteralPath $extractDir -Filter 'SHA256SUMS.txt' -File -Recurse | Select-Object -First 1
    if (-not $installer) { throw 'The artifact did not contain the M Windows installer.' }
    if (-not $checksumFile) { throw 'The artifact did not contain SHA256SUMS.txt; refusing to run an unverified installer.' }

    $escapedName = [Regex]::Escape($installer.Name)
    $checksumLine = Get-Content -LiteralPath $checksumFile.FullName | Where-Object {
        $_ -match ('^([a-fA-F0-9]{64})\s+\*?' + $escapedName + '$')
    } | Select-Object -First 1
    if (-not $checksumLine -or $checksumLine -notmatch ('^([a-fA-F0-9]{64})\s+\*?' + $escapedName + '$')) {
        throw 'The installer has no matching SHA-256 entry; refusing to run it.'
    }
    $expectedHash = $Matches[1].ToUpperInvariant()
    $actualHash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Installer SHA-256 verification failed. Expected $expectedHash, got $actualHash."
    }

    Write-Host "Verified installer: $($installer.Name)" -ForegroundColor Green
    Write-Host "Verified source commit: $mainSha" -ForegroundColor Gray

    $running = @(Get-Process -Name 'M' -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        Write-Host 'M is currently open. Save your work, then press Enter to close M and continue.' -ForegroundColor Yellow
        [void](Read-Host)
        $running = @(Get-Process -Name 'M' -ErrorAction SilentlyContinue)
        foreach ($process in $running) {
            try {
                if ($process.MainWindowHandle -ne [IntPtr]::Zero) { [void]$process.CloseMainWindow() }
            } catch { }
        }
        $deadline = (Get-Date).AddSeconds(15)
        do {
            Start-Sleep -Seconds 1
            $running = @(Get-Process -Name 'M' -ErrorAction SilentlyContinue)
        } while ($running.Count -gt 0 -and (Get-Date) -lt $deadline)
        if ($running.Count -gt 0) {
            throw 'M is still running. Close it normally from its window, then run this update script again. The installed files have not been replaced.'
        }
    }

    # Preserve the existing user's database, uploads, environment file and logs.
    $dataDir = Join-Path $env:LOCALAPPDATA 'M'
    $backupPath = $null
    if (Test-Path -LiteralPath $dataDir) {
        $documents = [Environment]::GetFolderPath('MyDocuments')
        if ([string]::IsNullOrWhiteSpace($documents) -or -not (Test-Path -LiteralPath $documents)) {
            $documents = $env:USERPROFILE
        }
        $backupRoot = Join-Path $documents 'M-Backups'
        $backupPath = Join-Path $backupRoot ('M-Backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
        Write-Host "Backing up local M data to: $backupPath" -ForegroundColor Gray
        & robocopy.exe $dataDir $backupPath /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XJ /NFL /NDL /NP | Out-Null
        $copyResult = $LASTEXITCODE
        if ($copyResult -ge 8) {
            throw "Backup failed (robocopy code $copyResult); installation was stopped. Check: $backupPath"
        }
        Write-Host 'Local data backup completed.' -ForegroundColor Green
    } else {
        Write-Host 'No existing %LOCALAPPDATA%\M data folder was found; this will be a first install or a custom setup.' -ForegroundColor Yellow
    }

    Write-Host 'Installing M in place. Existing data is stored outside the application folder.' -ForegroundColor Cyan
    $installArgs = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
    $installProcess = Start-Process -FilePath $installer.FullName -ArgumentList $installArgs -Wait -PassThru
    if ($installProcess.ExitCode -ne 0) {
        throw "The M installer exited with code $($installProcess.ExitCode). Review the installation and backup before retrying."
    }

    # Locate the existing per-user installation using its Inno Setup AppId, then fall back to the default path.
    $candidateExePaths = New-Object 'System.Collections.Generic.List[string]'
    $uninstallRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $uninstallRoots) {
        if (Test-Path -LiteralPath $root) {
            foreach ($key in (Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
                if ($key.PSChildName -match $ExpectedAppId) {
                    $entry = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction SilentlyContinue
                    if ($entry -and $entry.InstallLocation) {
                        $candidateExePaths.Add((Join-Path ([string]$entry.InstallLocation) 'M.exe'))
                    }
                }
            }
        }
    }
    $candidateExePaths.Add((Join-Path $env:LOCALAPPDATA 'Programs\M\M.exe'))
    $installedExe = $null
    foreach ($candidate in $candidateExePaths) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $installedExe = $candidate
            break
        }
    }

    if ($installedExe) {
        Start-Process -FilePath $installedExe -WorkingDirectory (Split-Path -Parent $installedExe)
        Write-Host 'M was updated and launched successfully.' -ForegroundColor Green
    } else {
        Write-Host 'M was updated successfully. Open it from the Windows Start menu if it did not launch automatically.' -ForegroundColor Green
    }
    if ($backupPath) { Write-Host "Data backup: $backupPath" -ForegroundColor Gray }
    Write-Host "Build commit: $mainSha" -ForegroundColor Gray
    Write-Host 'Note: this script does not disable Windows SmartScreen or Defender.' -ForegroundColor Yellow
    $Succeeded = $true
} catch {
    Write-Host ''
    Write-Host ('UPDATE FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'No Windows security feature was disabled.' -ForegroundColor Yellow
    if (Test-Path -LiteralPath $TempRoot) { Write-Host "Temporary diagnostic files were kept at: $TempRoot" -ForegroundColor Gray }
    exit 1
} finally {
    if ($Succeeded -and (Test-Path -LiteralPath $TempRoot)) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
