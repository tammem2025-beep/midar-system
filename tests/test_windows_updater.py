from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "tools" / "M-Update.ps1"


def test_windows_updater_uses_public_release_assets_not_actions_artifacts():
    source = UPDATER.read_text(encoding="utf-8")
    assert "/releases/latest" in source
    assert "browser_download_url" in source
    assert "SHA256SUMS.txt" in source
    assert "Get-FileHash" in source
    assert "actions/runs/$($run.id)/artifacts" not in source
    assert "archive_download_url" not in source


def test_windows_updater_checks_release_version_origin_and_preserves_local_data():
    source = UPDATER.read_text(encoding="utf-8")
    assert r"^v(?<version>\d+\.\d+\.\d+)$" in source
    assert "$assetUri.Host -ne 'github.com'" in source
    assert "robocopy.exe" in source
    assert "LOCALAPPDATA" in source
    assert "No Windows security feature was disabled." in source
    assert "Start-Process -FilePath $installedExe" in source
