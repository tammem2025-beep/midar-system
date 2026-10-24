/* M Command Center 0.9.0 — fast, keyboard-accessible navigation with no external dependencies. */
(() => {
  'use strict';
  if (window.__midarCommandCenterReady) return;
  window.__midarCommandCenterReady = true;

  const commands = [
    { id:'dashboard', group:'التنقل', title:'لوحة التحكم', detail:'نظرة شاملة على نشاط مساحة العمل', icon:'⌂', page:'dashboard', keywords:'الرئيسية مؤشرات أداء dashboard home' },
    { id:'posts', group:'التنقل', title:'المحتوى والمنشورات', detail:'المسودات، حالات النشر وتقويم المحتوى', icon:'▤', page:'posts', keywords:'منشورات محتوى كتابة publication calendar' },
    { id:'studio', group:'الإنشاء', title:'استوديو الفيديو القصير', detail:'مسودات الفيديو والمعاينة العمودية', icon:'▶', page:'studio', keywords:'ريلز reels shorts tiktok video فيديو' },
    { id:'new-post', group:'الإنشاء', title:'إنشاء منشور جديد', detail:'ابدأ مسودة محتوى جديدة', icon:'＋', page:'posts', action:'new-post', keywords:'إضافة منشور محتوى' },
    { id:'new-video', group:'الإنشاء', title:'إنشاء مسودة فيديو', detail:'أضف فيديو إلى استوديو المنشئ', icon:'▣', page:'studio', action:'new-video-draft', keywords:'فيديو ريلز shorts reels' },
    { id:'campaigns', group:'التنقل', title:'الحملات التسويقية', detail:'الخطط والأهداف والميزانيات', icon:'◈', page:'campaigns', keywords:'حملة تسويق إعلانات campaign' },
    { id:'inbox', group:'التنقل', title:'صندوق الرسائل', detail:'إدارة سجل المحادثات المتاح في النظام', icon:'✉', page:'inbox', keywords:'رسائل محادثات بريد inbox messages' },
    { id:'contacts', group:'التنقل', title:'العملاء والمبيعات', detail:'ملفات العملاء ومراحل المتابعة', icon:'♙', page:'contacts', keywords:'crm عميل lead sales' },
    { id:'new-contact', group:'الإنشاء', title:'إضافة عميل', detail:'أنشئ ملف عميل أو جهة اتصال', icon:'＋', page:'contacts', action:'new-contact', keywords:'عميل جهة اتصال lead contact' },
    { id:'tasks', group:'التنقل', title:'المهام والعمليات', detail:'أعمال الفريق والمواعيد', icon:'☑', page:'tasks', keywords:'مهمة tasks follow up' },
    { id:'new-task', group:'الإنشاء', title:'إنشاء مهمة', detail:'أضف متابعة أو إجراءً للفريق', icon:'＋', page:'tasks', action:'new-task', keywords:'مهمة جديدة task' },
    { id:'accounts', group:'التنقل', title:'الحسابات الاجتماعية', detail:'حالة الربط والقدرات المتاحة لكل منصة', icon:'◎', page:'accounts', keywords:'facebook instagram whatsapp telegram x حساب' },
    { id:'media', group:'التنقل', title:'مكتبة الوسائط', detail:'الصور والفيديو والملفات المرفوعة', icon:'▧', page:'media', keywords:'ملفات صور فيديو assets upload' },
    { id:'team', group:'الإدارة', title:'إدارة الفريق', detail:'الأعضاء والأدوار والصلاحيات', icon:'♧', page:'team', keywords:'موظفين اعضاء صلاحيات team members' },
    { id:'settings', group:'الإدارة', title:'الإعدادات العامة', detail:'الملف الشخصي ومساحة العمل والأمان', icon:'⚙', page:'settings', keywords:'إعداد ضبط settings preferences profile' },
    { id:'appearance', group:'التخصيص', title:'المظهر والألوان', detail:'السمة والألوان وكثافة العرض', icon:'◐', page:'settings', tab:'appearance', keywords:'لون ثيم مظهر dark light accent theme' },
    { id:'integrations', group:'الإدارة', title:'التكاملات الاجتماعية', detail:'حالة التكاملات والوثائق الرسمية', icon:'⛓', page:'settings', tab:'integrations', keywords:'oauth api google provider social integrations' },
    { id:'security', group:'الإدارة', title:'الأمان وتسجيل الدخول', detail:'كلمة المرور والجلسة وإعدادات الهوية', icon:'⛨', page:'settings', tab:'security', keywords:'كلمة مرور password google login security' },
    { id:'audit', group:'الإدارة', title:'سجل النشاط', detail:'مراجعة العمليات المسجلة داخل مساحة العمل', icon:'◷', page:'audit', keywords:'سجل التدقيق logs audit' },
  ];

  let activeIndex = 0;
  let visible = [];
  let previousFocus = null;
  let overlay;
  let searchInput;
  let list;
  let trigger;

  function makeButton(label, className, html) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.setAttribute('aria-label', label);
    if (html) button.innerHTML = html;
    return button;
  }

  function build() {
    const topbar = document.querySelector('.topbar');
    if (!topbar || document.getElementById('xpCommandRoot')) return;

    trigger = makeButton('فتح مركز الأوامر — Ctrl+K', 'command-launcher', '<span class="command-launcher-icon" aria-hidden="true">⌕</span><span>انتقال سريع</span><kbd>Ctrl K</kbd>');
    trigger.id = 'xpCommandTrigger';
    trigger.addEventListener('click', open);
    const anchor = topbar.querySelector('.account-menu-wrap');
    if (anchor) topbar.insertBefore(trigger, anchor);
    else topbar.appendChild(trigger);

    overlay = document.createElement('div');
    overlay.id = 'xpCommandRoot';
    overlay.className = 'xp-command-root';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="xp-command-backdrop" data-xp-command-close></div>
      <section class="xp-command-dialog" role="dialog" aria-modal="true" aria-labelledby="xpCommandTitle">
        <div class="xp-command-search"><span class="xp-command-search-icon" aria-hidden="true">⌕</span><label id="xpCommandTitle" class="hidden" for="xpCommandInput">مركز أوامر M</label><input id="xpCommandInput" type="search" autocomplete="off" placeholder="ابحث عن صفحة أو إجراء…" aria-controls="xpCommandList" aria-label="ابحث عن صفحة أو إجراء"><kbd>ESC</kbd></div>
        <div id="xpCommandList" class="xp-command-list" role="listbox" aria-label="الأوامر المتاحة"></div>
        <div class="xp-command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> للتنقل</span><span><kbd>Enter</kbd> للتنفيذ</span><span>M · مركز الأوامر</span></div>
      </section>`;
    document.body.appendChild(overlay);
    searchInput = overlay.querySelector('#xpCommandInput');
    list = overlay.querySelector('#xpCommandList');
    searchInput.addEventListener('input', () => { activeIndex = 0; renderList(); });
    searchInput.addEventListener('keydown', onSearchKeydown);
    overlay.addEventListener('click', event => {
      if (event.target.closest('[data-xp-command-close]')) close();
      const item = event.target.closest('[data-xp-command-index]');
      if (item) runCommand(Number(item.dataset.xpCommandIndex));
    });
    renderList();
  }

  function isPageAvailable(page) {
    const nav = document.querySelector(`.sidebar .nav button[data-page="${page}"]`);
    return !!nav && !nav.classList.contains('hidden');
  }

  function renderList() {
    if (!list || !searchInput) return;
    const query = searchInput.value.trim().toLocaleLowerCase('ar');
    visible = commands.filter(command => {
      if (!isPageAvailable(command.page)) return false;
      const haystack = `${command.title} ${command.detail} ${command.group} ${command.keywords || ''}`.toLocaleLowerCase('ar');
      return !query || haystack.includes(query);
    });
    if (activeIndex >= visible.length) activeIndex = Math.max(0, visible.length - 1);
    list.replaceChildren();
    if (!visible.length) {
      const empty = document.createElement('div');
      empty.className = 'xp-command-empty';
      empty.textContent = 'لا توجد نتائج مطابقة. جرّب كلمة أخرى.';
      list.appendChild(empty);
      return;
    }
    let priorGroup = '';
    visible.forEach((command, index) => {
      if (command.group !== priorGroup) {
        priorGroup = command.group;
        const heading = document.createElement('div');
        heading.className = 'xp-command-group';
        heading.textContent = priorGroup;
        list.appendChild(heading);
      }
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'xp-command-item';
      item.dataset.xpCommandIndex = String(index);
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', index === activeIndex ? 'true' : 'false');
      const icon = document.createElement('span');
      icon.className = 'xp-command-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = command.icon;
      const copy = document.createElement('span');
      copy.className = 'xp-command-copy';
      const title = document.createElement('b');
      title.textContent = command.title;
      const detail = document.createElement('small');
      detail.textContent = command.detail;
      copy.append(title, detail);
      const arrow = document.createElement('span');
      arrow.className = 'xp-command-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '↵';
      item.append(icon, copy, arrow);
      list.appendChild(item);
    });
  }

  function open() {
    if (!overlay) return;
    previousFocus = document.activeElement;
    overlay.hidden = false;
    searchInput.value = '';
    activeIndex = 0;
    renderList();
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => searchInput.focus());
  }

  function close() {
    if (!overlay || overlay.hidden) return;
    overlay.hidden = true;
    document.body.style.overflow = '';
    if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
  }

  function onSearchKeydown(event) {
    if (event.key === 'ArrowDown') { event.preventDefault(); activeIndex = Math.min(activeIndex + 1, Math.max(0, visible.length - 1)); renderList(); list.querySelector(`[data-xp-command-index="${activeIndex}"]`)?.scrollIntoView({ block: 'nearest' }); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); activeIndex = Math.max(0, activeIndex - 1); renderList(); list.querySelector(`[data-xp-command-index="${activeIndex}"]`)?.scrollIntoView({ block: 'nearest' }); }
    else if (event.key === 'Enter') { event.preventDefault(); if (visible.length) runCommand(activeIndex); }
    else if (event.key === 'Escape') { event.preventDefault(); close(); }
    else if (event.key === 'Tab') {
      event.preventDefault();
      const dialogButtons = overlay.querySelectorAll('button:not([disabled])');
      if (dialogButtons.length) dialogButtons[0].focus();
    }
  }

  function waitFor(predicate, timeout = 5000) {
    const started = Date.now();
    return new Promise(resolve => {
      const check = () => {
        const value = predicate();
        if (value || Date.now() - started >= timeout) resolve(value || null);
        else setTimeout(check, 80);
      };
      check();
    });
  }

  async function runCommand(index) {
    const command = visible[index];
    if (!command) return;
    close();
    const nav = document.querySelector(`.sidebar .nav button[data-page="${command.page}"]`);
    if (!nav || nav.classList.contains('hidden')) return;
    nav.click();
    if (command.tab) {
      const tab = await waitFor(() => document.querySelector(`[data-settings-tab="${command.tab}"]`), 6000);
      if (tab) tab.click();
      return;
    }
    if (command.action) {
      const target = await waitFor(() => document.querySelector(`#pageContent [data-action="${command.action}"]`), 6000);
      if (target) target.click();
      else if (typeof window.toast === 'function') window.toast('تعذر فتح الإجراء المطلوب. افتح الصفحة وحاول مرة أخرى.');
    }
  }

  // All sidebar sections now live inside #nav; app.js owns route and active-state handling.

  document.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === 'k') {
      event.preventDefault();
      if (overlay && !overlay.hidden) close(); else open();
    } else if (event.key === 'Escape' && overlay && !overlay.hidden) close();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', build, { once: true });
  else build();
})();
