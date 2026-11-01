import { test, expect } from "@playwright/test";

const TARGET_USER = process.env.TEST_USER_EMAIL || "operator@flowpilot.ai";

test.describe("FlowPilot AI — Integration Status Consistency & Responsive Cards", () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate via dev-login as the user with active Google & WhatsApp connections
    await page.goto("/login");
    const loginRes = await page.request.post("/api/auth/dev-login", {
      data: { email: TARGET_USER },
    });
    expect(loginRes.ok()).toBeTruthy();
    // Navigate to dashboard to ensure session cookie is established
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
  });

  test("Issue 1: Consistent Google Sheets & Provider Status across both pages", async ({ page }) => {
    // 1. Visit External Integrations (/integrations)
    await page.goto("/integrations");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "External Integrations & Business Channels" })).toBeVisible();

    // Verify Google Sheets card displays "Connected"
    const sheetsCardIntegrations = page.locator(".grid > div").filter({ hasText: "Google Sheets" }).first();
    await expect(sheetsCardIntegrations).toBeVisible();
    await expect(sheetsCardIntegrations.getByText("Connected", { exact: true })).toBeVisible();

    // Verify Gmail card displays "Connected"
    const gmailCardIntegrations = page.locator(".grid > div").filter({ hasText: "Google (Gmail)" }).first();
    await expect(gmailCardIntegrations).toBeVisible();
    await expect(gmailCardIntegrations.getByText("Connected", { exact: true })).toBeVisible();

    // Verify WhatsApp card displays user-owned Connection Error
    const waCardIntegrations = page.locator(".grid > div").filter({ hasText: "WhatsApp Business" }).first();
    await expect(waCardIntegrations).toBeVisible();
    await expect(waCardIntegrations.getByText("Connection Error", { exact: true })).toBeVisible();

    // 2. Visit App Connections (/settings/connections)
    await page.goto("/settings/connections");
    await page.waitForLoadState("networkidle");

    await expect(page.getByRole("heading", { name: "App Connections" })).toBeVisible();

    // Verify Google Sheets card also displays "Connected"
    const sheetsCardConnections = page.locator(".grid > div").filter({ hasText: "Google Sheets" }).first();
    await expect(sheetsCardConnections).toBeVisible();
    await expect(sheetsCardConnections.getByText("Connected", { exact: true })).toBeVisible();

    // Verify Gmail card displays "Connected"
    const gmailCardConnections = page.locator(".grid > div").filter({ hasText: "Gmail" }).first();
    await expect(gmailCardConnections).toBeVisible();
    await expect(gmailCardConnections.getByText("Connected", { exact: true })).toBeVisible();

    // Verify Slack card displays "Connected"
    const slackCardConnections = page.locator(".grid > div").filter({ hasText: "Slack" }).first();
    await expect(slackCardConnections).toBeVisible();
    await expect(slackCardConnections.getByText("Connected", { exact: true })).toBeVisible();

    // Verify WhatsApp card displays "Connection Error" on connections page as well
    const waCardConnections = page.locator(".grid > div").filter({ hasText: "WhatsApp Business" }).first();
    await expect(waCardConnections).toBeVisible();
    await expect(waCardConnections.getByText("Connection Error", { exact: true })).toBeVisible();
  });

  test("Issue 2: Responsive layout integrity and badge boundaries at desktop (1440px), tablet (768px), and mobile (390px)", async ({ page }) => {
    const viewports = [
      { name: "desktop", width: 1440, height: 900 },
      { name: "tablet", width: 768, height: 1024 },
      { name: "mobile", width: 390, height: 844 },
    ];

    for (const vp of viewports) {
      await page.setViewportSize({ width: vp.width, height: vp.height });

      // Check /settings/connections
      await page.goto("/settings/connections");
      await page.waitForLoadState("networkidle");

      const cards = page.locator(".grid > div");
      const count = await cards.count();
      expect(count).toBeGreaterThanOrEqual(4);

      for (let i = 0; i < count; i++) {
        const card = cards.nth(i);
        const cardBox = await card.boundingBox();
        expect(cardBox).not.toBeNull();

        // Verify status badge is within card boundaries
        const badge = card.locator('[data-testid^="status-badge-"]').first();
        if (await badge.isVisible()) {
          const badgeBox = await badge.boundingBox();
          expect(badgeBox).not.toBeNull();
          if (cardBox && badgeBox) {
            // Badge should be horizontally inside the card
            expect(badgeBox.x).toBeGreaterThanOrEqual(cardBox.x - 2);
            expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 5);
          }
        }
      }

      // Check /integrations
      await page.goto("/integrations");
      await page.waitForLoadState("networkidle");

      const intCards = page.locator(".grid > div");
      const intCount = await intCards.count();
      expect(intCount).toBeGreaterThanOrEqual(4);

      for (let i = 0; i < intCount; i++) {
        const card = intCards.nth(i);
        const cardBox = await card.boundingBox();
        expect(cardBox).not.toBeNull();

        const badge = card.locator('[data-testid^="status-badge-"]').first();
        if (await badge.isVisible()) {
          const badgeBox = await badge.boundingBox();
          expect(badgeBox).not.toBeNull();
          if (cardBox && badgeBox) {
            expect(badgeBox.x).toBeGreaterThanOrEqual(cardBox.x - 2);
            expect(badgeBox.x + badgeBox.width).toBeLessThanOrEqual(cardBox.x + cardBox.width + 5);
          }
        }
      }
    }
  });

  test("Cache synchronization & query invalidation on refresh", async ({ page }) => {
    await page.goto("/settings/connections");
    await page.waitForLoadState("networkidle");

    const refreshButton = page.getByRole("button", { name: /Refresh/i });
    await expect(refreshButton).toBeVisible();

    // Clicking Refresh should trigger reload of overview
    const [response] = await Promise.all([
      page.waitForResponse((res) => res.url().includes("/connections/overview") || res.url().includes("/integrations")),
      refreshButton.click(),
    ]);

    expect(response.status()).toBe(200);
  });
});
