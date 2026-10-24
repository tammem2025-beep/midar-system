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
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل صفحات الأعمال باستخدام واجهات Meta الرسمية.",
        "implemented_capabilities": [],
        "planned_capabilities": ["ربط الصفحات", "نشر أنواع المحتوى المدعومة", "قراءة الإحصاءات والصلاحيات المتاحة"],
        "requirements_ar": ["تطبيق Meta للمطورين", "تفويض OAuth", "الصلاحيات ومراجعة التطبيق حسب الاستخدام"],
        "limitations_ar": "تختلف الإمكانات حسب نوع الأصل والصلاحيات المعتمدة؛ لا يدعم هذا الإصدار ربط Facebook خارجيًا.",
        "required_environment": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
    },
    {
        "platform": "Instagram",
        "method": "Instagram Platform / OAuth",
        "docs_url": "https://developers.facebook.com/docs/instagram-platform/",
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل الحسابات الاحترافية والوظائف التي تسمح بها واجهات Instagram.",
        "implemented_capabilities": [],
        "planned_capabilities": ["ربط الحسابات المؤهلة", "نشر المحتوى المدعوم", "قراءة بيانات الأداء المتاحة"],
        "requirements_ar": ["حساب مؤهل حسب منتج API", "تفويض المستخدم", "الصلاحيات ومراجعة التطبيق حسب الحالة"],
        "limitations_ar": "لا يدعم هذا الإصدار نشر Instagram أو قراءة الرسائل خارجيًا؛ القدرات النهائية تعتمد على نوع الحساب والصلاحيات.",
        "required_environment": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
    },
    {
        "platform": "WhatsApp",
        "method": "WhatsApp Business Platform / Cloud API / Webhooks",
        "docs_url": "https://developers.facebook.com/docs/whatsapp/cloud-api/",
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل مراسلة الأعمال عبر المنصة الرسمية، وليس التحكم بحساب WhatsApp شخصي.",
        "implemented_capabilities": [],
        "planned_capabilities": ["استقبال أحداث الرسائل", "إرسال رسائل الأعمال المسموحة", "حالة التسليم حسب الأحداث المتاحة"],
        "requirements_ar": ["إعداد WhatsApp Business Platform", "معرّف رقم الهاتف", "رمز وصول وتحقق Webhook"],
        "limitations_ar": "تطبق سياسات نافذة المراسلة والقوالب والتسعير والصلاحيات الخاصة بـ WhatsApp Business.",
        "required_environment": ["WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN"],
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
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "موصل مقترح للنشر وقراءة موارد X التي تسمح بها الصلاحيات وخطة الوصول.",
        "implemented_capabilities": [],
        "planned_capabilities": ["تفويض OAuth", "نشر المنشورات المدعومة", "قراءة الموارد المتاحة وفق الخطة"],
        "requirements_ar": ["تطبيق مطور X", "OAuth", "مراجعة تسعير الاستخدام والحصص"],
        "limitations_ar": "الوصول والميزانية يعتمدان على خطة X API وحدودها الحالية؛ لا يدعم هذا الإصدار عمليات X الخارجية.",
        "required_environment": ["X_CLIENT_ID", "X_CLIENT_SECRET", "X_REDIRECT_URI"],
    },
    {
        "platform": "YouTube",
        "method": "YouTube Data API / OAuth 2.0",
        "docs_url": "https://developers.google.com/youtube/v3",
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل مقترح لإدارة الفيديوهات وبيانات القناة المتاحة.",
        "implemented_capabilities": [],
        "planned_capabilities": ["تفويض القناة", "رفع الفيديو ضمن القيود", "قراءة بيانات القناة والفيديو"],
        "requirements_ar": ["مشروع Google Cloud", "تفعيل YouTube Data API", "OAuth وحصص الاستخدام"],
        "limitations_ar": "تخضع عمليات الرفع والقراءة لحصص API وسياسات Google؛ لم تُنفذ عمليات YouTube في هذا الإصدار.",
        "required_environment": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REDIRECT_URI"],
    },
    {
        "platform": "TikTok",
        "method": "TikTok Content Posting API / OAuth",
        "docs_url": "https://developers.tiktok.com/docs/en/content-posting-api-get-started",
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل مقترح للنشر المباشر أو رفع المسودات وفق منتجات TikTok المعتمدة.",
        "implemented_capabilities": [],
        "planned_capabilities": ["تفويض صانع المحتوى", "تهيئة نشر الصور والفيديو وفق API", "متابعة حالة النشر"],
        "requirements_ar": ["تطبيق TikTok للمطورين", "نطاقات مصرح بها", "موافقة وتدقيق قبل النشر العام عند اللزوم"],
        "limitations_ar": "قد يقتصر المحتوى على الخصوصية إذا لم يُدقَّق التطبيق؛ يجب تطبيق إرشادات المشاركة والواجهة الرسمية.",
        "required_environment": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"],
    },
    {
        "platform": "LinkedIn",
        "method": "LinkedIn Posts API / OAuth",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api",
        "implementation_status": "planned",
        "status_label_ar": "قيد التطوير",
        "description_ar": "تكامل مقترح لنشر محتوى الأعضاء أو المؤسسات بحسب صلاحيات الوصول.",
        "implemented_capabilities": [],
        "planned_capabilities": ["تفويض العضو", "النشر للمستخدم أو المؤسسة عند السماح", "قراءة التفاعلات المدعومة"],
        "requirements_ar": ["تطبيق LinkedIn", "صلاحيات المنتج المعتمدة", "دور مناسب في صفحة المؤسسة عند النشر باسمها"],
        "limitations_ar": "تتوقف الوظائف على صلاحيات المنتج ومستوى الوصول وأدوار المؤسسة؛ لا يدعم هذا الإصدار LinkedIn خارجيًا.",
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
