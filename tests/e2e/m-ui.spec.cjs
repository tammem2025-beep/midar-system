const { test, expect } = require('@playwright/test');

test('M first-run setup, single create action, bilingual shell, theme and mobile layout', async ({ page }, testInfo) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.goto('/');
  await expect(page.locator('#authScreen')).toBeVisible();
  await expect(page.locator('#languageToggleAuthBtn')).toBeVisible();

  await page.locator('#languageToggleAuthBtn').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.locator('#authTitle')).toHaveText('Set up your workspace');
  await page.locator('#languageToggleAuthBtn').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');

  await page.locator('#setupName').fill('M Test Owner');
  await page.locator('#setupOrganization').fill('M E2E Workspace');
  await page.locator('#authEmail').fill('m-e2e-owner@example.com');
  await page.locator('#authPassword').fill('Secure-E2E-Password-123!');
  await page.locator('#authSubmit').click();

  await expect(page.locator('.dashboard-v2')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('#globalCreatePostBtn')).toBeVisible();
  await expect(page.locator('.dc-quick')).toHaveCount(0);
  await expect(page.locator('.dc-header-actions')).toHaveCount(0);
  await expect(page.locator('#accountSettingsBtn')).toHaveCount(0);

  await testInfo.attach('dashboard-desktop-ar', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  await page.locator('#accountMenuBtn').click();
  await page.locator('#languageToggleBtn').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expect(page.locator('#nav [data-page="dashboard"] .nav-text')).toHaveText('Dashboard');
  await expect(page.locator('#globalCreatePostBtn')).toContainText('Create');
  await testInfo.attach('dashboard-desktop-en', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  await page.locator('#languageToggleBtn').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  // Verify keyboard-only operation and focus restoration for the account dropdown.
  await page.locator('#accountMenuBtn').click();
  await page.locator('#accountMenuBtn').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#accountMenuBtn')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('#languageToggleBtn')).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.locator('#accountLogoutBtn')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('#accountMenu')).toBeHidden();
  await expect(page.locator('#accountMenuBtn')).toBeFocused();

  // Social platforms are opened from their in-page cards, not a duplicate top link strip.
  await page.locator('#nav [data-page="accounts"]').click();
  await expect(page.locator('.provider-grid')).toBeVisible();
  await expect(page.locator('.provider-launchpad')).toHaveCount(0);
  await expect(page.locator('[data-open-provider="Facebook"]')).toBeVisible();
  await expect(page.locator('[data-open-provider="Telegram"]')).toBeVisible();
  await page.locator('#nav [data-page="dashboard"]').click();

  await page.locator('#nav [data-page="settings"]').click();
  await expect(page.locator('.settings-layout-v2')).toBeVisible();
  await page.locator('.settings-nav-v2 [data-settings-tab="appearance"]').click();
  await expect(page.locator('#appearanceForm')).toBeVisible();
  await page.locator('.theme-choice-grid label.settings-choice').nth(1).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.locator('#appearanceForm button[type="submit"]').click();

  await page.locator('#nav [data-page="dashboard"]').click();
  await expect(page.locator('.dashboard-v2')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  const horizontalOverflow = await page.evaluate(
    () => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth
  );
  expect(horizontalOverflow).toBeLessThanOrEqual(2);
  await testInfo.attach('dashboard-mobile-390-ar', {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });

  expect(pageErrors, 'Unexpected browser errors: ' + pageErrors.join('\n')).toEqual([]);
});
