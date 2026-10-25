# ابدأ من هنا — M 0.21.1

الاسم الظاهر للمنتج هو **M**، والعبارة المعتمدة تحته هي **Manage. Connect. Grow.**. هذا الإصدار يحسّن عرض العلامة وتجربة تسجيل الدخول ويحدّث مراجع cache؛ ولا يغيّر عن قصد مخطط قاعدة البيانات أو مفاتيح الجلسات الداخلية أو صلاحيات API.

## تشغيل آمن

1. أوقف الخادم قبل التحديث.
2. احفظ نسخة من قاعدة البيانات وملف `.env` والملفات الموجودة داخل `data/`.
3. لا تستبدل ملف `.env` بنموذج جديد إذا كان لديك إعداد حالي. لا تشارك المفاتيح أو رموز الموصلات.
4. على Windows شغّل `run-m-windows.ps1` من جذر المشروع.
5. افتح `http://127.0.0.1:8000` وتحقق من تسجيل الدخول وظهور بياناتك قبل حذف أي نسخ احتياطية.

## أهم الملفات

- `frontend/brand-m-mark.svg`: رمز M الصغير.
- `frontend/brand-lockup.svg`: الشعار الكامل بالترتيب العمودي، والعبارة تحت M.
- `frontend/styles-src/14-m-brand-identity.css`: طبقة الهوية النهائية.
- `frontend/midar-ui.css`: CSS مجمّع، يُعاد بناؤه من المصدر.
- `frontend/manifest.webmanifest`: هوية تطبيق الويب القابل للتثبيت.
- `CHANGELOG-0.21.1.md`: سجل التغييرات.
- `docs/BRAND-IDENTITY-M-0.21.1-AR.md`: مواصفة الهوية.
- `docs/INTEGRATION-SECURITY-AUDIT-AR.md`: حالة التكاملات والأمن.
- `docs/PRODUCTION-CHECKLIST.md`: قائمة الاستعداد للنشر.

## التحقق المحلي

من جذر المستودع:

```powershell
python -m pytest -q
python tools/build_frontend_css.py
node --check frontend/app.js
node --check frontend/settings-enhanced.js
node --check frontend/command-center.js
```

تُضاف في GitHub Actions اختبارات مماثلة. لا تعتبر نجاح تنزيل الملفات دليلًا على أن الخادم أو قاعدة بيانات جهازك يعملان؛ اختبر التشغيل وتسجيل الدخول محليًا.

## حدود التكاملات

تسجيل Google يخص هوية مستخدم M فقط. موصل Telegram محدود بوظائف موثقة. بقية المنصات ليست متصلة بمجرد ظهورها في الكتالوج؛ يلزم تنفيذ OAuth/Webhooks/مهام النشر حسب المنصة والحصول على الصلاحيات المطلوبة.
