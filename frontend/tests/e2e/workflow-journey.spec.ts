import { test, expect } from "@playwright/test";

test.describe("FlowPilot AI — Operator Journey", () => {
  test("full navigation, workflow execution and operator dashboard flow", async ({ page }) => {
    test.setTimeout(60000);
    // 1. Visit Login Page
    await page.goto("/login");
    await expect(page).toHaveTitle(/FlowPilot AI/);
    await expect(page.getByText("Welcome Back")).toBeVisible();

    // 2. Perform Login
    await page.getByLabel(/Email Address/i).fill("operator@flowpilot.ai");
    await page.getByLabel(/Password/i).fill("Password123!");
    await page.getByRole("button", { name: /Sign In/i }).click();

    // 3. Verify Dashboard Overview
    await page.waitForURL("/dashboard");
    await expect(page.getByText("Operations Command Center")).toBeVisible();
    await expect(page.getByText("Total Executions")).toBeVisible();
    await expect(page.getByText("Active Executions")).toBeVisible();
    await expect(page.getByText("Pending Approvals")).toBeVisible();

    // 4. Navigate to Workflow Creation
    await page.locator("aside").getByRole("link", { name: "New Workflow" }).click();
    await page.waitForURL("/workflows");
    await expect(page.getByText("New Workflow Execution")).toBeVisible();

    // 5. Select a Starter Template
    await page.getByText("Weekly Ops Briefing", { exact: true }).click();
    const promptInput = page.getByPlaceholder(/Describe what you want the multi-agent system to accomplish/i);
    await expect(promptInput).not.toBeEmpty();

    // 6. Submit Workflow Run
    await page.getByRole("button", { name: /Execute Workflow/i }).click();
    await page.waitForURL(/\/executions\/[a-zA-Z0-9-]+/);

    // 7. Verify Execution Monitor
    await expect(page.getByText(/Execution:/i)).toBeVisible();
    await expect(page.getByText("LangGraph Execution Plan")).toBeVisible();
    await expect(page.getByText(/Live Audit Telemetry Stream/i)).toBeVisible();

    // 8. Navigate to Approvals
    await page.locator("aside").getByRole("link", { name: "Approvals" }).click();
    await page.waitForURL("/approvals");
    await expect(page.getByText("Human-in-the-Loop Approvals")).toBeVisible();

    // 9. Navigate to Schedules
    await page.locator("aside").getByRole("link", { name: "Schedules" }).click();
    await page.waitForURL("/schedules");
    await expect(page.getByText("Workflow Schedules")).toBeVisible();
    await expect(page.getByRole("button", { name: "New Schedule" })).toBeVisible();

    // 10. Navigate to Integrations
    await page.locator("aside").getByRole("link", { name: "Integrations" }).click();
    await page.waitForURL("/integrations");
    await expect(page.getByText("External Integrations & Business Channels")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Google (Gmail)" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Slack" })).toBeVisible();

    // 11. Navigate to BYOK Settings
    await page.locator("aside").getByRole("link", { name: "Multi-LLM (BYOK)" }).click();
    await page.waitForURL("/settings/llm");
    await expect(page.getByText("Multi-LLM BYOK & Model Orchestration")).toBeVisible();
    await expect(page.getByRole("button", { name: /Gemini/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /OpenAI/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /Groq/i })).toBeVisible();

    // 12. Switch to Groq provider tab
    await page.getByRole("button", { name: /Groq/i }).click();
    await expect(page.getByText("Groq API Key")).toBeVisible();

    // 13. Perform User Logout
    await page.getByLabel("User profile menu").click();
    await page.getByRole("button", { name: /Sign out/i }).click();
    await page.waitForURL("/login");
    await expect(page.getByText("Welcome Back")).toBeVisible();
  });
});
