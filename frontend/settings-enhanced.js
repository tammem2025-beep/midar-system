/* M — user preferences, Google OIDC UX, profile/settings and account menu.
 * Loaded before app.js; all requests go through the existing authenticated API client.
 */
let midarSettingsTab = 'profile';
let midarSavedPreferences = { theme_mode: 'dark', accent_color: 'blue', density: 'comfortable' };
const MIDAR_ACCENTS = {
  violet: { label: 'بنفسجي', hex: '#8B3FF2' },
  blue: { label: 'أزرق العلامة', hex: '#5366FF' },
  cyan: { label: 'سماوي العلامة', hex: '#06C6DE' },
  emerald: { label: 'زمردي', hex: '#10B981' },
  rose: { label: 'وردي', hex: '#F43F8B' },
  amber: { label: 'ذهبي', hex: '#D99A24' },
};

function applyAppearancePrefs(prefs = {}) {
  const root = document.documentElement;
  const themePreference = ['dark', 'light', 'system'].includes(prefs.theme_mode) ? prefs.theme_mode : 'dark';
  const systemIsLight = Boolean(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
  const resolvedTheme = themePreference === 'system' ? (systemIsLight ? 'light' : 'dark') : themePreference;
  const accent = Object.prototype.hasOwnProperty.call(MIDAR_ACCENTS, prefs.accent_color) ? prefs.accent_color : 'blue';
  const density = ['comfortable', 'compact'].includes(prefs.density) ? prefs.density : 'comfortable';
  root.dataset.theme = resolvedTheme;
  root.dataset.themePreference = themePreference;
  root.dataset.accent = accent;
  root.dataset.density = density;
  root.style.colorScheme = resolvedTheme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', resolvedTheme === 'light' ? '#f4f6fb' : '#0b1020');
  midarSavedPreferences = { theme_mode: themePreference, accent_color: accent, density };
}

async function loadAndApplyPreferences() {
  const prefs = await api('/preferences');
  applyAppearancePrefs(prefs);
  return prefs;
}

async function configureGoogleLogin(setupRequired) {
  const button = document.querySelector('#googleLoginBtn');
  const note = document.querySelector('#googleAuthNote');
  if (!button || !note) return;
  try {
    const config = await api('/auth/google/config', { headers: {} });
    button.disabled = !config.enabled || !!setupRequired;
    if (!config.enabled) {
      note.textContent = 'تسجيل Google غير مهيأ بعد. أكمل إعداد OAuth على الخادم أولًا.';
    } else if (setupRequired) {
      note.textContent = 'أنشئ حساب مالك مساحة العمل أولًا، ثم اربط Google من الإعدادات لتفعيل الدخول به.';
    } else {
      note.textContent = 'يمكن الدخول بحساب Google بعد ربطه من الإعدادات داخل المنصة. تسجيل Google لا يربط تلقائيًا حسابات السوشيال ميديا.';
    }
  } catch (_) {
    button.disabled = true;
    note.textContent = 'تعذر التحقق من إعداد Google على الخادم.';
  }
}

async function processGoogleRedirect() {
  const raw = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : '';
  if (!raw) return null;
  const params = new URLSearchParams(raw);
  const oneTimeCode = params.get('google_code');
  const result = params.get('google_result');
  if (!oneTimeCode && !result) return null;
  // Never keep the one-time code in browser history or leave it in the address bar.
  window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
  if (oneTimeCode) {
    try {
      const out = await api('/auth/google/complete', { method: 'POST', body: JSON.stringify({ code: oneTimeCode }) });
      token = out.access_token;
      currentUser = out.user;
      sessionStorage.setItem('midar_token', token);
      return { code: 'login_success' };
    } catch (_) {
      return { code: 'exchange_failed' };
    }
  }
  return { code: result };
}

const MIDAR_GOOGLE_MESSAGES = {
  not_configured: 'تسجيل Google غير مهيأ على الخادم.',
  access_denied: 'ألغيت عملية تسجيل الدخول أو ربط Google.',
  invalid_state: 'انتهت صلاحية العملية أو تعذر التحقق منها. ابدأ من جديد.',
  exchange_failed: 'تعذر التحقق من Google. تحقق من إعداد OAuth وحاول مجددًا.',
  identity_unlinked: 'حساب Google غير مرتبط بحساب M.',
  not_linked: 'هذا الحساب غير مرتبط بالمنصة. سجّل الدخول بالبريد وكلمة المرور ثم اربطه من الإعدادات.',
  account_inactive: 'هذا الحساب غير مفعّل أو لم يعد مرتبطًا بمساحة عمل.',
  link_conflict: 'حساب Google مرتبط بمستخدم آخر أو يوجد ربط مختلف لهذا المستخدم.',
  link_stale: 'تغيرت حالة الحساب أثناء عملية الربط. سجّل الدخول وابدأ من جديد.',
  link_success: 'تم ربط حساب Google بنجاح.',
  login_success: 'تم تسجيل الدخول باستخدام Google بنجاح.',
  invalid_profile: 'تعذر قراءة معلومات حساب Google المطلوبة.',
};

function showGoogleAuthNotice(code) {
  const root = document.querySelector('#authMessage');
  if (!root) return;
  const message = MIDAR_GOOGLE_MESSAGES[code] || MIDAR_GOOGLE_MESSAGES.exchange_failed;
  const type = ['link_success', 'login_success'].includes(code) ? 'success' : 'error';
  root.innerHTML = `<div class="${type}" role="status">${esc(message)}</div>`;
}
function showGoogleNotice(code) {
  const message = MIDAR_GOOGLE_MESSAGES[code];
  if (message && typeof toast === 'function') toast(message);
}

async function renderEnhancedSettings() {
  const results = await Promise.all([
    api('/preferences').catch(() => ({ ...midarSavedPreferences })),
    api('/organization').catch(() => null),
    api('/auth/google/status').catch(() => ({ enabled: false, linked: false, email: null })),
    api('/auth/google/config', { headers: {} }).catch(() => ({ enabled: false })),
    api('/integrations/catalog').catch(() => ({ providers: [], notice: 'تعذر تحميل كتالوج التكاملات.' })),
    api('/integrations/status').catch(() => null),
  ]);
  const [prefs, organization, googleStatus, googleConfig, catalog, integrationStatus] = results;
  applyAppearancePrefs(prefs);
  const isAdmin = ['owner', 'admin'].includes(currentUser?.role);
  const tabs = [
    ['profile', '♙', 'حسابي الشخصي'],
    ['appearance', '◐', 'المظهر والألوان'],
    ['workspace', '▦', 'مساحة العمل'],
    ['integrations', '◎', 'التكاملات الاجتماعية'],
    ['security', '⛨', 'الأمان وتسجيل الدخول'],
  ];
  if (!tabs.some(t => t[0] === midarSettingsTab)) midarSettingsTab = 'profile';
  const tabNav = tabs.map(([id, icon, title]) => `<button type="button" class="settings-tab-v2 ${midarSettingsTab === id ? 'active' : ''}" data-settings-tab="${id}" aria-current="${midarSettingsTab === id ? 'page' : 'false'}"><span>${icon}</span><b>${title}</b><i>›</i></button>`).join('');
  let panel = '';

  if (midarSettingsTab === 'profile') {
    panel = `
      <section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">PROFILE</span><h3>حسابك الشخصي</h3><p>حدّث الاسم الذي يظهر لك ولفريق العمل. البريد الإلكتروني الأساسي غير قابل للتعديل قبل إضافة تحقق مستقل للبريد.</p></div><div class="settings-profile-avatar">${esc((currentUser?.full_name || 'م').trim().split(/\s+/).slice(0,2).map(x=>x[0]).join(''))}</div></div>
      <form id="settingsProfileForm" class="settings-form-v2"><div class="form-grid"><div class="field full"><label for="settingsFullName">الاسم الكامل</label><input id="settingsFullName" name="full_name" required minlength="2" maxlength="160" value="${esc(currentUser?.full_name || '')}"></div><div class="field full"><label for="settingsEmail">البريد الإلكتروني</label><input id="settingsEmail" value="${esc(currentUser?.email || '')}" disabled readonly><span class="help">تغيير البريد يتطلب مسار تحقق منفصلًا، لذلك لا يُعدّل من هذه الشاشة.</span></div></div><button class="btn btn-primary" type="submit">حفظ بيانات الحساب</button></form></section>
      <section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">GOOGLE IDENTITY</span><h3>حساب Google</h3><p>استخدم Google لإثبات هويتك وتسجيل الدخول بعد ربط الحساب. هذا لا يكشف تلقائيًا حساباتك على منصات التواصل.</p></div>${googleStatus.linked ? '<span class="settings-pill settings-pill-good">مرتبط</span>' : '<span class="settings-pill">غير مرتبط</span>'}</div>
        <div class="google-link-row"><div class="google-mark">G</div><div class="google-link-copy"><b>${googleStatus.linked ? esc(googleStatus.email || 'حساب Google مرتبط') : 'اربط حساب Google'}</b><small>${googleConfig.enabled ? (googleStatus.linked ? 'يمكن استخدام هذا الحساب لتسجيل الدخول.' : 'يتطلب إعداد OAuth على الخادم وموافقتك عبر Google.') : 'أضف بيانات OAuth على الخادم لتفعيل الربط.'}</small></div>${googleStatus.linked ? '<span class="settings-pill settings-pill-good">تم التحقق</span>' : `<button type="button" class="btn btn-google-link" id="googleLinkBtn" data-google-link ${googleConfig.enabled ? '' : 'disabled'}>ربط Google</button>`}</div>
        <div class="settings-note"><b>الخصوصية والصلاحيات</b><p>الموافقة الحالية المطلوبة للهوية هي openid وemail وprofile. للوصول إلى YouTube أو Drive أو أي خدمة Google أخرى، يجب طلب الصلاحيات الخاصة بتلك الخدمة بشكل منفصل، مع شرح سبب استخدامها.</p></div></section>`;
  } else if (midarSettingsTab === 'appearance') {
    panel = `<section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">PERSONALIZATION</span><h3>المظهر والألوان</h3><p>خصّص مظهر M وفق تفضيلاتك. تُحفظ التفضيلات لحسابك وتعود عند تسجيل الدخول من جديد.</p></div><span class="settings-live-dot"></span></div><form id="appearanceForm" class="settings-form-v2">
      <div class="settings-option-block"><label class="settings-label">نمط الواجهة</label><div class="settings-choice-grid theme-choice-grid"><label class="settings-choice"><input type="radio" name="theme_mode" value="dark" ${prefs.theme_mode === 'dark' ? 'checked' : ''}><span class="theme-sample theme-sample-dark"><i></i><i></i><i></i></span><b>داكن فاخر</b><small>مناسب للاستخدام اليومي</small></label><label class="settings-choice"><input type="radio" name="theme_mode" value="light" ${prefs.theme_mode === 'light' ? 'checked' : ''}><span class="theme-sample theme-sample-light"><i></i><i></i><i></i></span><b>فاتح نظيف</b><small>سطوع ووضوح أعلى</small></label><label class="settings-choice"><input type="radio" name="theme_mode" value="system" ${prefs.theme_mode === 'system' ? 'checked' : ''}><span class="theme-sample theme-sample-system"><i></i><i></i><i></i></span><b>حسب الجهاز</b><small>يتبع إعداد النظام</small></label></div></div>
      <div class="settings-option-block"><label class="settings-label">اللون المميز</label><div class="accent-grid">${Object.entries(MIDAR_ACCENTS).map(([id,a])=>`<label class="accent-choice ${prefs.accent_color === id ? 'selected' : ''}" title="${esc(a.label)}"><input type="radio" name="accent_color" value="${id}" ${prefs.accent_color === id ? 'checked' : ''}><span style="--swatch:${a.hex}"></span><b>${esc(a.label)}</b></label>`).join('')}</div></div>
      <div class="settings-option-block"><label class="settings-label">كثافة العرض</label><div class="settings-choice-grid density-grid"><label class="settings-choice inline-choice"><input type="radio" name="density" value="comfortable" ${prefs.density === 'comfortable' ? 'checked' : ''}><span>☷</span><b>مريح</b><small>مساحات أوسع</small></label><label class="settings-choice inline-choice"><input type="radio" name="density" value="compact" ${prefs.density === 'compact' ? 'checked' : ''}><span>☰</span><b>مضغوط</b><small>معلومات أكثر</small></label></div></div>
      <div class="settings-preview-strip"><div class="preview-orb"></div><div><b>معاينة هوية M</b><small>لون الإبراز يتغير في الأزرار والروابط والعناصر النشطة.</small></div><button class="btn btn-primary" type="submit">حفظ المظهر</button></div>
    </form></section>`;
  } else if (midarSettingsTab === 'workspace') {
    panel = `<section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">WORKSPACE</span><h3>مساحة العمل</h3><p>هذه الإعدادات تخص مؤسستك وليست تفضيلات شخصية.</p></div><span class="settings-pill">${isAdmin ? 'إدارة' : 'قراءة فقط'}</span></div>
      <form id="orgForm" class="settings-form-v2"><div class="form-grid"><div class="field full"><label for="settingsOrgName">اسم مساحة العمل</label><input id="settingsOrgName" name="name" value="${esc(organization?.name || currentUser?.organization_name || '')}" required minlength="2" maxlength="160" ${isAdmin ? '' : 'disabled'}></div><div class="field full"><label for="settingsTimezone">المنطقة الزمنية</label><select id="settingsTimezone" name="timezone" ${isAdmin ? '' : 'disabled'}>${[['Asia/Hebron','فلسطين — Asia/Hebron'],['Asia/Jerusalem','القدس — Asia/Jerusalem'],['UTC','UTC'],['Europe/London','London'],['America/New_York','New York']].map(([v,l])=>`<option value="${v}" ${(organization?.timezone || 'Asia/Hebron') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div></div>${isAdmin ? '<button class="btn btn-primary" type="submit">حفظ مساحة العمل</button>' : '<p class="help">تحتاج إلى صلاحية مالك أو مدير لتعديل مساحة العمل.</p>'}</form></section>`;
  } else if (midarSettingsTab === 'integrations') {
    const rows = (catalog.providers || []).filter(p => p.platform !== 'Other').map(p => {
      const health = (integrationStatus?.providers || []).find(x => x.platform === p.platform);
      const live = p.implementation_status === 'implemented';
      const partial = p.implementation_status === 'partial';
      const label = partial ? 'موصل جزئي' : live ? 'منفذ' : 'قيد التطوير';
      const stateClass = partial ? 'settings-pill settings-pill-warn' : live ? 'settings-pill settings-pill-good' : 'settings-pill';
      const caps = [...(p.implemented_capabilities || []).map(x => ({name:x,live:true})), ...(p.planned_capabilities || []).map(x => ({name:x,live:false}))].slice(0,5);
      return `<article class="settings-provider"><div class="settings-provider-head"><div class="provider-orb provider-${esc(String(p.platform).toLowerCase().replace(/[^a-z]/g,''))}">${esc(({Facebook:'f',Instagram:'◎',WhatsApp:'◉',Telegram:'➤',X:'𝕏',YouTube:'▶',TikTok:'♪',LinkedIn:'in'})[p.platform] || '•')}</div><div class="settings-provider-title"><b>${esc(p.platform)}</b><small>${esc(p.method || '')}</small></div><span class="${stateClass}">${label}</span></div><p>${esc(p.description_ar || '')}</p><div class="settings-capabilities">${caps.map(c=>`<span class="${c.live?'live':''}">${c.live?'✓':'＋'} ${esc(c.name.replaceAll('_',' '))}</span>`).join('')}</div><div class="settings-provider-foot"><small>${esc(health?.status ? ({not_configured:'لم يُهيأ',configured_channel_verification_required:'يتطلب التحقق من القناة',credentials_present_flow_pending:'البيانات موجودة لكن التدفق غير مكتمل'}[health.status] || health.status) : 'يلزم إعداد وتحقق مستقل')}</small>${p.docs_url ? `<a href="${esc(p.docs_url)}" target="_blank" rel="noopener noreferrer">الوثائق الرسمية ↗</a>` : ''}</div><p class="settings-provider-limit">${esc(p.limitations_ar || '')}</p></article>`;
    }).join('');
    panel = `<section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">CONNECTORS</span><h3>التكاملات الاجتماعية</h3><p>حالة كل منصة كما يعرفها الكود الحالي. تسجيل المنصة لا يعني اتصال حساب حقيقي.</p></div></div><div class="settings-provider-grid">${rows || '<p class="help">كتالوج التكاملات غير متاح لهذا الدور أو تعذر تحميله.</p>'}</div><div class="settings-note"><b>القاعدة المعتمدة</b><p>لا تظهر أي منصة على أنها متصلة إلا بعد تنفيذ OAuth أو API والتحقق من الحساب المستهدف. حاليًا Telegram هو الموصل الخارجي الجزئي، ويقتصر على التحقق من الوجهة ونشر النص يدويًا عند إعداد الرمز.</p></div></section>`;
  } else {
    panel = `<section class="settings-panel-v2"><div class="settings-panel-heading"><div><span class="settings-kicker">SECURITY</span><h3>الأمان وتسجيل الدخول</h3><p>تحكم في كلمة المرور والجلسة الحالية وربط هويتك الخارجية.</p></div><span class="settings-pill settings-pill-good">اتصال محلي</span></div><div class="settings-action-row"><div><b>كلمة المرور</b><small>استخدم كلمة مرور طويلة وفريدة، ولا تشاركها مع أحد.</small></div><button type="button" class="btn" data-action="password-change">تغيير كلمة المرور</button></div><div class="settings-action-row"><div><b>حساب Google</b><small>${googleStatus.linked ? `مرتبط: ${esc(googleStatus.email || 'حساب Google')}` : 'غير مرتبط؛ اربطه من قسم حسابي الشخصي بعد إعداد OAuth.'}</small></div><button type="button" class="btn" data-settings-tab="profile">إدارة الربط</button></div><div class="settings-action-row"><div><b>تسجيل الخروج</b><small>ينهي جلسة M الحالية على هذا المتصفح.</small></div><button type="button" class="btn btn-danger" id="settingsLogoutBtn">تسجيل الخروج</button></div><div class="settings-note"><b>تنبيه الجاهزية</b><p>هذه النسخة تعمل محليًا. قبل النشر العام يلزم HTTPS، ومراجعة تخزين الجلسات، ومراقبة الدخول، واختبار الاستعادة والنسخ الاحتياطي.</p></div></section>`;
  }

  $('#pageContent').innerHTML = `${pageHead('الإعدادات والتخصيص','إدارة الحساب، المظهر، مساحة العمل، التكاملات، والأمان')}<div class="settings-layout-v2"><nav class="settings-nav-v2" aria-label="أقسام الإعدادات">${tabNav}<div class="settings-nav-footer"><span class="settings-live-dot"></span><span>تفضيلات الحساب تحفظ على الخادم</span></div></nav><div class="settings-main-v2">${panel}</div></div>`;
}

async function startGoogleLogin(button) {
  if (!button || button.disabled) return;
  button.disabled = true;
  const previous = button.innerHTML;
  button.innerHTML = '<span>جارٍ الاتصال بـ Google…</span>';
  try {
    const out = await api('/auth/google/login-url', { method: 'POST' });
    if (!out.authorization_url || !out.authorization_url.startsWith('https://accounts.google.com/')) throw new Error('أعاد الخادم رابط تفويض غير متوقع.');
    window.location.assign(out.authorization_url);
  } catch (err) {
    showGoogleAuthNotice(err.message?.includes('غير مهيأ') ? 'not_configured' : 'exchange_failed');
    button.disabled = false;
    button.innerHTML = previous;
  }
}

async function startGoogleLink(button) {
  if (!button || button.disabled) return;
  button.disabled = true;
  try {
    const out = await api('/auth/google/link-url', { method: 'POST' });
    if (!out.authorization_url || !out.authorization_url.startsWith('https://accounts.google.com/')) throw new Error('أعاد الخادم رابط تفويض غير متوقع.');
    window.location.assign(out.authorization_url);
  } catch (err) {
    toast(err.message || 'تعذر بدء ربط Google');
    button.disabled = false;
  }
}

document.addEventListener('click', event => {
  const loginButton = event.target.closest('#googleLoginBtn');
  if (loginButton) { startGoogleLogin(loginButton); return; }
  const linkButton = event.target.closest('[data-google-link]');
  if (linkButton) { startGoogleLink(linkButton); return; }
  const tabButton = event.target.closest('[data-settings-tab]');
  if (tabButton) {
    const target = tabButton.dataset.settingsTab;
    if (['profile','appearance','workspace','integrations','security'].includes(target)) {
      midarSettingsTab = target;
      loadPage('settings');
    }
    return;
  }
  if (event.target.closest('#settingsLogoutBtn')) performLogout();
});

document.addEventListener('change', event => {
  if (!event.target.closest('#appearanceForm')) return;
  const form = document.querySelector('#appearanceForm');
  if (!form) return;
  applyAppearancePrefs({
    theme_mode: new FormData(form).get('theme_mode') || midarSavedPreferences.theme_mode,
    accent_color: new FormData(form).get('accent_color') || midarSavedPreferences.accent_color,
    density: new FormData(form).get('density') || midarSavedPreferences.density,
  });
  document.querySelectorAll('.accent-choice').forEach(el => el.classList.toggle('selected', !!el.querySelector('input:checked')));
});

document.addEventListener('submit', async event => {
  const form = event.target;
  if (!['settingsProfileForm', 'appearanceForm'].includes(form?.id)) return;
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  if (submit) { submit.disabled = true; submit.dataset.previousText = submit.textContent; submit.textContent = 'جارٍ الحفظ…'; }
  try {
    const data = new FormData(form);
    if (form.id === 'settingsProfileForm') {
      const user = await api('/auth/profile', { method: 'PATCH', body: JSON.stringify({ full_name: String(data.get('full_name') || '').trim() }) });
      currentUser = user;
      $('#profileName').textContent = user.full_name;
      $('#topUser').textContent = user.full_name;
      const initials = user.full_name.trim().split(/\s+/).slice(0,2).map(x => x[0]).join('');
      $('#profileAvatar').textContent = initials;
      $('#topAvatar').textContent = initials;
      toast('تم حفظ بيانات الحساب');
    } else {
      const prefs = await api('/preferences', { method: 'PATCH', body: JSON.stringify({
        theme_mode: data.get('theme_mode'), accent_color: data.get('accent_color'), density: data.get('density')
      }) });
      applyAppearancePrefs(prefs);
      toast('تم حفظ المظهر وتفضيلات العرض');
    }
    await renderEnhancedSettings();
  } catch (err) {
    toast(err.message || 'تعذر حفظ الإعدادات');
  } finally {
    if (submit && submit.isConnected) { submit.disabled = false; submit.textContent = submit.dataset.previousText || 'حفظ'; }
  }
});

// Respect OS appearance changes only when the saved choice is "system".
/* MIDAR_SYSTEM_THEME_LISTENER */
if (window.matchMedia) {
  const systemThemeQuery = window.matchMedia('(prefers-color-scheme: light)');
  systemThemeQuery.addEventListener?.('change', () => {
    if (midarSavedPreferences.theme_mode === 'system') applyAppearancePrefs(midarSavedPreferences);
  });
}
