const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

async function captureScreenshots() {
  const outputDirDocs = path.resolve(__dirname, '../../docs/screenshots');
  const outputDirArtifacts = process.env.ARTIFACTS_DIR || null;
  const testUserEmail = process.env.TEST_USER_EMAIL || 'operator@flowpilot.ai';

  if (!fs.existsSync(outputDirDocs)) {
    fs.mkdirSync(outputDirDocs, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });

  const viewports = [
    { name: 'desktop-1440', width: 1440, height: 900, isMobile: false },
    { name: 'tablet-768', width: 768, height: 1024, isMobile: false },
    { name: 'mobile-390', width: 390, height: 844, isMobile: true },
  ];

  for (const vp of viewports) {
    console.log(`\n--- Capturing for ${vp.name} (${vp.width}x${vp.height}) ---`);
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 1,
      isMobile: vp.isMobile,
    });
    const page = await context.newPage();

    // Authenticate with test user account
    await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle' });
    const devLoginRes = await page.request.post('http://localhost:3000/api/auth/dev-login', {
      data: { email: testUserEmail },
    });
    if (!devLoginRes.ok()) {
      throw new Error(`Dev login failed: ${devLoginRes.status()}`);
    }

    // Clean styles to remove toaster / floating notifications that might obscure cards
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

    // 1. External Integrations Page (/integrations)
    console.log(`Navigating to /integrations (${vp.name})...`);
    await page.goto('http://localhost:3000/integrations', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await applyCleanStyle();
    await page.waitForTimeout(500);

    const intFilename = `integrations-${vp.name}.png`;
    const intDocsPath = path.join(outputDirDocs, intFilename);

    await page.screenshot({ path: intDocsPath, fullPage: false });
    if (outputDirArtifacts && fs.existsSync(outputDirArtifacts)) {
      fs.copyFileSync(intDocsPath, path.join(outputDirArtifacts, intFilename));
    }
    console.log(`Saved: ${intDocsPath}`);

    // 2. App Connections Page (/settings/connections)
    console.log(`Navigating to /settings/connections (${vp.name})...`);
    await page.goto('http://localhost:3000/settings/connections', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await applyCleanStyle();
    await page.waitForTimeout(500);

    const connFilename = `connections-${vp.name}.png`;
    const connDocsPath = path.join(outputDirDocs, connFilename);

    await page.screenshot({ path: connDocsPath, fullPage: false });
    if (outputDirArtifacts && fs.existsSync(outputDirArtifacts)) {
      fs.copyFileSync(connDocsPath, path.join(outputDirArtifacts, connFilename));
    }
    console.log(`Saved: ${connDocsPath}`);

    await context.close();
  }

  await browser.close();
  console.log('\nAll 6 responsive screenshots captured successfully!');
}

captureScreenshots().catch((err) => {
  console.error('Screenshot capture failed:', err);
  process.exit(1);
});
