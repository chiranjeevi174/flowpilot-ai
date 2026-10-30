const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

async function captureAll() {
  const outputDir = path.resolve(__dirname, '../../docs/screenshots_staging');
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });

  // 1. Desktop Context
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  console.log('1. Logging in as operator@flowpilot.ai...');
  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
  await page.getByLabel(/Email Address/i).fill('operator@flowpilot.ai');
  await page.getByLabel(/Password/i).fill('Password123!');
  await page.getByRole('button', { name: /Sign In/i }).click();

  await page.waitForURL('**/dashboard', { timeout: 15000 });
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(2000);

  // Helper to ensure clean UI without floating popovers/toasts covering content
  const applyCleanStyle = async () => {
    await page.addStyleTag({
      content: `
        [data-sonner-toaster],
        aside[aria-label="Live workflow notifications"] {
          display: none !important;
        }
      `,
    });
  };

  // --- Screenshot 1: Operations Dashboard ---
  console.log('Capturing Screenshot 1: dashboard.png...');
  await page.goto('http://localhost:3000/dashboard', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'dashboard.png') });

  // --- Screenshot 2: Workflow Creation ---
  console.log('Capturing Screenshot 2: workflow-creation.png...');
  await page.goto('http://localhost:3000/workflows', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  const starterBtn = page.getByText('Weekly Ops Briefing', { exact: true });
  if (await starterBtn.isVisible()) {
    await starterBtn.click();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: path.join(outputDir, 'workflow-creation.png') });

  // --- Screenshot 3: Workflow Execution ---
  console.log('Capturing Screenshot 3: workflow-execution.png...');
  await page.goto('http://localhost:3000/executions/6fc5ff7f-e3a7-4648-ba3c-9a1746e31b84', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'workflow-execution.png') });

  // --- Screenshot 4: Human Approvals ---
  console.log('Capturing Screenshot 4: approvals.png...');
  await page.goto('http://localhost:3000/approvals', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'approvals.png') });

  // --- Screenshot 5: Smart Scheduling ---
  console.log('Capturing Screenshot 5: scheduling.png...');
  await page.goto('http://localhost:3000/schedules', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'scheduling.png') });

  // --- Screenshot 6: Multi-LLM BYOK ---
  console.log('Capturing Screenshot 6: multi-llm-byok.png...');
  await page.goto('http://localhost:3000/settings/llm', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'multi-llm-byok.png') });

  // Optional 6b: Available Models Expanded
  console.log('Capturing Screenshot 6b: multi-llm-models.png...');
  const modelsSectionBtn = page.getByRole('button', { name: /Available Models/i });
  if (await modelsSectionBtn.isVisible()) {
    await modelsSectionBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outputDir, 'multi-llm-models.png') });
  }

  // --- Screenshot 7: App Connections ---
  console.log('Capturing Screenshot 7: app-connections.png...');
  await page.goto('http://localhost:3000/settings/connections', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'app-connections.png') });

  // Optional 7b: App Connections Setup Guide
  console.log('Capturing Screenshot 7b: app-connections-setup.png...');
  const setupGuideBtn = page.getByRole('button', { name: /Setup Guide/i }).first();
  if (await setupGuideBtn.isVisible()) {
    await setupGuideBtn.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outputDir, 'app-connections-setup.png') });
    const closeBtn = page.getByRole('button', { name: /Close/i });
    if (await closeBtn.isVisible()) {
      await closeBtn.click();
      await page.waitForTimeout(400);
    }
  }

  // --- Screenshot 8: Notification Center ---
  console.log('Capturing Screenshot 8: notifications.png...');
  await page.goto('http://localhost:3000/dashboard', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  const notifBell = page.locator('button[aria-label="View notifications"]');
  if (await notifBell.isVisible()) {
    await notifBell.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(outputDir, 'notifications.png') });
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }

  // --- Screenshot 9: Integrations Monitoring ---
  console.log('Capturing Screenshot 9: integrations.png...');
  await page.goto('http://localhost:3000/integrations', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'integrations.png') });

  // --- Screenshot 10: Account Profile ---
  console.log('Capturing Screenshot 10: account-profile.png...');
  await page.goto('http://localhost:3000/settings/profile', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await applyCleanStyle();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(outputDir, 'account-profile.png') });

  await context.close();

  // --- Screenshot 11: Responsive Dashboard (Mobile 390x844) ---
  console.log('Capturing Screenshot 11: responsive-dashboard.png...');
  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    isMobile: true,
  });
  const mobilePage = await mobileContext.newPage();
  await mobilePage.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
  await mobilePage.getByLabel(/Email Address/i).fill('operator@flowpilot.ai');
  await mobilePage.getByLabel(/Password/i).fill('Password123!');
  await mobilePage.getByRole('button', { name: /Sign In/i }).click();
  await mobilePage.waitForURL('**/dashboard', { timeout: 15000 });
  await mobilePage.waitForLoadState('networkidle');
  await mobilePage.waitForTimeout(1000);
  await mobilePage.addStyleTag({
    content: `
      [data-sonner-toaster],
      aside[aria-label="Live workflow notifications"] {
        display: none !important;
      }
    `,
  });
  await mobilePage.waitForTimeout(500);
  await mobilePage.screenshot({ path: path.join(outputDir, 'responsive-dashboard.png') });
  await mobileContext.close();

  await browser.close();
  console.log('All screenshots captured cleanly in:', outputDir);
}

captureAll().catch((err) => {
  console.error('Error during capture:', err);
  process.exit(1);
});
