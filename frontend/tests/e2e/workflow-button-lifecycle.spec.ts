import { test, expect } from "@playwright/test";

test.describe("Workflow Button Lifecycle & Next.js Navigation Stability", () => {
  test.beforeEach(async ({ page }) => {
    // Perform standard login
    await page.goto("/login");
    await page.getByLabel(/Email Address/i).fill("operator@flowpilot.ai");
    await page.getByLabel(/Password/i).fill("Password123!");
    await page.getByRole("button", { name: /Sign In/i }).click();
    await page.waitForURL("/dashboard");
  });

  test("execute workflow button resets loading state and remains interactive upon back-navigation", async ({ page }) => {
    // 1. Navigate to /workflows
    await page.locator("aside").getByRole("link", { name: "New Workflow" }).click();
    await page.waitForURL("/workflows");
    await expect(page.getByRole("heading", { name: "New Workflow Execution" })).toBeVisible();

    const submitBtn = page.getByRole("button", { name: /Execute Workflow/i });
    await expect(submitBtn).toBeVisible();
    await expect(submitBtn).toBeEnabled();

    // 2. Select a preset template
    await page.getByText("Weekly Ops Briefing", { exact: true }).click();
    const promptInput = page.getByPlaceholder(/Describe what you want the multi-agent system to accomplish/i);
    await expect(promptInput).not.toBeEmpty();

    // 3. Click Execute Workflow
    await submitBtn.click();

    // 4. Verify navigation to Execution Details
    await page.waitForURL(/\/executions\/[a-zA-Z0-9-]+/);
    await expect(page.getByText(/Execution:/i)).toBeVisible();

    // 5. Navigate BACK to /workflows
    await page.locator("aside").getByRole("link", { name: "New Workflow" }).click();
    await page.waitForURL("/workflows");

    // 6. VERIFY BUTTON IS IDLE (NOT LOADING/SPINNING) WITHOUT REFRESHING PAGE
    const newSubmitBtn = page.getByRole("button", { name: /Execute Workflow/i });
    await expect(newSubmitBtn).toBeVisible();
    await expect(newSubmitBtn).toBeEnabled();
    await expect(newSubmitBtn).toHaveText(/Execute Workflow/i);

    // 7. Verify user can type and submit again immediately
    const newPromptInput = page.getByPlaceholder(/Describe what you want the multi-agent system to accomplish/i);
    await newPromptInput.fill("Second workflow execution test");
    await expect(newSubmitBtn).toBeEnabled();
  });

  test("navigation loop across core routes preserves instant navigation with zero dropped segments", async ({ page }) => {
    const errorLogs: string[] = [];
    page.on("console", (msg) => {
      const text = msg.text();
      if (text.includes("Could not validate that a segment") || text.includes("Dropped segment") || text.includes("Error Type: Instant")) {
        errorLogs.push(text);
      }
    });

    // Dashboard -> New Workflow -> Approvals -> New Workflow
    await page.locator("aside").getByRole("link", { name: "Overview" }).click();
    await page.waitForURL("/dashboard");

    await page.locator("aside").getByRole("link", { name: "New Workflow" }).click();
    await page.waitForURL("/workflows");
    await expect(page.getByRole("heading", { name: "New Workflow Execution" })).toBeVisible();

    await page.locator("aside").getByRole("link", { name: "Approvals" }).click();
    await page.waitForURL("/approvals");
    await expect(page.getByText("Human-in-the-Loop Approvals")).toBeVisible();

    await page.locator("aside").getByRole("link", { name: "New Workflow" }).click();
    await page.waitForURL("/workflows");
    await expect(page.getByRole("heading", { name: "New Workflow Execution" })).toBeVisible();

    // Confirm no dropped segment or instant-navigation errors occurred
    expect(errorLogs).toEqual([]);
  });
});
