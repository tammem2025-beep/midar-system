from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO_EMAIL = "demo-owner@example.com"
DEMO_PASSWORD = "Demo-M-Only-2026!"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an isolated sample M database. It never uses the normal local .env."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "demo-data",
        help="New, empty directory for the demo database, .env and media.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    db_path = data_dir / "m-demo.db"
    env_path = data_dir / ".env"
    media_dir = data_dir / "media"

    if db_path.exists() or env_path.exists():
        print(
            f"Refusing to overwrite demo data in {data_dir}. Choose a new --data-dir; "
            "this script will not delete an existing database or settings file.",
            file=sys.stderr,
        )
        return 2

    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    secret_key = secrets.token_urlsafe(48)
    database_url = f"sqlite:///{db_path.as_posix()}"
    env_text = "\n".join(
        [
            "APP_ENV=development",
            f"SECRET_KEY={secret_key}",
            "TOKEN_TTL_SECONDS=43200",
            "CORS_ORIGINS=http://localhost:8001,http://127.0.0.1:8001",
            f"DATABASE_URL={database_url}",
            f"MEDIA_DIR={media_dir.as_posix()}",
            "LOGIN_WINDOW_MINUTES=15",
            "LOGIN_ACCOUNT_LIMIT=10",
            "LOGIN_IP_LIMIT=30",
            "GOOGLE_OAUTH_CLIENT_ID=",
            "GOOGLE_OAUTH_CLIENT_SECRET=",
            "GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8001/api/v1/auth/google/callback",
            "TELEGRAM_BOT_TOKEN=",
            "PROVIDER_TOKEN_ENCRYPTION_KEY=",
            "",
        ]
    )
    env_path.write_text(env_text, encoding="utf-8", newline="\n")

    # Configure a dedicated demo database before importing application modules.
    os.environ["APP_ENV"] = "development"
    os.environ["SECRET_KEY"] = secret_key
    os.environ["TOKEN_TTL_SECONDS"] = "43200"
    os.environ["CORS_ORIGINS"] = "http://localhost:8001,http://127.0.0.1:8001"
    os.environ["DATABASE_URL"] = database_url
    os.environ["MEDIA_DIR"] = str(media_dir)
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""
    os.environ["TELEGRAM_BOT_TOKEN"] = ""

    sys.path.insert(0, str(ROOT / "backend"))
    from app.db import Base, SessionLocal, engine
    from app.models import (
        AuditLog,
        Campaign,
        Contact,
        Conversation,
        InstallationState,
        Membership,
        Message,
        Organization,
        Post,
        SocialAccount,
        Task,
        User,
        UserPreference,
        utcnow,
    )
    from app.security import hash_password

    Base.metadata.create_all(bind=engine)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        organization = Organization(name="M Demo Studio", timezone="Asia/Hebron")
        db.add(organization)
        db.flush()

        owner = User(
            email=DEMO_EMAIL,
            full_name="M Demo Owner",
            password_hash=hash_password(DEMO_PASSWORD),
            is_active=True,
            must_change_password=False,
            auth_version=0,
        )
        db.add(owner)
        db.flush()

        db.add(InstallationState(id="primary", organization_id=organization.id))
        db.add(Membership(organization_id=organization.id, user_id=owner.id, role="owner"))
        db.add(UserPreference(user_id=owner.id, theme_mode="dark", accent_color="blue", density="comfortable"))

        accounts = [
            SocialAccount(organization_id=organization.id, platform="Instagram", account_name="M Studio Instagram", handle="@mstudio.demo", connection_status="disconnected"),
            SocialAccount(organization_id=organization.id, platform="Facebook", account_name="M Studio Facebook", handle="mstudio.demo", connection_status="disconnected"),
            SocialAccount(organization_id=organization.id, platform="Telegram", account_name="M Studio Telegram", handle="@mstudio_updates_demo", connection_status="disconnected"),
            SocialAccount(organization_id=organization.id, platform="X", account_name="M Studio on X", handle="@mstudio_demo", connection_status="disconnected"),
        ]
        db.add_all(accounts)
        db.flush()

        posts = [
            Post(
                organization_id=organization.id, title="حكاية منتجنا الجديد",
                content="كل تفصيلة تبدأ من فكرة. شاركونا رأيكم في الإصدار الجديد وما الذي تحبون رؤيته لاحقًا.",
                platform="Instagram", status="draft", created_by=owner.id,
            ),
            Post(
                organization_id=organization.id, title="ثلاث نصائح لمحتوى أقرب لجمهورك",
                content="اعرف جمهورك، حافظ على نبرة واضحة، وراجع النتائج قبل أن تكرر أي حملة. هذه مسودة تجريبية لعرض تقويم المحتوى.",
                platform="Facebook", status="in_review", created_by=owner.id,
            ),
            Post(
                organization_id=organization.id, title="إطلاق سلسلة أسبوعية",
                content="موعد تجريبي محفوظ داخل M. لا يتم نشره تلقائيًا لأن المجدول الخلفي والتكامل الخارجي غير مفعّلين في هذه النسخة.",
                platform="Instagram", status="scheduled",
                scheduled_at=now + timedelta(days=2), social_account_id=accounts[0].id,
                created_by=owner.id,
            ),
            Post(
                organization_id=organization.id, title="رسالة قصيرة للمجتمع",
                content="نستمع إلى ملاحظاتكم ونحوّلها إلى خطوات تطوير قابلة للقياس. سجل تجريبي لا يرسل محتوى إلى أي منصة.",
                platform="Telegram", status="approved", created_by=owner.id,
            ),
            Post(
                organization_id=organization.id, title="مسودة إعلان تعريفي",
                content="مسودة محفوظة للمراجعة الداخلية. أي نشر خارجي يحتاج إلى موصل رسمي موثّق ومفعل.",
                platform="X", status="draft", created_by=owner.id,
            ),
        ]
        db.add_all(posts)

        contacts = [
            Contact(organization_id=organization.id, name="ليان الخطيب", company="استوديو أثر", email="layan@example.com", phone="+970 599 000 101", source="Instagram", stage="qualified", value=2400, follow_up_at=now + timedelta(days=1), notes="مهتمة بخطة إدارة محتوى شهرية."),
            Contact(organization_id=organization.id, name="عمر منصور", company="بيت البن", email="omar@example.com", phone="+970 599 000 102", source="Facebook", stage="proposal", value=3800, follow_up_at=now + timedelta(days=3), notes="طلب عرضًا لإدارة حملتين."),
            Contact(organization_id=organization.id, name="نور ياسين", company="نواة للتصميم", email="noor@example.com", phone="+970 599 000 103", source="Referral", stage="new", value=1200, follow_up_at=now + timedelta(days=4), notes="جهة اتصال تجريبية."),
            Contact(organization_id=organization.id, name="سامي عوض", company="رواق", email="sami@example.com", phone="+970 599 000 104", source="Manual", stage="won", value=1800, notes="فرصة تجريبية مغلقة؛ ليست إيرادًا حقيقيًا."),
        ]
        db.add_all(contacts)
        db.flush()

        tasks = [
            Task(organization_id=organization.id, title="مراجعة تقويم المحتوى", description="تدقيق مواعيد المسودات قبل اعتمادها.", assignee="ليان", priority="high", status="in_progress", due_at=now + timedelta(hours=6), created_by=owner.id),
            Task(organization_id=organization.id, title="إعداد موجز الحملة", description="تحديد الجمهور والرسالة والهدف.", assignee="عمر", priority="medium", status="open", due_at=now + timedelta(days=1), created_by=owner.id),
            Task(organization_id=organization.id, title="تجهيز صور المنشور", description="مراجعة الأبعاد والنصوص البديلة.", assignee="نور", priority="medium", status="open", due_at=now + timedelta(days=2), created_by=owner.id),
            Task(organization_id=organization.id, title="مراجعة بيانات الحسابات", description="التأكد من أن الحالات التجريبية واضحة.", assignee="M Demo Owner", priority="low", status="done", due_at=now - timedelta(days=1), created_by=owner.id),
        ]
        db.add_all(tasks)

        campaigns = [
            Campaign(organization_id=organization.id, name="تعريف بالعلامة", objective="awareness", status="planning", budget=1500, start_at=now + timedelta(days=7), end_at=now + timedelta(days=21), notes="خطة توضيحية داخل M؛ لا تشتري إعلانات.", created_by=owner.id),
            Campaign(organization_id=organization.id, name="تفاعل المجتمع", objective="engagement", status="active", budget=950, start_at=now - timedelta(days=2), end_at=now + timedelta(days=12), notes="حالة تجريبية لتوضيح عرض الحملة.", created_by=owner.id),
            Campaign(organization_id=organization.id, name="جمع فرص العملاء", objective="leads", status="completed", budget=2100, start_at=now - timedelta(days=30), end_at=now - timedelta(days=10), notes="أرقام ميزانية افتراضية لأغراض العرض فقط.", created_by=owner.id),
        ]
        db.add_all(campaigns)

        conversation_a = Conversation(organization_id=organization.id, channel="Instagram", contact_id=contacts[0].id, status="open", last_message_at=now - timedelta(hours=2))
        conversation_b = Conversation(organization_id=organization.id, channel="Facebook", contact_id=contacts[1].id, status="open", last_message_at=now - timedelta(hours=5))
        db.add_all([conversation_a, conversation_b])
        db.flush()
        db.add_all(
            [
                Message(organization_id=organization.id, conversation_id=conversation_a.id, direction="inbound", body="مرحبًا، أود معرفة تفاصيل الباقة الشهرية.", delivery_status="local_only", created_at=now - timedelta(hours=2)),
                Message(organization_id=organization.id, conversation_id=conversation_a.id, direction="outbound", body="أهلًا بك! هذه رسالة تجريبية محفوظة داخل M فقط.", delivery_status="local_only", created_at=now - timedelta(hours=1, minutes=50)),
                Message(organization_id=organization.id, conversation_id=conversation_b.id, direction="inbound", body="هل يوجد عرض لإدارة المحتوى؟", delivery_status="local_only", created_at=now - timedelta(hours=5)),
            ]
        )
        db.add(
            AuditLog(
                organization_id=organization.id, user_id=owner.id,
                action="demo.seeded", entity_type="demo_workspace",
                entity_id=organization.id,
                details='{"sample_data":true,"external_actions":false}',
            )
        )
        db.commit()

    engine.dispose()
    print("Created an isolated M demo database.")
    print(f"Demo workspace: {organization.name}")
    print(f"Demo login: {DEMO_EMAIL}")
    print(f"Demo password: {DEMO_PASSWORD}")
    print(f"Database: {db_path}")
    print(f"Local settings: {env_path}")
    print("All sample records are fictional. Social accounts are disconnected and messages are local-only.")
    print("Never use the demo password or demo database for real work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
