# إعداد الربط الرسمي للمنصات في مِدار

يوثّق هذا الدليل إعداد مفاتيح المطوّر المطلوبة لتبدأ مِدار تدفقات OAuth/API الرسمية. **إدخال اسم الحساب لا يربطه**؛ يجب أن تنجح موافقة المزوّد والتحقق من هوية الحساب أولًا.

## قبل البدء

- لا تضع أسرار المطوّر أو رموز الوصول في GitHub أو في الواجهة أو في رسائل المحادثة.
- خزّن القيم في ملف الإعدادات المحلي الذي يستخدمه المشغّل، ثم أعد تشغيل M. في Windows المثبّت، ملف الإعدادات موجود عادةً في `%LOCALAPPDATA%\M\.env`.
- يجب أن تبقى `PROVIDER_TOKEN_ENCRYPTION_KEY` ثابتة ومحفوظة بأمان مع نسخة احتياطية محمية؛ تغييرها دون إعادة تشفير الرموز يمنع M من فك الرموز المخزنة.
- اترك `ENABLE_EXTERNAL_PUBLISHING=false` حتى تكمل إعداد الحسابات وتختبر وجهة آمنة. لا تفعّله إلا إذا أردت بدء إرسال منشورات حقيقية.

## Facebook وInstagram

أنشئ تطبيقًا في [Meta for Developers](https://developers.facebook.com/) وأكمل منتجات OAuth وGraph API والصلاحيات المطلوبة. أضف Redirect URI مطابقًا تمامًا لهذا المسار المحلي:

`http://127.0.0.1:8000/api/v1/integrations/meta/callback`

إعدادات الخادم:

```dotenv
META_APP_ID=
META_APP_SECRET=
META_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/meta/callback
META_GRAPH_API_VERSION=v26.0
```

القدرات الحالية: ربط صفحات Facebook وقراءة منشوراتها وفيديوهاتها؛ قراءة وسائط/Reels لحسابات Instagram Business/Creator المؤهلة المرتبطة بصفحة؛ ونشر نص إلى Facebook بعد منح `pages_manage_posts` فعليًا. **نشر Instagram والوسائط والرسائل والجدولة التلقائية ليست مفعّلة بعد.**

## X

أنشئ تطبيقًا في [X Developer Portal](https://developer.x.com/) واضبط OAuth 2.0 مع PKCE وScopes اللازمة. Redirect URI المحلي:

`http://127.0.0.1:8000/api/v1/integrations/oauth/x/callback`

```dotenv
X_CLIENT_ID=
X_CLIENT_SECRET=
X_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/oauth/x/callback
```

يدعم الموصل ربط الحساب وقراءة المنشورات المتاحة إذا مُنحت `tweet.read`، ونشر نصوص بعد منح `tweet.write`. تتطلب قراءة/نشر الوسائط أو الميزات الأخرى صلاحيات وخطة API مناسبة.

## LinkedIn

أنشئ تطبيقًا في [LinkedIn Developer Portal](https://www.linkedin.com/developers/) وفعّل منتجات/صلاحيات العضو الملائمة. يتطلب LinkedIn عنوان Redirect URI عامًّا عبر **HTTPS**؛ لذلك لا يكفي تشغيل M على `127.0.0.1` وحده لربط LinkedIn. عيّن Redirect URI المسجّل إلى:

`https://YOUR-PUBLIC-HOST/api/v1/integrations/oauth/linkedin/callback`

```dotenv
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REDIRECT_URI=https://YOUR-PUBLIC-HOST/api/v1/integrations/oauth/linkedin/callback
LINKEDIN_RESTLI_VERSION=202610
```

يدعم الموصل ربط ملف العضو ونشر منشور نصي بعد منح `w_member_social`. نشر المؤسسات والوصول إلى بياناتها يحتاج صلاحيات منتج وأدوارًا وموافقات منفصلة.

## TikTok

أنشئ تطبيقًا في [TikTok for Developers](https://developers.tiktok.com/) وفعّل Login Kit / Display API واطلب `user.info.basic` و`video.list`. للحزمة المحلية على Windows، سجّل Redirect URI الخاص بتطبيق Desktop:

`http://127.0.0.1:8000/api/v1/integrations/oauth/tiktok/callback`

```dotenv
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/oauth/tiktok/callback
```

يدعم الموصل ربط حساب TikTok وقراءة الملف والفيديوهات التي تسمح بها الصلاحيات. نشر الفيديو المباشر يتطلب `video.publish` وموافقة التطبيق واتباع عملية النشر الرسمية؛ هذا الإجراء لم يُفعّل بعد داخل مِدار.

## YouTube

في [Google Cloud Console](https://console.cloud.google.com/) فعّل YouTube Data API وأنشئ OAuth Client مناسبًا. Redirect URI المحلي:

`http://127.0.0.1:8000/api/v1/integrations/oauth/youtube/callback`

```dotenv
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/integrations/oauth/youtube/callback
```

يدعم الموصل ربط قناة YouTube وقراءة محتواها الذي تسمح به `youtube.readonly`. رفع الفيديو إلى YouTube يحتاج `youtube.upload` وحصص API، ولم يُفعّل بعد.

## WhatsApp Business

هذا التكامل خاص بـ **WhatsApp Business Platform / Cloud API**، وليس حساب WhatsApp الشخصي. في تطبيق Meta أضف WhatsApp، واحصل على Phone Number ID ورمز الوصول، واضبط Webhook. يحتاج استقبال الأحداث إلى عنوان HTTPS عام يمكن لـ Meta الوصول إليه.

```dotenv
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_GRAPH_API_VERSION=v26.0
```

- استخدم زر «التحقق من رقم الأعمال» من الإعدادات بعد حفظ القيم؛ يتحقق M عبر Cloud API ويحفظ اعتماد الرقم مشفّرًا.
- سجّل عنوان Webhook في Meta ليكون `https://YOUR-PUBLIC-HOST/api/v1/webhooks/whatsapp`، واضبط Verify Token نفسه في إعدادات Meta و`WHATSAPP_VERIFY_TOKEN`. يجب أن يطابق `WHATSAPP_APP_SECRET` سر تطبيق Meta المستخدم لتوقيع الأحداث.
- يدعم الإصدار الرسائل النصية الواردة والردود النصية وحالات التسليم من webhook موقّع. الرسائل خارج نافذة خدمة العملاء قد تحتاج قالبًا معتمدًا من Meta؛ إنشاء وإرسال القوالب وإرسال/تنزيل الوسائط لم يُفعّلا بعد.

## Telegram

أنشئ Bot عبر [@BotFather](https://t.me/BotFather)، احفظ الرمز في الخادم، وأضف البوت مسؤولًا في القناة مع صلاحية النشر. أدخل القناة من الحسابات الاجتماعية ثم استخدم «تحقق من القناة».

```dotenv
TELEGRAM_BOT_TOKEN=
```

يدعم الموصل التحقق من الوجهة ونشر النص يدويًا فقط. استقبال رسائل البوت، ونشر الوسائط، والجدولة الخلفية ليست مكتملة.

## تفعيل النشر الحقيقي

بعد إكمال إعدادات التطبيق والموافقة على الصلاحيات والتحقق من الحسابات، فعّل النشر الخارجي عن قصد على الخادم:

```dotenv
ENABLE_EXTERNAL_PUBLISHING=true
```

التفعيل يتيح فقط الوظائف المنفّذة للحساب الذي منح الصلاحية المطلوبة. لا يعني هذا نشرًا تلقائيًا عند `scheduled_at`: خدمة الجدولة المستمرة غير موجودة بعد. في بيئة الإنتاج، استخدم HTTPS، وخزّن الأسرار في مدير أسرار آمن، واختبر النسخ الاحتياطية والاستعادة وأذونات المزوّد قبل ربط حسابات العملاء.
