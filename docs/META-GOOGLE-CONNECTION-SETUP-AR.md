# إعداد تسجيل Google وربط حسابات التواصل في M

## تسجيل الدخول باستخدام Google

أنشئ OAuth Client من نوع **Web application** في Google Cloud Console، وأضف Redirect URI المحلي التالي:

`http://127.0.0.1:8000/api/v1/auth/google/callback`

افتح ملف الإعدادات المحلي `%LOCALAPPDATA%\\M\\.env` وضع قيم `GOOGLE_OAUTH_CLIENT_ID` و`GOOGLE_OAUTH_CLIENT_SECRET`، ثم أعد تشغيل M. في أول تشغيل يمكن إنشاء مساحة العمل الأولى من حساب Google موثّق. بعد إنشاء مساحة العمل، يجب ربط هوية Google من داخل الحساب قبل استخدامها لتسجيل الدخول مستقبلًا؛ لا يربط M الحسابات تلقائيًا اعتمادًا على البريد وحده.

## Facebook وInstagram

أنشئ تطبيقًا في Meta for Developers وفعّل منتجات تسجيل الدخول وGraph API اللازمة. اطلب الصلاحيات التي يحتاجها كل استخدام: `pages_show_list` و`pages_read_engagement` و`pages_read_user_content` للقراءة، و`pages_manage_posts` لنشر النصوص إلى صفحات Facebook، و`instagram_basic` لقراءة حساب Instagram الاحترافي. قد تتطلب صلاحيات النشر موافقة Meta ومراجعة التطبيق. سجّل Redirect URI التالي في قائمة OAuth Redirect URIs المسموح بها:

`http://127.0.0.1:8000/api/v1/integrations/meta/callback`

أضف القيم إلى ملف `%LOCALAPPDATA%\\M\\.env`:

```dotenv
META_APP_ID=معرّف_تطبيق_Meta
META_APP_SECRET=سر_تطبيق_Meta
META_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/meta/callback
META_GRAPH_API_VERSION=v26.0
```

يلزم أن تدير صفحة Facebook التي تريد ربطها. يظهر حساب Instagram فقط عندما يكون من نوع **Business** أو **Creator** ومرتبطًا بصفحة Facebook، وتمنح Meta التطبيق الصلاحيات المناسبة. قد تتطلب بعض الحالات أن يكون التطبيق في وضع Live ومراجعًا من Meta.

بعد حفظ الإعدادات وإعادة تشغيل M، افتح **الحسابات الاجتماعية** ثم **ربط Facebook وInstagram** ووافق على شاشة Meta. بعد الربط، استخدم **عرض المنشورات والفيديوهات** لجلب المحتوى المسموح به من الواجهات الرسمية.

## ما هو متاح فعليًا؟

- Google: تسجيل دخول عبر OAuth وإعداد مساحة العمل الأولى بعد إعداد بيانات OAuth.
- Facebook: ربط صفحاتك وقراءة المنشورات والفيديوهات، إضافة إلى نشر منشورات نصية بعد منح `pages_manage_posts` فعليًا. الصور والفيديو لم تُفعّل للنشر بعد.
- Instagram: قراءة وسائط/Reels للحسابات الاحترافية المؤهلة المرتبطة بصفحات Facebook؛ نشر Instagram والرسائل ما زالا غير مفعّلين.
- لا توجد جدولة خلفية دائمة أو صندوق رسائل اجتماعي متزامن في هذا الإصدار. المنشور الذي يحمل موعدًا محفوظًا لا يُرسل تلقائيًا.

## حماية بيانات الاتصال

يولّد تطبيق Windows مفتاح Fernet محليًا مرة واحدة لتشفير رموز OAuth، ويحفظه في `%LOCALAPPDATA%\\M\\.env`. احتفظ بنسخة احتياطية آمنة من ملف الإعدادات وقاعدة البيانات معًا؛ فقدان المفتاح يجعل الرموز المخزنة غير قابلة للاستعادة. لا ترفع ملف `.env` أو قاعدة بياناتك أو أسرار OAuth إلى GitHub.

المراجع الرسمية: [Google OAuth Web Server](https://developers.google.com/identity/protocols/oauth2/web-server) و[Meta Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).
