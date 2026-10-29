from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def test_brand_and_social_hub_modules_are_the_last_runtime_css_layers():
    builder = (ROOT / "tools" / "build_frontend_css.py").read_text(encoding="utf-8")
    assert '"13-design-system.css"' in builder
    assert '"14-m-brand-identity.css"' in builder
    assert '"15-social-hub-premium.css"' in builder
    assert builder.index('"14-m-brand-identity.css"') > builder.index('"13-design-system.css"')
    assert builder.index('"15-social-hub-premium.css"') > builder.index('"14-m-brand-identity.css"')


def test_design_system_defines_semantic_tokens_and_both_color_modes():
    source = (ROOT / "frontend" / "styles-src" / "13-design-system.css").read_text(encoding="utf-8")
    brand = (ROOT / "frontend" / "styles-src" / "14-m-brand-identity.css").read_text(encoding="utf-8")
    for token in (
        "--md-page", "--md-surface", "--md-surface-raised", "--md-text",
        "--md-text-muted", "--md-border", "--md-accent", "--md-action",
        "--md-shadow-sm", "--md-control-height", "--md-space-4",
    ):
        assert token in source
    assert ':root[data-theme="light"]' in source
    assert ':root[data-theme="light"]' in brand
    assert ':root[data-accent="blue"]' in brand
    for accent in ("blue", "cyan", "violet", "emerald", "rose", "amber"):
        assert f':root[data-accent="{accent}"]' in brand


def test_core_visual_contract_covers_shell_forms_tables_popovers_and_reduced_motion():
    source = (ROOT / "frontend" / "styles-src" / "14-m-brand-identity.css").read_text(encoding="utf-8")
    required = (
        ".topbar", ".sidebar", ".content", ".page-head", ".btn-primary",
        ".field input", ".nav button.active", ".auth-card", ".workspace-monogram",
        "@media (max-width: 760px)", "@media (max-width: 430px)",
        "prefers-reduced-motion: reduce",
    )
    for selector in required:
        assert selector in source
    assert re.search(r"\.topbar\s*\{[^}]*height:\s*60px", source, re.S)
    assert "--m-brand-gradient" in source
    assert "--pri: var(--md-action)" in source
    assert "--dc-violet: var(--md-accent)" in source
    assert "--cm-violet: var(--md-accent)" in source
    assert ".dashboard-v2 .dc-panel" in source
    assert ".cm-page .cm-view-switch button.is-active" in source


def test_m_brand_assets_and_pwa_metadata_are_coherent():
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "frontend" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert '<title>M</title>' in page
    assert "Manage. Connect. Grow." in page
    assert "/brand-m-mark.svg" in page
    assert '<button class="topbar-action" type="button" id="globalCreatePostBtn"' in page
    assert "accountSettingsBtn" not in page
    assert "languageToggleBtn" in page and "languageToggleAuthBtn" in page
    assert '/i18n.js?v=0.26.0' in page
    assert '<h1>M</h1>' not in page
    assert '<b>M</b>' not in page
    lockup = (ROOT / "frontend" / "brand-lockup.svg").read_text(encoding="utf-8")
    assert '>M</text>' not in lockup
    assert "Manage. Connect. Grow." in lockup
    assert manifest["name"] == "M"
    assert manifest["short_name"] == "M"
    for filename in (
        "brand-m-mark.svg", "brand-lockup.svg", "i18n.js", "icon.svg", "icon-192.png",
        "icon-512.png", "apple-touch-icon.png", "favicon.ico",
    ):
        assert (ROOT / "frontend" / filename).is_file(), filename


def test_runtime_assets_use_a_single_release_version():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version == "0.26.0"
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    sw = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    api = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert f"midar-ui.css?v={version}" in page
    assert "m-shell-v0260-social-hub-premium" in sw
    assert f"sw.js?v={version}" in app
    assert f'version="{version}"' in api

def test_brand_fallback_and_redundant_account_footer_refinement():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    brand = (ROOT / "frontend" / "styles-src" / "14-m-brand-identity.css").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "accent_color:'blue'" in app
    assert ".sidebar-footer { display: none !important; }" in brand
    # The header account menu stays as the single visible account/logout control.
    assert 'id="accountMenuBtn"' in page
    assert 'id="accountLogoutBtn"' in page
    assert 'id="profileAvatar"' in page



def test_sidebar_active_state_uses_selected_brand_accent():
    brand = (ROOT / "frontend" / "styles-src" / "14-m-brand-identity.css").read_text(encoding="utf-8")
    assert ".sidebar .nav button.active" in brand
    assert "background: linear-gradient(125deg, color-mix(in srgb, var(--md-accent) 25%" in brand
    assert ":root[data-theme=\"light\"] .sidebar .nav button.active" in brand



def test_windows_launcher_is_ascii_safe_for_legacy_powershell():
    launcher = (ROOT / "run-m-windows.ps1").read_text(encoding="utf-8")
    assert launcher.isascii(), "Keep the Windows PowerShell launcher ASCII-only; UTF-8 without BOM can be misread by Windows PowerShell 5.1."



def test_same_release_social_feed_and_keyboard_menu_improvements():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    page = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    sw = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    brand = (ROOT / "frontend" / "styles-src" / "14-m-brand-identity.css").read_text(encoding="utf-8")
    bundle = (ROOT / "frontend" / "midar-ui.css").read_text(encoding="utf-8")

    assert "safeHttpsMediaUrl" in app
    assert "metaMediaFilter" in app
    assert "selected==='reels'" in app
    assert 'data-view-remote-media="' in app
    assert "event.key==='Escape'" in app
    assert 'href="/midar-ui.css?v=0.26.0"' in page
    assert "m-shell-v0260-social-hub-premium" in sw
    assert "Same-release visual patch" in brand
    assert "Same-release visual patch" in bundle
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.26.0"


def test_portable_windows_archive_has_independent_data_directory():
    launcher = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(encoding="utf-8")

    assert "portable-mode.flag" in launcher
    assert "M-Portable-Data" in launcher
    assert "M-Windows-x64-Portable" in workflow
    assert "M-Portable-0.26.0-Windows-x64.zip" in workflow


def test_account_connect_actions_and_local_video_playback_are_exposed():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    settings = (ROOT / "frontend" / "settings-enhanced.js").read_text(encoding="utf-8")

    # Platform icons are the in-app entry points; external homepage shortcuts are removed.
    assert "data-open-provider" in app
    assert "data-open-platform-account" in app
    assert "openPlatformWorkspace" in app
    assert "platformHomeUrls" not in app
    assert "provider-launchpad" not in app
    assert "data-connect-provider" in app
    assert "providerConnectKeys" in app
    assert "startSocialProviderConnect" in settings
    assert "/integrations/oauth/${provider}/connect-url" in settings

    # Uploaded videos are fetched through the authenticated media endpoint and
    # rendered in a native HTML5 player.
    assert "async function previewMediaAsset" in app
    assert 'data-media-preview="' in app
    assert "Authorization:'Bearer '+token" in app
    assert '<video class="studio-preview-player" controls autoplay playsinline' in app


def test_social_hub_icons_and_premium_layer_are_present():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    module = (ROOT / "frontend" / "styles-src" / "15-social-hub-premium.css").read_text(encoding="utf-8")
    bundle = (ROOT / "frontend" / "midar-ui.css").read_text(encoding="utf-8")
    assert 'data-open-provider="${esc(p.platform)}"' in app
    assert ".provider-symbol.provider-launch-icon" in module
    assert ".provider-card:hover" in module
    assert ':root[data-theme="light"] .provider-card' in module
    assert "15-social-hub-premium.css" in (ROOT / "tools" / "build_frontend_css.py").read_text(encoding="utf-8")
    assert "M 0.26.0 — premium social hub" in module
    assert "M 0.26.0 — premium social hub" in bundle
