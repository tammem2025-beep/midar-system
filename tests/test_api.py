"""Integration tests for Midar's internal MVP API.

Each test uses an isolated schema inside a temporary SQLite file. These tests
verify the behaviors we can prove locally; third-party connector availability
is intentionally not simulated.
"""
from __future__ import annotations

import os
import csv
import io
import logging
import subprocess
from datetime import timedelta
import re
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

import pytest

_test_home = tempfile.TemporaryDirectory(prefix="midar-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_test_home.name) / 'test.db'}"
os.environ["MEDIA_DIR"] = str(Path(_test_home.name) / "media")
os.environ["SECRET_KEY"] = "test-secret-key-which-is-long-enough-for-testing-000000000"
os.environ["APP_ENV"] = "test"
os.environ["TOKEN_TTL_SECONDS"] = "3600"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest
from app.db import Base, SessionLocal, engine
import app.main as main_module
from app.main import ROLE_PERMISSIONS, ROLE_READ_PERMISSIONS, ALL_AREAS, app
from app.models import AuditLog, AuthFailure, IntegrationCredential, Membership, Organization, SocialAccount, User, utcnow
from app.security import hash_password


@pytest.fixture()
def client():
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_owner(client: TestClient, email: str = "owner@example.com") -> dict[str, str]:
    response = client.post("/api/v1/auth/setup", json={
        "full_name": "مالك M",
        "email": email,
        "password": "a-long-test-password-123",
        "organization_name": "M للاختبار",
        "timezone": "Asia/Hebron",
    })
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def create_member(client: TestClient, owner_headers: dict[str, str], role: str, email: str) -> dict[str, str]:
    response = client.post("/api/v1/team/members", headers=owner_headers, json={
        "full_name": f"عضو {role}",
        "email": email,
        "temporary_password": "a-temporary-password-123",
        "role": role,
    })
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "a-temporary-password-123",
    })
    assert login.status_code == 200, login.text
    first_token = {"Authorization": "Bearer " + login.json()["access_token"]}
    changed = client.post("/api/v1/auth/change-password", headers=first_token, json={
        "current_password": "a-temporary-password-123",
        "new_password": "a-new-secure-password-456",
    })
    assert changed.status_code == 200, changed.text
    return {"Authorization": "Bearer " + changed.json()["access_token"]}


def test_health_setup_and_core_crud(client: TestClient, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    root = client.get("/")
    assert root.status_code == 200
    assert '<title>M</title>' in root.text and "0.22.0" in root.text
    assert 'href="/midar-ui.css?v=0.22.0"' in root.text
    assert root.text.count('rel="stylesheet"') == 1
    assert client.get("/midar-ui.css").status_code == 200
    for retired in ("/styles.css", "/theme.css", "/visual-upgrade.css", "/settings-enhanced.css", "/premium-settings.css", "/experience.css", "/premium-experience.css", "/visual-redesign.css", "/dashboard-command.css", "/premium-shell.css", "/content-calendar.css"):
        assert client.get(retired).status_code == 404
    assert client.get("/brand-mark.svg").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200
    js_asset = client.get("/app.js")
    css_asset = client.get("/midar-ui.css")
    icon_asset = client.get("/icon.svg")
    assert js_asset.status_code == 200 and "/integrations/catalog" in js_asset.text
    assert all(token in js_asset.text for token in ("dashboard-v2", "dc-content-pipeline", "dc-attention", "dc-agenda"))
    assert all(token in js_asset.text for token in ("data-submit-review", "data-approve-post", "data-request-changes", "review_note"))
    theme_asset = client.get("/midar-ui.css")
    calendar_asset = client.get("/midar-ui.css")
    assert all(token in theme_asset.text for token in ("--m-brand-navy: #0B1020", "--m-brand-cyan: #06C6DE", "--m-brand-blue: #5366FF", "--m-brand-violet: #8B3FF2"))
    assert ".review-note" in calendar_asset.text
    settings_js_asset = client.get("/settings-enhanced.js")
    settings_css_asset = client.get("/midar-ui.css")
    assert settings_js_asset.status_code == 200
    assert settings_css_asset.status_code == 200
    for required_ui_function in ("renderEnhancedSettings", "processGoogleRedirect", "configureGoogleLogin", "loadAndApplyPreferences", "applyAppearancePrefs", "startGoogleLogin"):
        assert f"function {required_ui_function}" in settings_js_asset.text
    assert 'href="/midar-ui.css?v=0.22.0"' in root.text
    assert 'src="/settings-enhanced.js' in root.text
    assert css_asset.status_code == 200 and ".provider-grid" in css_asset.text
    assert icon_asset.status_code == 200 and "linearGradient" in icon_asset.text
    assert client.get("/api/v1/health").json()["database"] == "ok"
    assert client.get("/api/v1/auth/status").json()["setup_required"] is True
    headers = create_owner(client)
    assert client.get("/api/v1/auth/status").json()["setup_required"] is False
    second_setup = client.post("/api/v1/auth/setup", json={
        "full_name": "مالك ثانٍ", "email": "other-owner@example.com",
        "password": "another-long-password-456", "organization_name": "مساحة أخرى"
    })
    assert second_setup.status_code == 409

    contact = client.post("/api/v1/contacts", headers=headers, json={
        "name": "عميل تجريبي", "company": "شركة المثال", "email": "CLIENT@example.com",
        "source": "Instagram", "stage": "qualified", "value": 1500, "notes": "سجل للاختبار"
    })
    assert contact.status_code == 201, contact.text
    assert contact.json()["email"] == "client@example.com"
    contact_id = contact.json()["id"]
    task = client.post("/api/v1/tasks", headers=headers, json={
        "title": "متابعة العميل", "assignee": "مستخدم تجريبي", "priority": "high", "status": "open"
    })
    assert task.status_code == 201, task.text
    post = client.post("/api/v1/posts", headers=headers, json={
        "title": "مسودة إطلاق", "content": "نص تجريبي", "platform": "Facebook", "status": "draft"
    })
    assert post.status_code == 201, post.text
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Instagram", "account_name": "صفحة تجريبية", "handle": "@demo"
    })
    assert account.status_code == 201, account.text
    assert account.json()["connection_status"] == "disconnected"
    duplicate = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Instagram", "account_name": "نسخة أخرى", "handle": "@demo"
    })
    assert duplicate.status_code == 409

    campaign = client.post("/api/v1/campaigns", headers=headers, json={
        "name": "حملة الافتتاح", "objective": "awareness", "status": "planning", "budget": 1200
    })
    assert campaign.status_code == 201, campaign.text
    dashboard = client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["counts"]["contacts"] == 1
    assert dashboard.json()["counts"]["active_tasks"] == 1
    assert dashboard.json()["counts"]["total_tasks"] == 1
    assert dashboard.json()["counts"]["overdue_tasks"] == 0
    assert dashboard.json()["counts"]["total_posts"] == 1
    assert dashboard.json()["counts"]["draft_posts"] == 1
    assert dashboard.json()["integrations_live"] is False
    updated = client.put(f"/api/v1/contacts/{contact_id}", headers=headers, json={
        "name": "عميل تجريبي", "company": "شركة المثال", "email": "client@example.com",
        "source": "Instagram", "stage": "won", "value": 1500, "notes": "تم البيع"
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["stage"] == "won"
    logs = client.get("/api/v1/audit-logs", headers=headers)
    assert logs.status_code == 200 and len(logs.json()) >= 6
    integrations = client.get("/api/v1/integrations/status", headers=headers)
    assert integrations.status_code == 200
    assert integrations.json()["external_actions_enabled"] is False
    providers = {p["platform"]: p for p in integrations.json()["providers"]}
    assert providers["Telegram"]["connector_implemented"] is True
    assert providers["Telegram"]["supported_actions"] == ["verify_channel", "publish_text"]
    assert all(not p["connector_implemented"] for name, p in providers.items() if name != "Telegram")



def test_provider_catalog_is_truthful_and_never_exposes_secret_values(client: TestClient, monkeypatch):
    secret = "123456789:never-return-this-secret-token"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", secret)
    owner = create_owner(client)
    response = client.get("/api/v1/integrations/catalog", headers=owner)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["release"] == "0.22.0"
    providers = {p["platform"]: p for p in payload["providers"]}
    assert set(providers) == {"Facebook", "Instagram", "WhatsApp", "Telegram", "X", "YouTube", "TikTok", "LinkedIn", "Other"}
    assert providers["Telegram"]["implementation_status"] == "partial"
    assert providers["Telegram"]["implemented_capabilities"] == ["verify_destination", "publish_text"]
    assert providers["Facebook"]["implementation_status"] == "planned"
    assert providers["Facebook"]["implemented_capabilities"] == []
    assert all((p["docs_url"] is None or p["docs_url"].startswith("https://")) for p in providers.values())
    assert secret not in response.text
    assert "التسجيل في الكتالوج لا يعني" in payload["notice"]

    editor = create_member(client, owner, "editor", "catalog-editor@example.com")
    assert client.get("/api/v1/integrations/catalog", headers=editor).status_code == 200
    assert client.get("/api/v1/integrations/status", headers=editor).status_code == 403


def test_integration_status_does_not_confuse_credentials_with_implementation(client: TestClient, monkeypatch):
    monkeypatch.setenv("META_APP_ID", "demo-client-id")
    monkeypatch.setenv("META_APP_SECRET", "demo-client-secret")
    monkeypatch.setenv("META_REDIRECT_URI", "https://example.invalid/callback")
    owner = create_owner(client)
    response = client.get("/api/v1/integrations/status", headers=owner)
    assert response.status_code == 200, response.text
    providers = {p["platform"]: p for p in response.json()["providers"]}
    assert providers["Facebook"]["credentials_present"] is True
    assert providers["Facebook"]["connector_implemented"] is False
    assert providers["Facebook"]["supported_actions"] == []
    assert providers["Telegram"]["connector_implemented"] is True


def test_unmatched_request_path_is_not_written_to_logs():
    # Unknown routes must not fall back to raw path segments, which may contain
    # customer identifiers or accidentally exposed secrets.
    raw_path = "/internal/reset-token-should-not-be-logged"
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": raw_path,
        "raw_path": raw_path.encode("ascii"), "query_string": b"", "root_path": "",
        "headers": [], "server": ("testserver", 80), "client": ("testclient", 12345),
    }
    request = StarletteRequest(scope)
    assert main_module._request_log_path(request) == "<unmatched-route>"


def test_request_observability_headers_and_logs_redact_query_strings(client: TestClient, caplog, monkeypatch):
    monkeypatch.setattr(main_module, "SLOW_REQUEST_THRESHOLD_MS", 0.0)
    caplog.set_level(logging.WARNING, logger="midar.request")

    response = client.get("/api/v1/auth/status?access_token=DO_NOT_LOG_THIS")
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id", "")
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert response.headers["server-timing"].startswith("app;dur=")
    assert request_id in caplog.text
    assert "request_observed" in caplog.text
    assert "/api/v1/auth/status" in caplog.text
    assert "access_token=DO_NOT_LOG_THIS" not in caplog.text
    assert "DO_NOT_LOG_THIS" not in caplog.text

    second = client.get("/api/v1/auth/status")
    assert second.headers["x-request-id"] != request_id


def test_unhandled_request_returns_correlated_generic_error_without_exception_text(client: TestClient, caplog):
    from fastapi.routing import APIRoute

    def deliberately_fail():
        raise RuntimeError("SENSITIVE-EXCEPTION-MESSAGE")

    route = APIRoute("/__test_request_diagnostics_failure", deliberately_fail, methods=["GET"])
    mount_index = next(i for i, item in enumerate(main_module.app.router.routes) if getattr(item, "name", None) == "frontend")
    main_module.app.router.routes.insert(mount_index, route)
    try:
        caplog.set_level(logging.ERROR, logger="midar.request")
        response = client.get("/__test_request_diagnostics_failure?code=OAUTH-CODE-MUST-NOT-LOG")
    finally:
        main_module.app.router.routes.remove(route)

    assert response.status_code == 500
    request_id = response.headers.get("x-request-id", "")
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    assert response.json()["request_id"] == request_id
    assert "SENSITIVE-EXCEPTION-MESSAGE" not in response.text
    assert "OAUTH-CODE-MUST-NOT-LOG" not in caplog.text
    assert "SENSITIVE-EXCEPTION-MESSAGE" not in caplog.text
    assert request_id in caplog.text
    assert "request_unhandled_exception" in caplog.text


def test_auth_required_and_security_headers(client: TestClient):
    headers_response = client.get("/api/v1/contacts")
    assert headers_response.status_code == 401
    assert headers_response.headers["cache-control"] == "no-store"
    assert headers_response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/v1/tasks").status_code == 401


def test_invalid_scheduled_post_requires_time(client: TestClient):
    headers = create_owner(client)
    response = client.post("/api/v1/posts", headers=headers, json={
        "title": "موعد بلا تاريخ", "platform": "X", "status": "scheduled", "content": ""
    })
    assert response.status_code == 422


def test_workspace_isolation_by_resource_id(client: TestClient):
    owner_headers = create_owner(client)
    created = client.post("/api/v1/contacts", headers=owner_headers, json={"name": "خاص بالمساحة الأولى"})
    assert created.status_code == 201
    contact_id = created.json()["id"]

    # Create a second workspace directly to exercise tenant isolation without
    # exposing a public endpoint that bypasses the one-time first-run setup.
    db = SessionLocal()
    try:
        org2 = Organization(name="مساحة ثانية", timezone="Asia/Hebron")
        db.add(org2)
        db.flush()
        user2 = User(email="owner2@example.com", full_name="مالك ثانٍ", password_hash=hash_password("a-second-secure-password-987"))
        db.add(user2)
        db.flush()
        db.add(Membership(organization_id=org2.id, user_id=user2.id, role="owner"))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"email": "owner2@example.com", "password": "a-second-secure-password-987"})
    assert login.status_code == 200, login.text
    other_headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/api/v1/contacts", headers=other_headers).json() == []
    assert client.get(f"/api/v1/contacts/{contact_id}", headers=other_headers).status_code == 404
    assert client.put(f"/api/v1/contacts/{contact_id}", headers=other_headers, json={"name": "محاولة وصول"}).status_code == 404
    own_contact = client.post("/api/v1/contacts", headers=other_headers, json={"name": "خاص بالمساحة الثانية"})
    assert own_contact.status_code == 201
    assert len(client.get("/api/v1/contacts", headers=owner_headers).json()) == 1


def test_role_permissions_match_api_behavior(client: TestClient):
    headers = create_owner(client)
    support = create_member(client, headers, "support", "support@example.com")
    editor = create_member(client, headers, "editor", "editor@example.com")
    analyst = create_member(client, headers, "analyst", "analyst@example.com")

    assert client.get("/api/v1/contacts", headers=support).status_code == 200
    assert client.post("/api/v1/contacts", headers=support, json={"name": "عميل الدعم"}).status_code == 201
    assert client.post("/api/v1/posts", headers=support, json={"title": "غير مسموح", "platform": "Facebook"}).status_code == 403
    assert client.get("/api/v1/integrations/status", headers=support).status_code == 403

    assert client.get("/api/v1/posts", headers=editor).status_code == 200
    assert client.post("/api/v1/posts", headers=editor, json={"title": "مسودة المحرر", "platform": "Instagram"}).status_code == 201
    assert client.get("/api/v1/contacts", headers=editor).status_code == 403
    assert client.post("/api/v1/contacts", headers=editor, json={"name": "غير مسموح"}).status_code == 403

    assert client.get("/api/v1/contacts", headers=analyst).status_code == 200
    assert client.get("/api/v1/tasks", headers=analyst).status_code == 200
    assert client.post("/api/v1/tasks", headers=analyst, json={"title": "تعديل غير مسموح"}).status_code == 403
    assert client.get("/api/v1/team/members", headers=analyst).status_code == 403

    # Prevent accidental drift where a role can write an area it cannot read,
    # or a route uses an area name absent from the canonical registry.
    assert set(ROLE_READ_PERMISSIONS) == set(ROLE_PERMISSIONS)
    for role in ROLE_PERMISSIONS:
        assert ROLE_PERMISSIONS[role] <= ROLE_READ_PERMISSIONS[role]
        assert ROLE_READ_PERMISSIONS[role] <= ALL_AREAS


def test_local_inbox_records_are_explicitly_not_sent(client: TestClient):
    headers = create_owner(client)
    contact = client.post("/api/v1/contacts", headers=headers, json={"name": "عميل محادثة"})
    assert contact.status_code == 201
    conversation = client.post("/api/v1/conversations", headers=headers, json={
        "channel": "WhatsApp", "contact_id": contact.json()["id"], "status": "open"
    })
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    message = client.post(f"/api/v1/conversations/{conversation_id}/messages", headers=headers, json={
        "body": "مسودة رد للاختبار", "direction": "outbound"
    })
    assert message.status_code == 201
    assert message.json()["delivery_status"] == "local_only"
    assert client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers).json()[0]["body"] == "مسودة رد للاختبار"


def test_session_revocation_and_temporary_password_gate(client: TestClient):
    headers = create_owner(client)
    created = client.post("/api/v1/team/members", headers=headers, json={
        "full_name": "عضو مؤقت", "email": "temporary@example.com",
        "temporary_password": "temporary-secure-pass-123", "role": "editor"
    })
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": "temporary@example.com", "password": "temporary-secure-pass-123"})
    temp_headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.get("/api/v1/posts", headers=temp_headers).status_code == 403
    changed = client.post("/api/v1/auth/change-password", headers=temp_headers, json={
        "current_password": "temporary-secure-pass-123", "new_password": "permanent-secure-pass-123"
    })
    assert changed.status_code == 200
    new_headers = {"Authorization": "Bearer " + changed.json()["access_token"]}
    assert client.get("/api/v1/posts", headers=new_headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=temp_headers).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=new_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 401


def test_upload_rejects_untrusted_content_and_unknown_extensions(client: TestClient):
    headers = create_owner(client)
    bad_image = client.post("/api/v1/media", headers=headers, files={"file": ("not-really.jpg", b"not an image", "image/jpeg")})
    assert bad_image.status_code == 415
    bad_extension = client.post("/api/v1/media", headers=headers, files={"file": ("payload.exe", b"MZ", "application/octet-stream")})
    assert bad_extension.status_code == 415


def test_content_calendar_returns_workspace_scoped_timezone_aware_period_and_backlog(client: TestClient):
    owner = create_owner(client)
    # These dates straddle midnight in the organization's Asia/Hebron timezone.
    first = client.post("/api/v1/posts", headers=owner, json={
        "title": "محتوى أول يوم", "content": "داخل الفترة", "platform": "Facebook", "status": "scheduled", "scheduled_at": "2029-12-31T22:30:00Z"
    })
    last = client.post("/api/v1/posts", headers=owner, json={
        "title": "محتوى آخر الشهر", "content": "داخل الشهر", "platform": "Instagram", "status": "scheduled", "scheduled_at": "2030-01-31T20:30:00Z"
    })
    after = client.post("/api/v1/posts", headers=owner, json={
        "title": "الشهر التالي", "content": "خارج الفترة", "platform": "Facebook", "status": "scheduled", "scheduled_at": "2030-01-31T22:30:00Z"
    })
    draft = client.post("/api/v1/posts", headers=owner, json={
        "title": "مسودة بلا موعد", "content": "بانتظار التخطيط", "platform": "LinkedIn", "status": "draft"
    })
    assert all(r.status_code == 201 for r in (first, last, after, draft))

    response = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-01-31", headers=owner)
    assert response.status_code == 200, response.text
    data = response.json()
    ids = {item["id"] for item in data["items"]}
    assert first.json()["id"] in ids
    assert last.json()["id"] in ids
    assert after.json()["id"] not in ids
    assert data["timezone"] == "Asia/Hebron"
    assert data["items_count"] == 2
    assert data["backlog_count"] == 1
    assert data["backlog"][0]["id"] == draft.json()["id"]
    assert data["counts"]["total"] == 4

    filtered = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-01-31&platform=Facebook&q=أول", headers=owner)
    assert filtered.status_code == 200, filtered.text
    filtered_data = filtered.json()
    assert filtered_data["items_count"] == 1
    assert len(filtered_data["items"]) == 1
    assert filtered_data["items"][0]["id"] == first.json()["id"]
    assert filtered_data["truncated"] is False


def test_content_calendar_validates_range_and_enforces_post_permissions(client: TestClient):
    owner = create_owner(client)
    reversed_range = client.get("/api/v1/posts/calendar?start_date=2030-02-01&end_date=2030-01-01", headers=owner)
    assert reversed_range.status_code == 422
    oversized = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-04-15", headers=owner)
    assert oversized.status_code == 422
    maximum_date = client.get("/api/v1/posts/calendar?start_date=9999-12-31&end_date=9999-12-31", headers=owner)
    assert maximum_date.status_code == 422
    support = create_member(client, owner, "support", "calendar-support@example.com")
    restricted = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-01-31", headers=support)
    assert restricted.status_code == 403


def test_content_calendar_falls_back_for_invalid_organization_timezone(client: TestClient):
    owner = create_owner(client)
    with SessionLocal() as db:
        organization = db.query(Organization).first()
        assert organization is not None
        organization.timezone = "Invalid/Workspace-Timezone"
        db.commit()
    response = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-01-31", headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == "Asia/Hebron"


def test_dashboard_hides_metrics_from_unauthorized_areas(client: TestClient):
    owner_headers = create_owner(client)
    assert client.post("/api/v1/contacts", headers=owner_headers, json={"name": "عميل سري", "value": 4200}).status_code == 201
    assert client.post("/api/v1/posts", headers=owner_headers, json={"title": "منشور سري", "platform": "Facebook", "status": "scheduled", "scheduled_at": "2030-01-01T10:00:00Z"}).status_code == 201
    overdue = client.post("/api/v1/tasks", headers=owner_headers, json={
        "title": "مهمة متأخرة", "status": "open", "due_at": "2020-01-01T09:00:00Z"
    })
    assert overdue.status_code == 201, overdue.text
    owner_dashboard = client.get("/api/v1/dashboard", headers=owner_headers)
    assert owner_dashboard.status_code == 200
    assert owner_dashboard.json()["counts"]["total_posts"] == 1
    assert owner_dashboard.json()["counts"]["scheduled_posts"] == 1
    assert owner_dashboard.json()["counts"]["overdue_tasks"] == 1
    support_headers = create_member(client, owner_headers, "support", "dashboard-support@example.com")

    support_dashboard = client.get("/api/v1/dashboard", headers=support_headers)
    assert support_dashboard.status_code == 200
    payload = support_dashboard.json()
    assert payload["counts"]["contacts"] == 1
    assert payload["counts"]["open_leads"] == 1
    assert payload["counts"]["overdue_tasks"] == 1
    assert payload["pipeline_value"] == 4200
    assert payload["counts"]["scheduled_posts"] is None
    assert payload["counts"]["total_posts"] is None
    assert payload["counts"]["draft_posts"] is None
    assert "posts" not in payload["visible_areas"]


def test_media_download_enforces_area_permissions(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app import main as app_main

    monkeypatch.setattr(app_main, "MEDIA_DIR", tmp_path / "media")
    owner_headers = create_owner(client)
    upload = client.post("/api/v1/media", headers=owner_headers, files={
        "file": ("brief.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")
    })
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["id"]
    owner_download = client.get(f"/api/v1/media/{asset_id}/download", headers=owner_headers)
    assert owner_download.status_code == 200
    assert owner_download.content.startswith(b"%PDF-")

    support_headers = create_member(client, owner_headers, "support", "media-support@example.com")
    assert client.get("/api/v1/media", headers=support_headers).status_code == 403
    assert client.get(f"/api/v1/media/{asset_id}/download", headers=support_headers).status_code == 403


def test_workspace_isolation_for_posts_tasks_campaigns_and_conversations(client: TestClient):
    owner_headers = create_owner(client)
    contact = client.post("/api/v1/contacts", headers=owner_headers, json={"name": "عميل مساحة أولى"}).json()
    post = client.post("/api/v1/posts", headers=owner_headers, json={"title": "محتوى خاص", "platform": "Facebook"}).json()
    task = client.post("/api/v1/tasks", headers=owner_headers, json={"title": "مهمة خاصة"}).json()
    campaign = client.post("/api/v1/campaigns", headers=owner_headers, json={"name": "حملة خاصة"}).json()
    conversation = client.post("/api/v1/conversations", headers=owner_headers, json={"channel": "WhatsApp", "contact_id": contact["id"]}).json()

    db = SessionLocal()
    try:
        other_org = Organization(name="مساحة تحقق أخرى", timezone="Asia/Hebron")
        db.add(other_org)
        db.flush()
        other_user = User(email="isolated-owner@example.com", full_name="مالك مستقل", password_hash=hash_password("a-distinct-secure-password-789"))
        db.add(other_user)
        db.flush()
        db.add(Membership(organization_id=other_org.id, user_id=other_user.id, role="owner"))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/auth/login", json={"email": "isolated-owner@example.com", "password": "a-distinct-secure-password-789"})
    assert login.status_code == 200, login.text
    other_headers = {"Authorization": "Bearer " + login.json()["access_token"]}

    assert client.put(f"/api/v1/posts/{post['id']}", headers=other_headers, json={"title": "تعديل","platform":"Facebook"}).status_code == 404
    assert client.delete(f"/api/v1/posts/{post['id']}", headers=other_headers).status_code == 404
    assert client.put(f"/api/v1/tasks/{task['id']}", headers=other_headers, json={"title": "تعديل"}).status_code == 404
    assert client.delete(f"/api/v1/tasks/{task['id']}", headers=other_headers).status_code == 404
    assert client.put(f"/api/v1/campaigns/{campaign['id']}", headers=other_headers, json={"name": "تعديل"}).status_code == 404
    assert client.delete(f"/api/v1/campaigns/{campaign['id']}", headers=other_headers).status_code == 404
    assert client.patch(f"/api/v1/conversations/{conversation['id']}", headers=other_headers, json={"status": "closed"}).status_code == 404
    assert client.get(f"/api/v1/conversations/{conversation['id']}/messages", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/contacts", headers=other_headers).json() == []



def test_telegram_destination_verification_is_scoped_and_secret_safe(client: TestClient, monkeypatch):
    monkeypatch.setenv("ENABLE_EXTERNAL_PUBLISHING", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-value")
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة الاختبار", "handle": "@midar_test_channel"
    })
    assert account.status_code == 201, account.text

    async def fake_verify(token, target):
        assert token == "test-bot-token-value"
        assert target == "@midar_test_channel"
        return {
            "bot": {"id": 42, "is_bot": True, "first_name": "Midar", "username": "midar_bot"},
            "chat": {"id": -100123456789, "type": "channel", "title": "قناة الاختبار", "username": "midar_test_channel"},
        }

    monkeypatch.setattr(main_module, "telegram_verify_channel", fake_verify)
    response = client.post("/api/v1/integrations/telegram/verify", headers=headers, json={"social_account_id": account.json()["id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified"] is True
    assert body["account"]["connection_status"] == "connected"
    assert body["account"]["provider_account_id"] == "-100123456789"
    assert "test-bot-token-value" not in response.text
    status = client.get("/api/v1/integrations/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["external_actions_enabled"] is True
    telegram_status = next(p for p in status.json()["providers"] if p["platform"] == "Telegram")
    assert telegram_status["verified_destinations"] == 1 and telegram_status["status"] == "ready"


def test_telegram_publish_has_delivery_record_and_prevents_duplicate(client: TestClient, monkeypatch):
    monkeypatch.setenv("ENABLE_EXTERNAL_PUBLISHING", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-value")
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة الاختبار", "handle": "@midar_test_channel"
    })
    assert account.status_code == 201

    async def fake_verify(token, target):
        return {"bot": {"id": 42, "username": "midar_bot"}, "chat": {"id": -100123456789, "type": "channel", "title": "قناة الاختبار", "username": "midar_test_channel"}}

    send_calls = []
    async def fake_send(token, target_chat_id, text):
        send_calls.append((token, target_chat_id, text))
        return {"message_id": 777, "chat_id": -100123456789, "chat_type": "channel", "date": 1234567890}

    monkeypatch.setattr(main_module, "telegram_verify_channel", fake_verify)
    monkeypatch.setattr(main_module, "telegram_send_text", fake_send)
    verify = client.post("/api/v1/integrations/telegram/verify", headers=headers, json={"social_account_id": account.json()["id"]})
    assert verify.status_code == 200, verify.text
    created = client.post("/api/v1/posts", headers=headers, json={
        "title": "اختبار نشر Telegram", "content": "رسالة اختبارية", "platform": "Telegram",
        "status": "draft", "social_account_id": account.json()["id"]
    })
    assert created.status_code == 201, created.text

    published = client.post(f"/api/v1/posts/{created.json()['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["provider_post_id"] == "777"
    assert published.json()["published_at"] is not None
    assert send_calls == [("test-bot-token-value", "-100123456789", "رسالة اختبارية")]

    duplicate = client.post(f"/api/v1/posts/{created.json()['id']}/publish", headers=headers)
    assert duplicate.status_code == 409
    assert len(send_calls) == 1


def test_telegram_ambiguous_delivery_is_not_retried(client: TestClient, monkeypatch):
    monkeypatch.setenv("ENABLE_EXTERNAL_PUBLISHING", "true")
    from app.integrations.telegram import TelegramDeliveryUnknown
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-value")
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة الاختبار", "handle": "@midar_test_channel"
    })

    async def fake_verify(token, target):
        return {"bot": {"id": 42}, "chat": {"id": -100123456789, "type": "channel", "title": "قناة الاختبار"}}
    send_calls = []
    async def ambiguous_send(token, target_chat_id, text):
        send_calls.append(1)
        raise TelegramDeliveryUnknown("simulated timeout")
    monkeypatch.setattr(main_module, "telegram_verify_channel", fake_verify)
    monkeypatch.setattr(main_module, "telegram_send_text", ambiguous_send)
    assert client.post("/api/v1/integrations/telegram/verify", headers=headers, json={"social_account_id": account.json()["id"]}).status_code == 200
    created = client.post("/api/v1/posts", headers=headers, json={
        "title": "منشور غامض", "content": "رسالة قد تكون وصلت", "platform": "Telegram", "social_account_id": account.json()["id"]
    })
    response = client.post(f"/api/v1/posts/{created.json()['id']}/publish", headers=headers)
    assert response.status_code == 502
    stored = client.get("/api/v1/posts", headers=headers).json()[0]
    assert stored["status"] == "delivery_unknown"
    assert client.post(f"/api/v1/posts/{created.json()['id']}/publish", headers=headers).status_code == 409
    assert len(send_calls) == 1
    resolved = client.post(f"/api/v1/posts/{created.json()['id']}/resolve-delivery", headers=headers, json={
        "resolution": "failed", "note": "تحققت من القناة ولم تظهر الرسالة"
    })
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "failed"


def test_delivery_reconciliation_requires_admin_and_unknown_state(client: TestClient, monkeypatch):
    monkeypatch.setenv("ENABLE_EXTERNAL_PUBLISHING", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-value")
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة الاختبار", "handle": "@midar_test_channel"
    })
    async def fake_verify(token, target):
        return {"bot": {"id": 42}, "chat": {"id": -100123456789, "type": "channel", "title": "قناة الاختبار"}}
    monkeypatch.setattr(main_module, "telegram_verify_channel", fake_verify)
    assert client.post("/api/v1/integrations/telegram/verify", headers=headers, json={"social_account_id": account.json()["id"]}).status_code == 200
    post = client.post("/api/v1/posts", headers=headers, json={"title": "نشر", "content": "نص", "platform": "Telegram", "social_account_id": account.json()["id"]})
    # Deliberately put the post into the ambiguous state through an API send failure.
    from app.integrations.telegram import TelegramDeliveryUnknown
    async def fail_ambiguous(token, target, body):
        raise TelegramDeliveryUnknown("network timeout")
    monkeypatch.setattr(main_module, "telegram_send_text", fail_ambiguous)
    assert client.post(f"/api/v1/posts/{post.json()['id']}/publish", headers=headers).status_code == 502
    invalid = client.post(f"/api/v1/posts/{post.json()['id']}/resolve-delivery", headers=headers, json={"resolution": "published", "note": "checked"})
    assert invalid.status_code == 200
    assert invalid.json()["status"] == "published"
    second = client.post(f"/api/v1/posts/{post.json()['id']}/resolve-delivery", headers=headers, json={"resolution": "failed", "note": "checked again"})
    assert second.status_code == 409


def test_definitive_telegram_rejection_can_be_corrected_and_retried(client: TestClient, monkeypatch):
    monkeypatch.setenv("ENABLE_EXTERNAL_PUBLISHING", "true")
    from app.integrations.telegram import TelegramAPIError
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token-value")
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة الاختبار", "handle": "@midar_test_channel"
    })
    async def fake_verify(token, target):
        return {"bot": {"id": 42}, "chat": {"id": -100123456789, "type": "channel", "title": "قناة الاختبار"}}
    monkeypatch.setattr(main_module, "telegram_verify_channel", fake_verify)
    assert client.post("/api/v1/integrations/telegram/verify", headers=headers, json={"social_account_id": account.json()["id"]}).status_code == 200
    post = client.post("/api/v1/posts", headers=headers, json={"title": "قابل لإعادة المحاولة", "content": "النص", "platform": "Telegram", "social_account_id": account.json()["id"]})
    async def definitive_error(token, target, body):
        raise TelegramAPIError("chat not found", error_code=400)
    monkeypatch.setattr(main_module, "telegram_send_text", definitive_error)
    first = client.post(f"/api/v1/posts/{post.json()['id']}/publish", headers=headers)
    assert first.status_code == 502
    failed = client.get("/api/v1/posts", headers=headers).json()[0]
    assert failed["status"] == "failed" and "chat not found" in failed["publish_error"]
    async def success(token, target, body):
        return {"message_id": 991, "chat_id": -100123456789, "chat_type": "channel", "date": 1234567890}
    monkeypatch.setattr(main_module, "telegram_send_text", success)
    retry = client.post(f"/api/v1/posts/{post.json()['id']}/publish", headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "published" and retry.json()["provider_post_id"] == "991"


def test_post_target_must_belong_to_workspace_and_match_platform(client: TestClient):
    headers = create_owner(client)
    account = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Telegram", "account_name": "قناة", "handle": "@mychannel"
    })
    assert account.status_code == 201
    mismatch = client.post("/api/v1/posts", headers=headers, json={
        "title": "منشور غير متوافق", "platform": "Facebook", "social_account_id": account.json()["id"]
    })
    assert mismatch.status_code == 422


def test_user_preferences_persist_and_are_scoped_to_authenticated_user(client: TestClient):
    owner = create_owner(client)
    defaults = client.get("/api/v1/preferences", headers=owner)
    assert defaults.status_code == 200, defaults.text
    assert defaults.json() == {"theme_mode": "dark", "accent_color": "blue", "density": "comfortable"}

    saved = client.patch("/api/v1/preferences", headers=owner, json={
        "theme_mode": "light", "accent_color": "cyan", "density": "compact"
    })
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"theme_mode": "light", "accent_color": "cyan", "density": "compact"}
    reread = client.get("/api/v1/preferences", headers=owner)
    assert reread.json() == saved.json()

    invalid = client.patch("/api/v1/preferences", headers=owner, json={"accent_color": "not-a-color"})
    assert invalid.status_code == 422
    assert "not-a-color" not in client.get("/api/v1/preferences", headers=owner).text


def test_profile_update_is_validated_and_does_not_change_email(client: TestClient):
    owner = create_owner(client)
    before = client.get("/api/v1/auth/me", headers=owner).json()
    updated = client.patch("/api/v1/auth/profile", headers=owner, json={"full_name": "المالك الجديد"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "المالك الجديد"
    assert updated.json()["email"] == before["email"]
    assert client.patch("/api/v1/auth/profile", headers=owner, json={"full_name": " "}).status_code == 422


def test_google_oidc_is_disabled_without_credentials_and_scopes_are_identity_only(client: TestClient, monkeypatch):
    for key in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI"):
        monkeypatch.delenv(key, raising=False)
    config = client.get("/api/v1/auth/google/config")
    assert config.status_code == 200
    assert config.json()["enabled"] is False
    assert config.json()["scopes"] == ["openid", "email", "profile"]
    assert client.post("/api/v1/auth/google/login-url", json={}).status_code == 503
    owner = create_owner(client)
    status = client.get("/api/v1/auth/google/status", headers=owner)
    assert status.status_code == 200
    assert status.json()["enabled"] is False and status.json()["linked"] is False


def test_google_oidc_refuses_insecure_non_local_redirect(client: TestClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "http://example.com/callback")
    assert client.get("/api/v1/auth/google/config").json()["enabled"] is False


def test_short_video_drafts_are_persisted_validated_and_workspace_scoped(client: TestClient):
    owner = create_owner(client)
    created = client.post("/api/v1/video-drafts", headers=owner, json={
        "title": "مقطع إطلاق المنتج", "caption": "وصف تجريبي للمقطع",
        "media_asset_id": None, "target_platforms": ["Instagram", "TikTok", "YouTube"],
        "aspect_ratio": "9:16", "duration_seconds": 24, "status": "draft"
    })
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["target_platforms"] == ["Instagram", "TikTok", "YouTube"]
    assert client.get("/api/v1/video-drafts", headers=owner).json()[0]["id"] == draft["id"]

    updated = client.put(f"/api/v1/video-drafts/{draft['id']}", headers=owner, json={
        "title": "مقطع إطلاق محدّث", "caption": "نسخة جديدة",
        "media_asset_id": None, "target_platforms": ["YouTube"],
        "aspect_ratio": "9:16", "duration_seconds": 31, "status": "ready"
    })
    # A draft cannot be marked ready without a video asset.
    assert updated.status_code == 422

    updated = client.put(f"/api/v1/video-drafts/{draft['id']}", headers=owner, json={
        "title": "مقطع إطلاق محدّث", "caption": "نسخة جديدة",
        "media_asset_id": None, "target_platforms": ["YouTube"],
        "aspect_ratio": "9:16", "duration_seconds": 31, "status": "draft"
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "مقطع إطلاق محدّث"
    assert client.delete(f"/api/v1/video-drafts/{draft['id']}", headers=owner).status_code == 204
    assert client.get("/api/v1/video-drafts", headers=owner).json() == []



def test_experience_layer_and_command_center_are_served(client: TestClient):
    root = client.get("/")
    assert root.status_code == 200
    assert 'href="/midar-ui.css?v=0.22.0"' in root.text
    assert root.text.count('rel="stylesheet"') == 1
    assert 'src="/command-center.js?v=0.22.0"' in root.text
    assert root.text.index('src="/app.js?v=0.22.0"') < root.text.index('src="/command-center.js?v=0.22.0"')
    css = client.get("/midar-ui.css")
    js = client.get("/command-center.js")
    assert css.status_code == 200 and "xp-command-dialog" in css.text
    assert js.status_code == 200 and "__midarCommandCenterReady" in js.text
    assert "nav.click()" in js.text
    assert "All sidebar sections now live inside #nav" in js.text
    app_js = client.get("/app.js")
    assert app_js.status_code == 200
    for fragment in ("حالة المحتوى", "ما يستحق انتباهك", "على جدولك", "dashboard-v2", "connected", "posts/calendar", "cm-month-grid", "localInputToIso", "safeTimezone", "params.q=postWorkspace.q.trim().slice(0,100)", "params.status=postWorkspace.status", "params.platform=postWorkspace.platform"):
        assert fragment in app_js.text
    assert all(fragment in css.text for fragment in (".workspace-hero", ".upcoming-item", "prefers-reduced-motion", ":focus-visible", ".review-note", ".cm-month-grid"))
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "m-shell-v0220" in sw.text
    assert "'/midar-ui.css?v=0.22.0'" in sw.text
    assert "'/command-center.js?v=0.22.0'" in sw.text
    for retired in ("'/experience.css", "'/dashboard-command.css", "'/premium-shell.css", "'/content-calendar.css"):
        assert retired not in sw.text



def test_sidebar_redesign_has_single_navigation_and_safe_collapse(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="sidebarCollapseBtn"' in page.text
    assert 'class="nav sidebar-navigation" id="nav" aria-label="أقسام M"' in page.text
    assert 'aria-controls="sidebar" aria-expanded="false"' in page.text
    assert page.text.count('id="nav"') == 1
    for section in ("الرئيسية", "المحتوى والتسويق", "التواصل والعلاقات", "الحسابات والتكاملات", "الإدارة"):
        assert f'aria-label="{section}"' in page.text
    for page_id in ("dashboard", "posts", "studio", "campaigns", "inbox", "contacts", "tasks", "accounts", "media", "team", "settings", "audit"):
        assert f'data-page="{page_id}"' in page.text
    assert 'data-page="settings"' in page.text  # one Settings entry: no fake workspace-switcher shortcut
    assert page.text.count('data-page="settings"') == 1
    css = client.get("/midar-ui.css")
    assert css.status_code == 200
    for token in (".sidebar-navigation", ".nav button", "body.sidebar-collapsed .main", ".nav-icon svg", "overscroll-behavior-y: contain", "prefers-reduced-motion"):
        assert token in css.text
    js = client.get("/app.js")
    for token in ("midar.sidebar.collapsed", "applySidebarCollapsedPreference", "aria-current", "nav-section", "setMobileSidebarOpen", "mobileOverlay", "aria-expanded"):
        assert token in js.text
    command_js = client.get("/command-center.js")
    assert command_js.status_code == 200
    assert "All sidebar sections now live inside #nav" in command_js.text
    assert "document.addEventListener('click', event =>" not in command_js.text

def test_settings_and_creator_ui_assets_are_served(client: TestClient):
    owner = create_owner(client)
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="accountMenuBtn"' in page.text
    assert 'id="settings-enhanced' not in page.text  # CSS is external, no fake HTML hook.
    css = client.get("/midar-ui.css")
    assert css.status_code == 200
    assert ".accent-choice" in css.text and ".settings-layout-v2" in css.text and 'data-theme="light"' in css.text
    assert ".studio-preview-player" in css.text
    js = client.get("/settings-enhanced.js")
    for fragment in ("renderEnhancedSettings", "data-google-link", "settingsProfileForm", "appearanceForm", "settingsLogoutBtn", "MIDAR_SYSTEM_THEME_LISTENER"):
        assert fragment in js.text
    app_js = client.get("/app.js")
    assert "video-preview" in app_js.text or "studio-preview-player" in app_js.text
    # Keep each settings/authentication helper in one file to prevent classic-script shadowing.
    assert "function renderEnhancedSettings" not in app_js.text
    assert page.text.index('src="/settings-enhanced.js') < page.text.index('src="/app.js')
    assert client.get("/favicon.ico").status_code == 200


def test_stylesheet_bundle_is_single_ordered_runtime_asset(client: TestClient):
    root = client.get("/")
    bundle = client.get("/midar-ui.css")
    assert bundle.status_code == 200
    assert root.text.count('rel="stylesheet"') == 1
    assert all(s in bundle.text for s in (
        "--midar-midnight: #101827", ".provider-grid", ".accent-choice",
        ".xp-command-dialog", ".dashboard-v2", ".cm-page", ".review-note",
    ))
    assert "overflow-y: auto" in bundle.text and "overscroll-behavior-y: contain" in bundle.text
    assert "11-sidebar-redesign.css" in bundle.text
    sw = client.get("/sw.js")
    assert "'/midar-ui.css?v=0.22.0'" in sw.text
    assert "m-shell-v0220" in sw.text


def test_service_worker_precaches_settings_controller_and_favicon(client: TestClient):
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "m-shell-v0220" in sw.text
    assert "'/settings-enhanced.js" in sw.text
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200
    assert icon.headers.get("content-type", "").startswith("image/")




def test_cross_platform_pwa_manifest_and_safe_area_assets(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200
    assert 'href="/midar-ui.css?v=0.22.0"' in page.text
    for token in (
        'name="apple-mobile-web-app-capable" content="yes"',
        'name="apple-mobile-web-app-status-bar-style" content="black-translucent"',
        'rel="apple-touch-icon" href="/apple-touch-icon.png"',
        'id="installAppBtn"',
    ):
        assert token in page.text
    manifest_response = client.get("/manifest.webmanifest")
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    assert manifest["id"] == "/" and manifest["display"] == "standalone"
    assert manifest["lang"] == "ar" and manifest["dir"] == "rtl"
    png_icons = {icon["src"]: icon for icon in manifest["icons"] if icon["type"] == "image/png"}
    assert png_icons["/icon-192.png"]["sizes"] == "192x192"
    assert png_icons["/icon-512.png"]["sizes"] == "512x512"
    for asset in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
        response = client.get(asset)
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("image/png")


def test_cross_platform_responsive_css_and_mobile_drawer_accessibility(client: TestClient):
    css = client.get("/midar-ui.css")
    js = client.get("/app.js")
    sw = client.get("/sw.js")
    assert css.status_code == js.status_code == sw.status_code == 200
    for token in ("env(safe-area-inset-top", "--midar-target-size: 44px", "font-size: 16px !important", "@media (max-width: 390px)", "prefers-reduced-motion"):
        assert token in css.text
    for token in ("aria-modal", "sidebar.inert=true", "event.key==='Escape'", "installButton.addEventListener('click'", "navigator.standalone", "shouldOpen?'إغلاق القائمة':'فتح القائمة'", "isAppleTouchDevice()", "document.body.style.position='fixed'", "window.scrollTo(0,mobileNavScrollY)"):
        assert token in js.text
    assert "m-shell-v0220" in sw.text
    for asset in ("/icon-192.png", "/icon-512.png", "/apple-touch-icon.png"):
        assert f"'{asset}'" in sw.text

def test_post_review_workflow_enforces_roles_states_and_audit(client: TestClient):
    owner = create_owner(client)
    editor = create_member(client, owner, "editor", "review-editor@example.com")

    created = client.post("/api/v1/posts", headers=editor, json={
        "title": "حملة تحتاج مراجعة", "content": "النص الأول", "platform": "Instagram", "status": "draft"
    })
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]

    # Clients cannot forge editorial states through the ordinary CRUD schema.
    forged = client.post("/api/v1/posts", headers=editor, json={
        "title": "تجاوز المراجعة", "content": "نص", "platform": "Facebook", "status": "approved"
    })
    assert forged.status_code == 422

    submitted = client.post(f"/api/v1/posts/{post_id}/submit-review", headers=editor)
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "in_review"

    # Content in review cannot be changed or deleted while the decision is pending.
    update_payload = {
        "title": "محاولة تعديل أثناء المراجعة", "content": "تغيير", "platform": "Instagram", "status": "draft"
    }
    assert client.put(f"/api/v1/posts/{post_id}", headers=editor, json=update_payload).status_code == 409
    assert client.delete(f"/api/v1/posts/{post_id}", headers=editor).status_code == 409

    # An editor can submit but cannot approve or request changes.
    assert client.post(f"/api/v1/posts/{post_id}/approve", headers=editor).status_code == 403
    assert client.post(f"/api/v1/posts/{post_id}/request-changes", headers=editor, json={
        "note": "يرجى توضيح الهدف"
    }).status_code == 403

    approved = client.post(f"/api/v1/posts/{post_id}/approve", headers=owner)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert client.put(f"/api/v1/posts/{post_id}", headers=owner, json=update_payload).status_code == 409
    assert client.post(f"/api/v1/posts/{post_id}/approve", headers=owner).status_code == 409

    # Approved and review statuses are backed by real dashboard counts.
    dashboard = client.get("/api/v1/dashboard", headers=owner)
    assert dashboard.status_code == 200
    assert dashboard.json()["counts"]["approved_posts"] == 1
    assert dashboard.json()["counts"]["in_review_posts"] == 0

    logs = client.get("/api/v1/audit-logs?limit=50", headers=owner)
    assert logs.status_code == 200
    actions = [row for row in logs.json() if row.get("entity_id") == post_id]
    assert any(row["action"] == "post.review_requested" for row in actions)
    assert any(row["action"] == "post.approved" for row in actions)


def test_post_review_changes_request_requires_note_and_returns_post_to_author(client: TestClient):
    owner = create_owner(client)
    editor = create_member(client, owner, "editor", "changes-editor@example.com")
    created = client.post("/api/v1/posts", headers=editor, json={
        "title": "مسودة للتعديل", "content": "النص يحتاج تدقيقًا", "platform": "Facebook", "status": "draft"
    })
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    submitted = client.post(f"/api/v1/posts/{post_id}/submit-review", headers=editor)
    assert submitted.status_code == 200 and submitted.json()["status"] == "in_review"

    too_short = client.post(f"/api/v1/posts/{post_id}/request-changes", headers=owner, json={"note": "لا"})
    assert too_short.status_code == 422
    returned = client.post(f"/api/v1/posts/{post_id}/request-changes", headers=owner, json={
        "note": "أضف مصدر الأرقام وراجع صياغة العنوان"
    })
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "changes_requested"

    # The author receives the latest reviewer note with the post itself; they do not need
    # access to the owner/admin-only audit page to understand the requested changes.
    author_posts = client.get("/api/v1/posts?status=changes_requested", headers=editor)
    assert author_posts.status_code == 200, author_posts.text
    assert len(author_posts.json()) == 1
    assert author_posts.json()[0]["review_note"] == "أضف مصدر الأرقام وراجع صياغة العنوان"
    calendar = client.get("/api/v1/posts/calendar?start_date=2030-01-01&end_date=2030-01-31", headers=editor)
    assert calendar.status_code == 200, calendar.text
    assert any(row["id"] == post_id and row["review_note"] == "أضف مصدر الأرقام وراجع صياغة العنوان" for row in calendar.json()["backlog"])

    logs = client.get("/api/v1/audit-logs?limit=50", headers=owner)
    decision = next(row for row in logs.json() if row.get("entity_id") == post_id and row["action"] == "post.changes_requested")
    assert decision["details"]["note"] == "أضف مصدر الأرقام وراجع صياغة العنوان"

    # Author can edit after the reviewer returns it; the editor schema transitions it back to draft.
    revised = client.put(f"/api/v1/posts/{post_id}", headers=editor, json={
        "title": "مسودة منقحة", "content": "تمت مراجعة النص", "platform": "Facebook", "status": "draft"
    })
    assert revised.status_code == 200, revised.text
    assert revised.json()["status"] == "draft"
    assert revised.json()["title"] == "مسودة منقحة"


def test_post_review_routes_are_workspace_scoped_and_state_checked(client: TestClient):
    owner = create_owner(client)
    created = client.post("/api/v1/posts", headers=owner, json={
        "title": "مسودة", "content": "نص", "platform": "X", "status": "draft"
    })
    assert created.status_code == 201, created.text
    post_id = created.json()["id"]
    assert client.post(f"/api/v1/posts/{post_id}/approve", headers=owner).status_code == 409
    assert client.post(f"/api/v1/posts/{post_id}/request-changes", headers=owner, json={
        "note": "لا يمكن طلب تعديل قبل إرسال المحتوى للمراجعة"
    }).status_code == 409
    assert client.post("/api/v1/posts/not-a-real-id/submit-review", headers=owner).status_code == 404

    # An analyst can read posts but has no write permission for the content workflow.
    analyst = create_member(client, owner, "analyst", "review-analyst@example.com")
    assert client.post(f"/api/v1/posts/{post_id}/submit-review", headers=analyst).status_code == 403



def test_provider_credentials_are_encrypted_tenant_scoped_and_audited(client: TestClient, monkeypatch):
    from app.integrations.credential_store import (
        CredentialScopeError, load_provider_credential, store_provider_credential,
    )
    from app.security_tokens import generate_provider_encryption_key

    monkeypatch.setenv("PROVIDER_TOKEN_ENCRYPTION_KEY", generate_provider_encryption_key())
    owner_headers = create_owner(client, "credential-owner@example.com")
    account_response = client.post("/api/v1/social-accounts", headers=owner_headers, json={
        "platform": "Facebook", "account_name": "حساب اختبار بيانات الاعتماد", "handle": "@vault-test"
    })
    assert account_response.status_code == 201, account_response.text
    account_id = account_response.json()["id"]

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "credential-owner@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == user.id).one()
        account = db.query(SocialAccount).filter(SocialAccount.id == account_id).one()
        # Simulate the verified state that a future provider-specific OAuth callback must establish.
        account.connection_status = "connected"
        account.provider_account_id = "remote-account-123"
        db.commit()
        saved = store_provider_credential(
            db,
            organization_id=membership.organization_id,
            social_account_id=account.id,
            actor_user_id=user.id,
            provider="Facebook",
            access_token="access-token-do-not-store-in-plaintext",
            refresh_token="refresh-token-do-not-store-in-plaintext",
            scopes=["pages_read_engagement", "pages_manage_posts"],
        )
        assert "access-token-do-not-store-in-plaintext" not in saved.access_token_ciphertext
        assert "refresh-token-do-not-store-in-plaintext" not in (saved.refresh_token_ciphertext or "")
        db.commit()
        credential_id = saved.id
        org_id = membership.organization_id
        user_id = user.id
        row = db.query(IntegrationCredential).filter(IntegrationCredential.id == credential_id).one()
        assert row.key_format == "fernet:v1"
        assert row.status == "active"
        log = db.query(AuditLog).filter(AuditLog.action == "integration.credential_stored").one()
        assert "access-token-do-not-store-in-plaintext" not in log.details
        assert "refresh-token-do-not-store-in-plaintext" not in log.details
        loaded = load_provider_credential(db, organization_id=org_id, social_account_id=account_id)
        assert loaded is not None
        assert loaded.access_token == "access-token-do-not-store-in-plaintext"
        assert loaded.refresh_token == "refresh-token-do-not-store-in-plaintext"
        assert loaded.scopes == ("pages_manage_posts", "pages_read_engagement")

        from app.integrations.credential_store import CredentialStoreError
        with pytest.raises(CredentialStoreError):
            store_provider_credential(
                db, organization_id=membership.organization_id, social_account_id=account.id,
                actor_user_id=user.id, provider="Facebook", access_token="scope-limit-test",
                scopes=[f"scope-{i}" for i in range(257)],
            )

        # A different tenant gets no record even when it knows the social account ID.
        assert load_provider_credential(db, organization_id="other-organization-id", social_account_id=account_id) is None

    editor_headers = create_member(client, owner_headers, "editor", "credential-editor@example.com")
    with SessionLocal() as db:
        editor = db.query(User).filter(User.email == "credential-editor@example.com").one()
        with pytest.raises(CredentialScopeError):
            store_provider_credential(
                db,
                organization_id=org_id,
                social_account_id=account_id,
                actor_user_id=editor.id,
                provider="Facebook",
                access_token="editor-must-not-write-credentials",
            )
        db.rollback()


def test_credential_store_fails_closed_without_encryption_key(client: TestClient, monkeypatch):
    from app.integrations.credential_store import store_provider_credential
    from app.security_tokens import TokenVaultConfigurationError

    monkeypatch.delenv("PROVIDER_TOKEN_ENCRYPTION_KEY", raising=False)
    headers = create_owner(client, "credential-no-key@example.com")
    account_response = client.post("/api/v1/social-accounts", headers=headers, json={
        "platform": "Facebook", "account_name": "حساب بلا مفتاح", "handle": "@no-key-test"
    })
    assert account_response.status_code == 201
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "credential-no-key@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == user.id).one()
        account = db.query(SocialAccount).filter(SocialAccount.id == account_response.json()["id"]).one()
        account.connection_status = "connected"
        account.provider_account_id = "remote-account-no-key"
        db.commit()
        with pytest.raises(TokenVaultConfigurationError):
            store_provider_credential(
                db, organization_id=membership.organization_id, social_account_id=account.id,
                actor_user_id=user.id, provider="Facebook", access_token="must-not-fall-back-to-plain-text",
            )
        assert db.query(IntegrationCredential).count() == 0
        db.rollback()



def test_provider_oauth_transaction_is_one_time_scoped_and_pkce_s256(client: TestClient):
    from app.integrations.authorization import (
        AuthorizationTransactionError, create_authorization_transaction,
        consume_authorization_transaction,
    )
    from app.models import OAuthTransaction
    import base64
    import hashlib

    owner_headers = create_owner(client, "oauth-state-owner@example.com")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "oauth-state-owner@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == user.id).one()
        challenge = create_authorization_transaction(
            db, provider="meta", purpose="link", user_id=user.id,
            organization_id=membership.organization_id, auth_version=user.auth_version,
            ttl_seconds=3600,  # implementation caps this at 15 minutes
        )
        db.commit()
        assert len(challenge.code_verifier) >= 43
        assert challenge.code_challenge_method == "S256"
        expected_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(challenge.code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert challenge.code_challenge == expected_challenge
        stored = db.query(OAuthTransaction).one()
        assert stored.state_hash != challenge.state
        assert challenge.state not in stored.state_hash
        assert stored.provider == "meta" and stored.purpose == "link"
        with pytest.raises(AuthorizationTransactionError):
            consume_authorization_transaction(
                db, provider="meta", purpose="link", state=challenge.state,
                browser_binding="wrong-browser-binding",
            )
        db.rollback()
        # State remains valid after a mismatched browser proof and can only be consumed with the right cookie.
        consumed = consume_authorization_transaction(
            db, provider="meta", purpose="link", state=challenge.state,
            browser_binding=challenge.browser_binding,
        )
        db.commit()
        assert consumed.user_id == user.id
        assert consumed.organization_id == membership.organization_id
        assert consumed.code_verifier == challenge.code_verifier
        assert db.query(OAuthTransaction).count() == 0
        with pytest.raises(AuthorizationTransactionError):
            consume_authorization_transaction(
                db, provider="meta", purpose="link", state=challenge.state,
                browser_binding=challenge.browser_binding,
            )

    editor_headers = create_member(client, owner_headers, "editor", "oauth-state-editor@example.com")
    with SessionLocal() as db:
        editor = db.query(User).filter(User.email == "oauth-state-editor@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == editor.id).one()
        with pytest.raises(AuthorizationTransactionError):
            create_authorization_transaction(
                db, provider="meta", purpose="link", user_id=editor.id,
                organization_id=membership.organization_id, auth_version=editor.auth_version,
            )
        db.rollback()


def test_google_oauth_callback_is_bound_to_starting_browser_and_single_use(client: TestClient, monkeypatch, caplog):
    """The OAuth callback must match the HttpOnly cookie set by the start request."""
    from urllib.parse import parse_qs, urlparse
    from app.models import OAuthTransaction, ProviderOAuthBinding

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app.example.test/api/v1/auth/google/callback")
    exchanged: list[str] = []

    def fake_exchange(config, code, verifier):
        exchanged.append(code)
        assert len(verifier) >= 43
        return "test-id-token"

    monkeypatch.setattr(main_module, "google_exchange_code", fake_exchange)
    monkeypatch.setattr(main_module, "verify_google_id_token", lambda token, client_id, nonce: {
        "sub": "unlinked-google-subject", "email": "person@example.com", "email_verified": True,
    })

    started = client.post("/api/v1/auth/google/login-url", json={})
    assert started.status_code == 200, started.text
    assert started.headers["cache-control"] == "no-store"
    set_cookie = started.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "max-age=600" in set_cookie.lower()

    auth_query = parse_qs(urlparse(started.json()["authorization_url"]).query)
    state = auth_query["state"][0]
    cookie_name = main_module._google_binding_cookie_name(state)
    binding_cookie = client.cookies.get(cookie_name)
    assert binding_cookie

    # A different browser, even with the state value, cannot redeem the code.
    import logging
    with TestClient(app, follow_redirects=False) as other_browser:
        with caplog.at_level(logging.WARNING, logger="midar.security"):
            rejected = other_browser.get("/api/v1/auth/google/callback", params={"state": state, "code": "attacker-code"})
    assert rejected.status_code == 303
    assert "browser_binding_mismatch" in caplog.text
    assert state not in caplog.text and "attacker-code" not in caplog.text and binding_cookie not in caplog.text
    assert "google_result=invalid_state" in rejected.headers["location"]
    assert exchanged == []
    with SessionLocal() as db:
        assert db.query(OAuthTransaction).count() == 1
        assert db.query(ProviderOAuthBinding).count() == 1

    # Original browser can complete the flow; it consumes transaction exactly once.
    completed = client.get("/api/v1/auth/google/callback", params={"state": state, "code": "legitimate-code"}, follow_redirects=False)
    assert completed.status_code == 303
    assert "google_result=not_linked" in completed.headers["location"]
    assert exchanged == ["legitimate-code"]
    assert "max-age=0" in completed.headers.get("set-cookie", "").lower()
    with SessionLocal() as db:
        assert db.query(OAuthTransaction).count() == 0
        assert db.query(ProviderOAuthBinding).count() == 0

    replay = client.get("/api/v1/auth/google/callback", params={"state": state, "code": "replay-code"}, follow_redirects=False)
    assert "google_result=invalid_state" in replay.headers["location"]
    assert exchanged == ["legitimate-code"]


def test_google_identity_link_uses_shared_oauth_service_without_requiring_admin_role(client: TestClient, monkeypatch):
    """Google sign-in identity belongs to the user; social publishing connections remain admin-only."""
    from urllib.parse import parse_qs, urlparse
    from app.models import ExternalIdentity
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-google-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app.example.test/api/v1/auth/google/callback")
    monkeypatch.setattr(main_module, "google_exchange_code", lambda config, code, verifier: "fake-google-id-token")
    monkeypatch.setattr(main_module, "verify_google_id_token", lambda token, client_id, nonce: {
        "sub": "google-subject-for-editor", "email": "google-editor@example.com", "email_verified": True,
    })
    owner_headers = create_owner(client, "google-link-owner@example.com")
    editor_headers = create_member(client, owner_headers, "editor", "google-link-editor@example.com")
    started = client.post("/api/v1/auth/google/link-url", headers=editor_headers, json={})
    assert started.status_code == 200, started.text
    auth_query = parse_qs(urlparse(started.json()["authorization_url"]).query)
    state = auth_query["state"][0]
    linked = client.get("/api/v1/auth/google/callback", params={"state": state, "code": "authorized-code"}, follow_redirects=False)
    assert linked.status_code == 303
    assert "google_result=link_success" in linked.headers["location"]
    with SessionLocal() as db:
        identity = db.query(ExternalIdentity).filter(ExternalIdentity.subject == "google-subject-for-editor").one()
        user = db.query(User).filter(User.email == "google-link-editor@example.com").one()
        assert identity.user_id == user.id


def test_expired_oauth_state_cleans_browser_binding_and_reports_reason(client):
    from datetime import timedelta
    from app.integrations.authorization import (
        AuthorizationTransactionError, create_authorization_transaction,
        consume_authorization_transaction,
    )
    from app.models import OAuthTransaction, ProviderOAuthBinding, User, Membership
    from app.models import utcnow
    from app.db import SessionLocal

    # Use the shared API test helper style via a small direct setup through the app fixture.
    response = client.post("/api/v1/auth/setup", json={
        "full_name": "OAuth Owner", "email": "oauth-expiry@example.com",
        "password": "secure-password-for-expiry-test", "organization_name": "OAuth Expiry",
    })
    assert response.status_code == 201
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "oauth-expiry@example.com").one()
        membership = db.query(Membership).filter(Membership.user_id == user.id).one()
        challenge = create_authorization_transaction(
            db, provider="meta", purpose="link", user_id=user.id,
            organization_id=membership.organization_id, auth_version=user.auth_version,
        )
        db.commit()
        row = db.query(OAuthTransaction).one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(AuthorizationTransactionError) as exc_info:
            consume_authorization_transaction(
                db, provider="meta", purpose="link", state=challenge.state,
                browser_binding=challenge.browser_binding,
            )
        assert exc_info.value.reason == "expired"
        assert exc_info.value.cleanup_performed is True
        db.commit()
        assert db.query(OAuthTransaction).count() == 0
        assert db.query(ProviderOAuthBinding).count() == 0



def test_contacts_csv_neutralizes_spreadsheet_formula_cells(client: TestClient):
    headers = create_owner(client, "csv-formula-owner@example.com")
    response = client.post("/api/v1/contacts", headers=headers, json={
        "name": '=HYPERLINK("https://evil.example","open")',
        "company": "+SUM(1,1)",
        "email": "csv-test@example.com",
        "phone": "@SUM(1,1)",
        "source": "-IMPORT",
        "stage": "new",
        "value": 1500,
        "notes": "\t=cmd|' /C calc'!A0",
    })
    assert response.status_code == 201, response.text
    exported = client.get("/api/v1/exports/contacts.csv", headers=headers)
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "private, no-store"
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    row = rows[1]
    assert row[0].startswith("'=")
    assert row[1].startswith("'+")
    assert row[2] == "csv-test@example.com"
    assert row[3].startswith("'@")
    assert row[4].startswith("'-")
    assert row[8].startswith("'\t=")
    assert row[6] == "1500.0" or row[6] == "1500"


def test_login_throttle_retry_after_tracks_rolling_window_expiry(client: TestClient, monkeypatch):
    from app.db import SessionLocal

    monkeypatch.setattr(main_module, "LOGIN_ACCOUNT_LIMIT", 3)
    monkeypatch.setattr(main_module, "LOGIN_IP_LIMIT", 100)
    monkeypatch.setattr(main_module, "LOGIN_WINDOW_MINUTES", 15)
    create_owner(client, "throttle-window@example.com")
    for _ in range(3):
        failed = client.post("/api/v1/auth/login", json={
            "email": "throttle-window@example.com",
            "password": "incorrect-password-value",
        })
        assert failed.status_code == 401

    account_key, ip_key = main_module.login_keys("throttle-window@example.com", "testclient")
    almost_expired = utcnow() - timedelta(minutes=14, seconds=50)
    with SessionLocal() as db:
        db.query(AuthFailure).filter(AuthFailure.key_hash.in_([account_key, ip_key])).update(
            {AuthFailure.created_at: almost_expired}, synchronize_session=False
        )
        db.commit()

    limited = client.post("/api/v1/auth/login", json={
        "email": "throttle-window@example.com",
        "password": "incorrect-password-value",
    })
    assert limited.status_code == 429
    retry_after = int(limited.headers["Retry-After"])
    assert 1 <= retry_after <= 15, f"expected precise remaining window, got {retry_after}"
    assert "حاول بعد" in limited.json()["detail"]


def test_unconfigured_development_secret_is_random_and_production_fails_closed():
    code = (
        "import sys; sys.path.insert(0, 'backend'); "
        "import app.security as s; "
        "assert len(s.SECRET_KEY) >= 32; "
        "assert s.SECRET_KEY != 'dev-only-change-this-secret-before-any-real-use'; "
        "print('secure-development-secret')"
    )
    env = os.environ.copy()
    env.pop("SECRET_KEY", None)
    env["APP_ENV"] = "development"
    development = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert development.returncode == 0, development.stderr
    assert "secure-development-secret" in development.stdout

    env["APP_ENV"] = "production"
    env["SECRET_KEY"] = "short"
    production = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'backend'); import app.security"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert production.returncode != 0
    assert "random SECRET_KEY" in production.stderr
