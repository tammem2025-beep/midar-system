# M updater for the existing Windows installation.
# Downloads the latest stable public GitHub Release installer (not an Actions artifact),
# verifies SHA-256, backs up local data, updates in place, then launches M.

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
    Write-Host 'Checking the latest stable public GitHub release...' -ForegroundColor Gray

    # Prefer the public GitHub Release assets. Actions artifact download URLs can return
    # 401 Unauthorized without an authenticated GitHub session, even for a public repository.
    $release = Invoke-RestMethod -Uri "$ApiBase/releases/latest" -Headers $Headers -Method Get
    $releaseTag = [string]$release.tag_name
    if ($release.draft -or $release.prerelease -or $releaseTag -notmatch '^v(?<version>\d+\.\d+\.\d+)$') {
        throw 'GitHub did not return a valid stable M release. No local files were changed.'
    }
    $version = $Matches['version']
    $installerName = "M-Setup-$version-Windows-x64.exe"
    $releaseAssets = @($release.assets)
    $installerAssets = @($releaseAssets | Where-Object { $_.name -eq $installerName })
    $checksumAssets = @($releaseAssets | Where-Object { $_.name -eq 'SHA256SUMS.txt' })
    if ($installerAssets.Count -ne 1 -or $checksumAssets.Count -ne 1) {
        throw "The latest release $releaseTag is missing its expected installer or SHA256SUMS.txt. No local files were changed."
    }
    $installerAsset = $installerAssets[0]
    $checksumAsset = $checksumAssets[0]
    $expectedAssetPrefix = "/$Owner/$Repo/releases/download/$releaseTag/"
    foreach ($asset in @($installerAsset, $checksumAsset)) {
        [Uri]$assetUri = $null
        if (-not [Uri]::TryCreate([string]$asset.browser_download_url, [UriKind]::Absolute, [ref]$assetUri) -or
            $assetUri.Scheme -ne 'https' -or $assetUri.Host -ne 'github.com' -or
            -not $assetUri.AbsolutePath.StartsWith($expectedAssetPrefix, [StringComparison]::Ordinal)) {
            throw 'GitHub returned a release asset URL outside the official M release path. Refusing to download it.'
        }
    }

    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    $installerPath = Join-Path $TempRoot $installerName
    $checksumPath = Join-Path $TempRoot 'SHA256SUMS.txt'

    Write-Host "Downloading public M release $releaseTag ..." -ForegroundColor Gray
    # browser_download_url is a public Releases URL; it does not use the Actions artifact endpoint.
    Invoke-WebRequest -Uri $installerAsset.browser_download_url -Headers @{ 'User-Agent' = 'M-Update-PowerShell' } -OutFile $installerPath -UseBasicParsing
    Invoke-WebRequest -Uri $checksumAsset.browser_download_url -Headers @{ 'User-Agent' = 'M-Update-PowerShell' } -OutFile $checksumPath -UseBasicParsing

    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf) -or
        (Get-Item -LiteralPath $installerPath).Length -lt 5000000) {
        throw 'The downloaded installer is missing or unexpectedly small.'
    }
    if ($installerAsset.size -and (Get-Item -LiteralPath $installerPath).Length -ne [long]$installerAsset.size) {
        throw 'The installer size differs from GitHub release metadata. Refusing to run it.'
    }
    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf) -or
        (Get-Item -LiteralPath $checksumPath).Length -gt 16384) {
        throw 'The release checksum file is missing or unexpectedly large.'
    }

    $escapedName = [Regex]::Escape($installerName)
    $checksumLine = Get-Content -LiteralPath $checksumPath | Where-Object {
        $_ -match ('^([a-fA-F0-9]{64})\s+\*?' + $escapedName + '$')
    } | Select-Object -First 1
    if (-not $checksumLine -or $checksumLine -notmatch ('^([a-fA-F0-9]{64})\s+\*?' + $escapedName + '$')) {
        throw 'The official release has no matching SHA-256 entry for the installer; refusing to run it.'
    }
    $expectedHash = $Matches[1].ToUpperInvariant()
    $actualHash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Installer SHA-256 verification failed. Expected $expectedHash, got $actualHash."
    }
    $installer = Get-Item -LiteralPath $installerPath
    Write-Host "Verified installer: $($installer.Name)" -ForegroundColor Green
    Write-Host "Verified release: $releaseTag" -ForegroundColor Gray

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
    Write-Host "Installed release: $releaseTag" -ForegroundColor Gray
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
