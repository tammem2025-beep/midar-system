"""Authoritative catalog of social-platform capabilities for the current release.

This is capability metadata, not proof of account connection. Provider-specific
operations become live only when a connector is implemented, credentials are
configured, and the target account/destination is verified.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

PROVIDER_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "platform": "Facebook",
        "method": "Meta Graph API / OAuth",
        "docs_url": "https://developers.facebook.com/docs/graph-api/",
        "implementation_status": "partial",
        "status_label_ar": "ربط وقراءة المحتوى",
        "description_ar": "تكامل صفحات الأعمال باستخدام واجهات Meta الرسمية.",
        "implemented_capabilities": ["account_authorization", "read_page_posts", "read_page_videos", "publish_page_text"],
        "planned_capabilities": ["نشر الصور والفيديو", "الجدولة الخلفية", "التحليلات الموسعة"],
        "requirements_ar": ["تطبيق Meta للمطورين", "تفويض OAuth", "الصلاحيات ومراجعة التطبيق حسب الاستخدام"],
        "limitations_ar": "يوفر هذا الإصدار ربط صفحات Facebook وقراءة محتواها ونشر المنشورات النصية بعد منح pages_manage_posts فعليًا. نشر الصور والفيديو والرسائل والجدولة الخلفية ما زالت غير مفعّلة.",
        "required_environment": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
    },
    {
        "platform": "Instagram",
        "method": "Instagram Platform / OAuth",
        "docs_url": "https://developers.facebook.com/docs/instagram-platform/",
        "implementation_status": "partial",
        "status_label_ar": "ربط وقراءة الوسائط",
        "description_ar": "تكامل الحسابات الاحترافية والوظائف التي تسمح بها واجهات Instagram.",
        "implemented_capabilities": ["account_authorization", "read_media", "read_reels"],
        "planned_capabilities": ["نشر المحتوى", "التعليقات والرسائل", "التحليلات الموسعة"],
        "requirements_ar": ["حساب مؤهل حسب منتج API", "تفويض المستخدم", "الصلاحيات ومراجعة التطبيق حسب الحالة"],
        "limitations_ar": "يتيح هذا الإصدار قراءة وسائط الحسابات الاحترافية المرتبطة بصفحات Facebook فقط. حسابات Instagram الشخصية غير مدعومة، والنشر والرسائل لم يُفعّلا.",
        "required_environment": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
    },
    {
        "platform": "WhatsApp",
        "method": "WhatsApp Business Platform / Cloud API / Webhooks",
        "docs_url": "https://developers.facebook.com/docs/whatsapp/cloud-api/",
        "implementation_status": "partial",
        "status_label_ar": "ربط رقم أعمال ورسائل فعلية",
        "description_ar": "تحقق من رقم WhatsApp Business عبر Cloud API، واستقبال الرسائل عبر Webhook موقّع، وإرسال النص من صندوق الرسائل بعد ربط الرقم.",
        "implemented_capabilities": ["verify_business_number", "send_text", "receive_webhooks", "read_inbound_text", "delivery_status_updates"],
        "planned_capabilities": ["قوالب الرسائل من الواجهة", "تنزيل الوسائط الواردة", "إرسال الصور والفيديو والملفات"],
        "requirements_ar": ["إعداد WhatsApp Business Platform", "معرّف رقم الهاتف", "رمز وصول وتحقق Webhook"],
        "limitations_ar": "تطبق سياسات نافذة المراسلة والقوالب والتسعير والصلاحيات الخاصة بـ WhatsApp Business.",
        "required_environment": ["WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"],
    },
    {
        "platform": "Telegram",
        "method": "Telegram Bot API",
        "docs_url": "https://core.telegram.org/bots/api",
        "implementation_status": "partial",
        "status_label_ar": "موصل جزئي",
        "description_ar": "الوظائف الخارجية الحالية تقتصر على التحقق من وجهة البوت ونشر النص يدويًا.",
        "implemented_capabilities": ["verify_destination", "publish_text"],
        "planned_capabilities": ["استقبال Updates", "نشر الوسائط", "الجدولة الخلفية", "مزامنة تحليلات موسعة"],
        "requirements_ar": ["رمز بوت محفوظ في الخادم", "إضافة البوت إلى القناة كمسؤول", "صلاحية النشر للقناة"],
        "limitations_ar": "لا توجد في هذا الإصدار رسائل واردة أو نشر وسائط أو جدولة خلفية؛ الحسابات الشخصية ليست مدعومة عبر Bot API بهذا الشكل.",
        "required_environment": ["TELEGRAM_BOT_TOKEN"],
    },
    {
        "platform": "X",
        "method": "X API / OAuth",
        "docs_url": "https://docs.x.com/x-api/getting-started/about-x-api",
        "implementation_status": "partial",
        "status_label_ar": "ربط الحساب ونشر النص",
        "description_ar": "OAuth حقيقي لربط حساب X، وقراءة المنشورات المتاحة عند منح tweet.read، ونشر النص عند منح tweet.write. قراءة التفاعلات والوسائط والميزات الموسعة تعتمد على خطة API.",
        "implemented_capabilities": ["account_authorization", "read_profile", "read_posts", "publish_text"],
        "planned_capabilities": ["قراءة التفاعلات والتحليلات", "النشر بالوسائط", "مزامنة المكتبة بتفاصيل إضافية"],
        "requirements_ar": ["تطبيق مطور X", "OAuth", "مراجعة تسعير الاستخدام والحصص"],
        "limitations_ar": "يتطلب تطبيق مطور X مفعلًا وصلاحيات tweet.read وtweet.write عند الحاجة. الخطط والحصص تحدد الموارد المتاحة؛ النشر النصي فقط مدعوم في هذا الموصل.",
        "required_environment": ["X_CLIENT_ID", "X_CLIENT_SECRET", "X_REDIRECT_URI"],
    },
    {
        "platform": "YouTube",
        "method": "YouTube Data API / OAuth 2.0",
        "docs_url": "https://developers.google.com/youtube/v3",
        "implementation_status": "partial",
        "status_label_ar": "ربط القناة وقراءة ملفها",
        "description_ar": "OAuth حقيقي للتحقق من قناة YouTube وقراءة بياناتها الأساسية؛ رفع الفيديو ومزامنة المكتبة يتطلبان مسارات إضافية.",
        "implemented_capabilities": ["account_authorization", "read_profile", "read_videos"],
        "planned_capabilities": ["رفع الفيديو", "مزامنة مكتبة الفيديو بشكل متزامن", "التحليلات المتاحة"],
        "requirements_ar": ["مشروع Google Cloud", "تفعيل YouTube Data API", "OAuth وحصص الاستخدام"],
        "limitations_ar": "يتطلب المشروع تفعيل YouTube Data API ومنح youtube.readonly للقناة. قراءة الفيديوهات تعمل عبر API؛ رفع الفيديو غير مفعّل في هذا الإصدار.",
        "required_environment": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI"],
    },
    {
        "platform": "TikTok",
        "method": "TikTok Content Posting API / OAuth",
        "docs_url": "https://developers.tiktok.com/docs/en/content-posting-api-get-started",
        "implementation_status": "partial",
        "status_label_ar": "ربط الحساب وقراءة الملف",
        "description_ar": "OAuth حقيقي لربط TikTok وقراءة ملف المستخدم؛ المحتوى والنشر يحتاجان المنتجات والصلاحيات التي توافق عليها TikTok.",
        "implemented_capabilities": ["account_authorization", "read_profile", "read_videos"],
        "planned_capabilities": ["النشر المباشر أو رفع المسودات", "حالة النشر", "مزامنة الفيديوهات بتفاصيل إضافية"],
        "requirements_ar": ["تطبيق TikTok للمطورين", "نطاقات مصرح بها", "موافقة وتدقيق قبل النشر العام عند اللزوم"],
        "limitations_ar": "قراءة الفيديوهات تعتمد على تفعيل Display API ومنح video.list. نشر المحتوى غير مفعّل، ويتطلب موافقة منتج وصلاحية video.publish ومسار نشر رسمي.",
        "required_environment": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"],
    },
    {
        "platform": "LinkedIn",
        "method": "LinkedIn Posts API / OAuth",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api",
        "implementation_status": "partial",
        "status_label_ar": "ربط العضو ونشر النص",
        "description_ar": "OAuth حقيقي لربط عضو LinkedIn ونشر نصوصه الشخصية بعد منح w_member_social؛ نشر المؤسسة والقراءة المقيدة تحتاج صلاحيات إضافية.",
        "implemented_capabilities": ["account_authorization", "read_profile", "publish_text"],
        "planned_capabilities": ["نشر باسم المؤسسات", "قراءة منشورات وتفاعلات وفق الصلاحيات"],
        "requirements_ar": ["تطبيق LinkedIn", "صلاحيات المنتج المعتمدة", "دور مناسب في صفحة المؤسسة عند النشر باسمها"],
        "limitations_ar": "ربط ملف العضو ونشر المنشورات النصية الشخصية مدعومان بعد منح w_member_social؛ النشر باسم المؤسسات والقراءة المتقدمة تتطلب موافقات وصلاحيات منفصلة.",
        "required_environment": ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"],
    },
    {
        "platform": "Other",
        "method": "تسجيل داخلي فقط",
        "docs_url": None,
        "implementation_status": "manual_only",
        "status_label_ar": "سجل داخلي فقط",
        "description_ar": "يمكن تسجيل منصة أخرى كمرجع داخلي، دون أي ربط أو اتصال خارجي.",
        "implemented_capabilities": ["manual_record"],
        "planned_capabilities": [],
        "requirements_ar": [],
        "limitations_ar": "إضافة السجل لا تنشئ تكاملًا مع المنصة.",
        "required_environment": [],
    },
)


def public_provider_catalog() -> list[dict[str, Any]]:
    """Return non-secret capability metadata for users allowed to view accounts."""
    return deepcopy(list(PROVIDER_REGISTRY))


def provider_by_name(platform: str) -> dict[str, Any] | None:
    for provider in PROVIDER_REGISTRY:
        if provider["platform"] == platform:
            return provider
    return None
