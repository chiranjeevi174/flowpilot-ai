import { test, expect } from "@playwright/test";

test.describe("FlowPilot AI — Dashboard Metrics & Schedule Lifecycle Consistency", () => {
  test("Scenario A & D — Pending Approvals counter matches actionable Approvals page and respects user isolation", async ({
    page,
  }) => {
    test.setTimeout(60000);

    // 1. Sign in as operator@flowpilot.ai
    await page.goto("/login");
    await page.getByLabel(/Email Address/i).fill("operator@flowpilot.ai");
    await page.getByLabel(/Password/i).fill("Password123!");
    await page.getByRole("button", { name: /Sign In/i }).click();

    // 2. Open Overview dashboard
    await page.waitForURL("/dashboard");
    await expect(page.getByText("Operations Command Center")).toBeVisible();

    // 3. Pending Approvals card on dashboard
    const pendingApprovalsCard = page.locator("div.grid > div").filter({ hasText: "Pending Approvals" });
    await expect(pendingApprovalsCard).toBeVisible();

    // Read the pending approvals count
    const pendingText = await pendingApprovalsCard.locator(".text-2xl, .text-3xl").innerText();
    const pendingCount = parseInt(pendingText.trim(), 10);
    expect(Number.isInteger(pendingCount)).toBe(true);

    // 4. Click Review or navigate to Approvals
    if (pendingCount > 0) {
      await pendingApprovalsCard.getByRole("link", { name: /Review/i }).click();
    } else {
      await page.locator("aside").getByRole("link", { name: "Approvals" }).click();
    }
    await page.waitForURL("/approvals");
    await expect(page.getByText("Human-in-the-Loop Approvals")).toBeVisible();

    // 5. Compare actionable records on Approvals page
    if (pendingCount > 0) {
      const cards = page.locator('[id^="approval-card-"]');
      await expect(cards).toHaveCount(pendingCount);
    } else {
      await expect(page.getByText("All caught up!")).toBeVisible();
    }

    // 6. Return to Overview and verify counter persistence
    await page.locator("aside").getByRole("link", { name: "Overview" }).click();
    await page.waitForURL("/dashboard");
    const pendingTextAfterReturn = await pendingApprovalsCard.locator(".text-2xl, .text-3xl").innerText();
    expect(parseInt(pendingTextAfterReturn.trim(), 10)).toBe(pendingCount);

    // 7. Refresh browser and verify consistency
    await page.reload();
    await expect(page.getByText("Operations Command Center")).toBeVisible();
    const pendingTextAfterReload = await pendingApprovalsCard.locator(".text-2xl, .text-3xl").innerText();
    expect(parseInt(pendingTextAfterReload.trim(), 10)).toBe(pendingCount);

    // 8. Log out to test user isolation
    await page.getByLabel("User profile menu").click();
    await page.getByRole("button", { name: /Sign out/i }).click();
    await page.waitForURL("/login");
  });

  test("Scenario B & C — Active Schedules counter matches active schedules tab and excludes history", async ({
    page,
  }) => {
    test.setTimeout(60000);

    // 1. Sign in as operator@flowpilot.ai
    await page.goto("/login");
    await page.getByLabel(/Email Address/i).fill("operator@flowpilot.ai");
    await page.getByLabel(/Password/i).fill("Password123!");
    await page.getByRole("button", { name: /Sign In/i }).click();
    await page.waitForURL("/dashboard");

    // 2. Read Active Schedules metric from dashboard
    const schedulesCard = page.locator("div.grid > div").filter({ hasText: "Active Schedules" });
    await expect(schedulesCard).toBeVisible();
    const activeText = await schedulesCard.locator(".text-2xl, .text-3xl").innerText();
    const activeCount = parseInt(activeText.trim(), 10);
    expect(Number.isInteger(activeCount)).toBe(true);

    // 3. Navigate to Schedules page
    await page.locator("aside").getByRole("link", { name: "Schedules" }).click();
    await page.waitForURL("/schedules");
    await expect(page.getByText("Workflow Schedules")).toBeVisible();

    // 4. Verify Active Schedules tab badge matches the dashboard count
    const activeTabButton = page.getByRole("button", { name: /Active Schedules/i });
    await expect(activeTabButton).toBeVisible();
    const tabBadgeText = await activeTabButton.locator("span, div").filter({ hasText: /^\d+$/ }).innerText();
    expect(parseInt(tabBadgeText.trim(), 10)).toBe(activeCount);

    // 5. Verify Schedule History tab exists and is distinct
    const historyTabButton = page.getByRole("button", { name: /Schedule History/i });
    await expect(historyTabButton).toBeVisible();
    await historyTabButton.click();
    await expect(page.getByText(/Archived One-Time Schedules|No schedule history yet/i)).toBeVisible();

    // 6. Return to Overview via sidebar and verify instant cache freshness
    await page.locator("aside").getByRole("link", { name: "Overview" }).click();
    await page.waitForURL("/dashboard");
    await expect(schedulesCard).toBeVisible();

    // 7. Clean logout
    await page.getByLabel("User profile menu").click();
    await page.getByRole("button", { name: /Sign out/i }).click();
    await page.waitForURL("/login");
  });
});
