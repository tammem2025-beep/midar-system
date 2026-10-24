# هوية M — Digital Business Management (0.20.0)

## أساس العلامة
- الاسم: **M**
- الوصف: **Digital Business Management** — إدارة الأعمال الرقمية
- الشعار التسويقي: **Manage. Connect. Grow.**
- الشخصية: تقنية هادئة، بسيطة، راقية، موثوقة، وعملية.

## ألوان العلامة
- Deep Navy `#0B1020`
- Cyan `#06C6DE`
- Brand Blue `#5366FF`
- Violet `#8B3FF2`
- Light Background `#F6F8FC`
- Light Surface `#FFFFFF`
- Main Text `#172033`
- Muted Text `#596B84`

الشعار يستخدم التدرج الثابت السياني→الأزرق→البنفسجي مستقلًا عن accent الذي يختاره المستخدم داخل الواجهة. ألوان النجاح والتحذير والخطأ مستقلة عن ألوان العلامة.

## الأصول
- `frontend/brand-m-mark.svg`: الرمز المستقل، مناسب للواجهات.
- `frontend/brand-lockup.svg`: قفل أفقي يشمل M والوصف والشعار التسويقي.
- `frontend/icon.svg`: أيقونة التطبيق المتجهية.
- `frontend/icon-192.png`, `frontend/icon-512.png`, `frontend/apple-touch-icon.png`, `frontend/favicon.ico`: أصول المنصات.

## نظام التصميم
ملف `frontend/styles-src/14-m-brand-identity.css` هو الطبقة النهائية في الـ cascade. لا تُعدّل `frontend/midar-ui.css` مباشرة؛ فهو ملف مجمّع من وحدات المصدر. شغّل `python tools/build_frontend_css.py` بعد أي تغيير في ملفات `styles-src`.

## التوافق
أبقي اسم ملف CSS القديم `midar-ui.css` ومفتاح الجلسة `midar_token` خلال هذا التحديث لتجنب كسر مراجع التطبيق والجلسات القائمة. هذه أسماء تقنية داخلية، وليست أسماء تجارية معروضة. أما تفضيلات الثيم المخزنة للمستخدمين الحاليين فتظل كما هي؛ الافتراضي الأزرق ينطبق على التفضيلات الجديدة أو غير المحددة.

---

# تقرير تنفيذ الهوية والهندسة — M 0.20.0

## نطاق التنفيذ
تغيير الهوية الظاهرة من مِدار إلى M — Digital Business Management، وإنشاء أصول علامة جديدة، وإضافة طبقة CSS نهائية، وتحديث الثيم وبيانات PWA وإصدار التطبيق واختباراته.

## ما تغير
- `frontend/index.html`: العنوان وبيانات التعريف والعلامة الظاهرة وشعار تسجيل الدخول والقائمة الجانبية والتذييل ومراجع الأصول.
- `frontend/brand-m-mark.svg`, `frontend/brand-lockup.svg`, `frontend/brand-mark.svg`, `frontend/icon.svg`: الشعار وأيقونة التطبيق.
- `frontend/icon-192.png`, `frontend/icon-512.png`, `frontend/apple-touch-icon.png`, `frontend/favicon.ico`: أصول التطبيق المولدة من SVG.
- `frontend/manifest.webmanifest`: الاسم والوصف وألوان PWA.
- `frontend/styles-src/14-m-brand-identity.css`: توكنات العلامة، درجات الألوان، وضعا العرض، الرمز، المساحات، الرأس، القائمة والمكونات المشتركة.
- `tools/build_frontend_css.py` و`frontend/midar-ui.css`: بناء الطبقة الجديدة من المصدر.
- `frontend/app.js`, `settings-enhanced.js`, `command-center.js`, `sw.js`: تحديث العبارات الظاهرة والمظهر ومراجع الإصدار واسم cache.
- `backend/app/main.py`, `models.py`, `schemas.py`, `integrations/telegram.py`: بيانات إصدار API، الرسائل، وافتراضي اللون للمستخدمين الجدد.
- `tests/*`, `README.md`, `CHANGELOG-0.20.0.md`, ووثائق العلامة.

## قرارات التوافق
لا يتم تغيير قاعدة البيانات القائمة أو عقود API أو مفاتيح الجلسة. احتُفظ بمسار `midar-ui.css` الحالي لتقليل مخاطر كسر المرجع، لكنه أصبح يجمع نظام M الجديد. لم تتم إعادة تسمية جميع الرموز الداخلية التي تحمل `midar`، لأن بعضها يعمل كمعرفات جلسة أو CSS أو سجل أو إعداد وقد تكون إعادة تسميتها غير ذات فائدة وظيفية.

## حدود التحقق
- الاختبارات المذكورة في تقرير التسليم يجب تنفيذها في بيئة البناء المتاحة.
- لم يتم التحقق من الاسم قانونيًا أو من توافر نطاق/حسابات اجتماعية.
- يجب على المالك تجربة التطبيق في بيئته المحلية وبعد تحديث الـ service worker، والتأكد من أن إعدادات ثيم المستخدم الحالية تعكس التوقعات.
