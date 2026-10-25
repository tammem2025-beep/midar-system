# ابدأ من هنا — M 0.22.0

العلامة: **M**  
العبارة: **Manage. Connect. Grow.**

## تشغيل على Windows

1. نزّل ZIP للمصدر من GitHub وفكّه في مجلد منفصل.
2. افتح PowerShell من جذر المجلد.
3. نفّذ:

    Set-ExecutionPolicy -Scope Process Bypass -Force
    .\run-m-windows.ps1

4. افتح http://127.0.0.1:8000. اترك نافذة PowerShell مفتوحة.
5. لا تستبدل ملف .env الموجود، ولا تنقل قاعدة بياناتك فوق نسخة جديدة دون نسخة احتياطية.

ملف التشغيل ASCII لتجنّب مشاكل الترميز في Windows PowerShell 5.1. يستخدم Python 3.12 أو 3.13.

## تجربة عرض مع بيانات وهمية

نفّذ:

    .\tools\run-demo-windows.ps1

ثم افتح http://127.0.0.1:8001. استخدم حساب العرض الموجود في DEMO-GUIDE-AR.md. بيانات العرض في demo-data منفصلة عن قاعدة بيانات العمل، وجميع الحسابات الاجتماعية مفصولة والرسائل محلية فقط.

## معاينة من الهاتف على الشبكة المحلية

على شبكة Wi-Fi خاصة وموثوقة فقط:

    .\run-m-windows.ps1 -LAN

استخدم عنوان IPv4 الذي يطبعه السكربت على الهاتف. هذا اتصال HTTP غير مشفر للمعاينة، وليس نشرًا عامًا ولا تثبيت PWA رسميًا.

## تثبيت Windows

راجع docs/WINDOWS-DISTRIBUTION-AR.md. بعد نجاح سير بناء Windows في GitHub Actions نزّل الأثر M-Windows-x64-Installer. المثبت يحفظ بيانات العمل تحت %LOCALAPPDATA%\M\ خارج مجلد التطبيق. المثبت غير موقع رقميًا في هذا الإصدار.

## تثبيت الهاتف والكمبيوتر عبر PWA

يتطلب رابط HTTPS مستضافًا يمكن الوصول إليه من الجهاز. لا يوجد رابط HTTPS عام مستضاف ضمن هذه المرحلة. تعليمات Android وiPhone وWindows موجودة في docs/MOBILE-PWA-SETUP-AR.md.

## التحقق

من جذر المشروع:

    python -m pytest -q
    python tools/build_frontend_css.py
    node --check frontend/i18n.js
    node --check frontend/app.js
    node --check frontend/settings-enhanced.js
    node --check frontend/command-center.js
    npm install
    npx playwright install chromium
    npm run test:e2e

اطلع على نتائج GitHub Actions قبل اعتبار أي بناء أو اختبار مكتملًا.

## حدود تكاملات التواصل

ظهور Facebook/Instagram/WhatsApp/X/Telegram في الكتالوج لا يعني اتصال الحساب. Google OIDC هو تسجيل دخول إلى M فقط. Telegram موصل جزئي للنشر النصي اليدوي والتحقق من القناة؛ لم يتم تفعيل نشر تلقائي شامل لجميع المنصات.
