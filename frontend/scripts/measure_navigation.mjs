import { chromium } from "@playwright/test";

async function runBenchmark() {
  console.log("=== FlowPilot AI Navigation Benchmark ===");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  // Helper to record network activity during a step
  let requests = [];
  page.on("request", (req) => {
    requests.push({
      url: req.url(),
      method: req.method(),
      resourceType: req.resourceType(),
      startTime: Date.now(),
    });
  });

  page.on("response", (res) => {
    const req = requests.find((r) => r.url === res.url());
    if (req) {
      req.status = res.status();
      req.duration = Date.now() - req.startTime;
    }
  });

  // 1. Login
  console.log("\n[1] Logging in as operator@flowpilot.ai...");
  await page.goto("http://localhost:3000/login", { waitUntil: "networkidle" });
  await page.getByLabel(/Email Address/i).fill("operator@flowpilot.ai");
  await page.getByLabel(/Password/i).fill("Password123!");
  await page.getByRole("button", { name: /Sign In/i }).click();
  await page.waitForURL("**/dashboard", { timeout: 15000 });
  await page.waitForLoadState("networkidle");
  console.log("[OK] Successfully logged in and landed on /dashboard");

  // Mark client window for full-page reload detection
  await page.evaluate(() => {
    window.__CLIENT_SESSION_MARKER__ = "SPA_PERSISTED";
  });

  // Navigation test paths
  const transitions = [
    {
      from: "/dashboard",
      to: "/executions",
      label: "Overview -> Executions",
      linkText: "Executions",
      selector: "aside a[href='/executions']",
      expectedText: "Workflow Executions",
    },
    {
      from: "/executions",
      to: "/settings/connections",
      label: "Executions -> App Connections",
      linkText: "App Connections",
      selector: "aside a[href='/settings/connections']",
      expectedText: "App Connections",
    },
    {
      from: "/settings/connections",
      to: "/settings/profile",
      label: "App Connections -> Account Profile",
      linkText: "Account Profile",
      selector: "aside a[href='/settings/profile']",
      expectedText: "Account & Security Settings",
    },
    {
      from: "/settings/profile",
      to: "/schedules",
      label: "Account Profile -> Scheduling",
      linkText: "Schedules",
      selector: "aside a[href='/schedules']",
      expectedText: "Workflow Schedules",
    },
    {
      from: "/schedules",
      to: "/dashboard",
      label: "Scheduling -> Overview",
      linkText: "Overview",
      selector: "aside a[href='/dashboard']",
      expectedText: "Operations Command Center",
    },
  ];

  async function performNav(t, runType) {
    requests = [];
    const beforeMarker = await page.evaluate(() => window.__CLIENT_SESSION_MARKER__);

    const tStart = performance.now();
    // Click navigation link
    const link = page.locator(t.selector);
    await link.click();

    // Wait for URL change
    await page.waitForURL(`**${t.to}`, { timeout: 30000 });
    const urlTime = performance.now() - tStart;

    // Wait for expected header / text to be visible
    await page.getByText(t.expectedText, { exact: false }).first().waitFor({ state: "visible", timeout: 30000 });
    const domReadyTime = performance.now() - tStart;

    // Wait small settling window to capture any immediate background API queries
    await page.waitForTimeout(600);
    const totalTime = performance.now() - tStart;

    const afterMarker = await page.evaluate(() => window.__CLIENT_SESSION_MARKER__);
    const isFullPageReload = beforeMarker !== "SPA_PERSISTED" || afterMarker !== "SPA_PERSISTED";

    // Summarize network requests
    const apiRequests = requests.filter((r) => r.url.includes("/api/"));
    const staticRequests = requests.filter((r) => !r.url.includes("/api/"));

    return {
      label: t.label,
      runType,
      urlTime: Math.round(urlTime),
      domReadyTime: Math.round(domReadyTime),
      totalTime: Math.round(totalTime),
      isFullPageReload,
      apiCount: apiRequests.length,
      apiCalls: apiRequests.map((r) => {
        try {
          const u = new URL(r.url);
          return `${r.method} ${u.pathname}${u.search} (${r.duration || 0}ms)`;
        } catch {
          return `${r.method} ${r.url}`;
        }
      }),
      staticCount: staticRequests.length,
    };
  }

  // --- PASS 1: First Visit (Cold Route Compilation) ---
  console.log("\n=========================================");
  console.log("PASS 1: First Visit (Cold Compilation)");
  console.log("=========================================");
  const pass1Results = [];
  for (const t of transitions) {
    console.log(`\nNavigating: ${t.label}...`);
    const res = await performNav(t, "First Visit (Cold)");
    pass1Results.push(res);
    console.log(`  - URL Change Duration: ${res.urlTime}ms`);
    console.log(`  - Content Visible Duration: ${res.domReadyTime}ms`);
    console.log(`  - Full-page Reload: ${res.isFullPageReload ? "YES (Reload occurred!)" : "No (SPA Client-Side Transition)"}`);
    console.log(`  - API Requests Triggered (${res.apiCount}):`);
    res.apiCalls.forEach((c) => console.log(`      * ${c}`));
  }

  // --- PASS 2: Second Visit (Warm Route Cache) ---
  console.log("\n=========================================");
  console.log("PASS 2: Second Visit (Warm / Post-Compile)");
  console.log("=========================================");
  const pass2Results = [];
  for (const t of transitions) {
    console.log(`\nNavigating: ${t.label}...`);
    const res = await performNav(t, "Second Visit (Warm)");
    pass2Results.push(res);
    console.log(`  - URL Change Duration: ${res.urlTime}ms`);
    console.log(`  - Content Visible Duration: ${res.domReadyTime}ms`);
    console.log(`  - Full-page Reload: ${res.isFullPageReload ? "YES (Reload occurred!)" : "No (SPA Client-Side Transition)"}`);
    console.log(`  - API Requests Triggered (${res.apiCount}):`);
    res.apiCalls.forEach((c) => console.log(`      * ${c}`));
  }

  // Summary Table
  console.log("\n=========================================");
  console.log("NAVIGATION LATENCY SUMMARY");
  console.log("=========================================");
  console.table(
    pass1Results.map((p1, idx) => {
      const p2 = pass2Results[idx];
      return {
        Route: p1.label,
        "1st Visit (ms)": p1.domReadyTime,
        "2nd Visit (ms)": p2.domReadyTime,
        "Client Route Transition": p1.isFullPageReload ? "Full Reload" : "Client SPA",
        "1st Visit APIs": p1.apiCount,
        "2nd Visit APIs": p2.apiCount,
      };
    })
  );

  await browser.close();
}

runBenchmark().catch((err) => {
  console.error("Benchmark error:", err);
  process.exit(1);
});
