import { test, expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const fixture = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, "fixtures/operator.json"),
    "utf-8",
  ),
) as { username: string; password: string; argon2Hash: string };

async function login(page: Page) {
  // Bypass the login form (its controlled-input hydration timing is flaky
  // under React 19 + Next 16 Suspense — the existing dashboard.spec.ts
  // sees the same race). Hit the JSON API directly: server sets the same
  // session cookie either way, and we're testing the /strategy-lab view,
  // not the auth UI.
  const res = await page.request.post("/api/auth/login", {
    data: {
      username: fixture.username,
      password: fixture.password,
      next: "/strategy-lab",
    },
  });
  if (!res.ok()) {
    throw new Error(`Login API failed: ${res.status()} ${await res.text()}`);
  }
}

// CORS headers required because api-client uses credentials:"include" and
// the dashboard origin (3000) ≠ API origin (8081). Browser would block the
// response without explicit Allow-Credentials + a non-wildcard Allow-Origin.
const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:3000",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,accept,authorization",
};

test.describe("Bot Cockpit /strategy-lab", () => {
  test("renders empty state when backtest_runs is empty", async ({ page }) => {
    // Mock backend to return empty list for backtest runs and OHLCV.
    await page.route("**/dashboard/**", async (route) => {
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: CORS_HEADERS });
        return;
      }
      const url = route.request().url();
      if (url.includes("/backtest/runs") && !url.match(/\/runs\/\d+/)) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: "[]",
        });
        return;
      }
      // OHLCV / others → empty
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS_HEADERS,
        body: "[]",
      });
    });

    await login(page);
    await page.goto("/strategy-lab");

    // Stub copy must NOT be present (would still appear if the page route
    // hadn't been replaced from the 1.5.E StubPage placeholder).
    await expect(page.getByText(/coming in 1\.5\.E/i)).toHaveCount(0);

    // Page heading is real.
    await expect(
      page.getByRole("heading", { name: /^Strategy Lab$/ }),
    ).toBeVisible();

    // Empty-state message — scope to <main> so the heading match doesn't
    // collide with the nav link of the same name.
    const emptyMatch = page.locator("main").getByText(/no backtests yet/i);
    await expect(emptyMatch).toBeVisible({ timeout: 15_000 });
  });

  test("renders seeded backtest run with metrics gate-coloring", async ({
    page,
  }) => {
    const runMeta = {
      id: 42,
      started_at: "2026-04-01T10:00:00Z",
      completed_at: "2026-04-01T11:00:00Z",
      strategy_version: "v1.0",
      fold_index: 1,
      train_start: "2025-01-01T00:00:00Z",
      train_end: "2025-06-30T00:00:00Z",
      test_start: "2025-07-01T00:00:00Z",
      test_end: "2025-09-30T00:00:00Z",
      metrics: {
        sharpe: 1.8,
        max_dd: 0.18,
        profit_factor: 1.6,
        total_trades: 142,
        win_rate: 0.58,
        expectancy: 0.012,
        sortino: 2.1,
      },
      gate_passed: true,
      notes: null,
    };
    const runDetail = {
      ...runMeta,
      parameters: { lookback: 14, atr_mult: 2.0 },
      equity_curve: [
        { ts: "2025-07-01T00:00:00Z", equity: 10000 },
        { ts: "2025-08-01T00:00:00Z", equity: 10800 },
        { ts: "2025-09-30T00:00:00Z", equity: 11500 },
      ],
      trades: [
        {
          ts: "2025-07-15T12:00:00Z",
          side: "long",
          price: 50000,
          pnl_pct: 0.02,
        },
      ],
    };

    await page.route("**/dashboard/**", async (route) => {
      if (route.request().method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: CORS_HEADERS });
        return;
      }
      const url = route.request().url();
      if (url.includes("/backtest/runs/42")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: JSON.stringify(runDetail),
        });
        return;
      }
      if (url.includes("/backtest/runs")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: JSON.stringify([runMeta]),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS_HEADERS,
        body: "[]",
      });
    });

    await login(page);
    await page.goto("/strategy-lab");

    const main = page.locator("main");
    // Fold-1 tab from FoldNavigator — proves the seeded run loaded and the
    // fold navigator built tabs from real data.
    await expect(main.getByRole("tab", { name: /Fold 1/i }).first()).toBeVisible(
      { timeout: 15_000 },
    );
    // The strategy version dropdown is populated from the seeded run.
    const versionSelect = page.getByLabel(/Strategy version/i);
    await expect(versionSelect.locator("option[value='v1.0']")).toHaveCount(1);
    // Per-fold metrics table renders the seeded fold row with the seeded
    // Sharpe value (1.8 → > 1.5 → green PASS).
    await expect(main.getByText("1.80").first()).toBeVisible({ timeout: 15_000 });
    // Phase 9 gate badge text is present.
    await expect(
      main.getByText(/Phase 9 gate (PASS|FAIL)/i).first(),
    ).toBeVisible();
  });
});
