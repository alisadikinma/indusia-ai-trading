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
  await page.goto("/login");
  await page.getByLabel("Username").fill(fixture.username);
  await page.getByLabel("Password").fill(fixture.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL("**/dashboard");
}

test.describe("Bot Cockpit /dashboard", () => {
  test("renders all five panel headings after login", async ({ page }) => {
    await login(page);
    // Stub copy must NOT be present
    await expect(page.getByText(/coming in 1\.5\.D/i)).toHaveCount(0);
    // All five panels must render their headings
    await expect(
      page.getByRole("heading", { name: /^Live Chart$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^AI Reasoning$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^Open Positions$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^Risk Monitor$/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^Equity Curve$/ }),
    ).toBeVisible();
  });

  test("timeframe switcher updates active state on click", async ({ page }) => {
    await login(page);
    const tf1m = page.getByRole("tab", { name: "1m", exact: true });
    const tf15m = page.getByRole("tab", { name: "15m", exact: true });
    await expect(tf15m).toHaveAttribute("data-active", "true");
    await tf1m.click();
    await expect(tf1m).toHaveAttribute("data-active", "true");
    await expect(tf15m).toHaveAttribute("data-active", "false");
  });

  test("pair switcher renders both BTC and ETH options", async ({ page }) => {
    await login(page);
    const pairSelect = page.getByLabel(/Pair/i);
    await expect(pairSelect).toBeVisible();
    await expect(pairSelect.locator("option")).toHaveCount(2);
    await expect(pairSelect.locator('option[value="BTC/USDT"]')).toHaveCount(1);
    await expect(pairSelect.locator('option[value="ETH/USDT"]')).toHaveCount(1);
  });

  test("renders empty-state copy when API returns empty arrays", async ({
    page,
  }) => {
    // Mock backend to always return empty arrays / null
    await page.route("**/dashboard/**", async (route) => {
      const url = route.request().url();
      if (url.includes("/journal")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: [], total: 0, page: 1, size: 50 }),
        });
        return;
      }
      if (url.includes("/risk/state")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            drawdown_pct: null,
            daily_pnl: null,
            open_positions: 0,
            circuit_breaker_state: "green",
            note: "no equity_curve rows yet",
          }),
        });
        return;
      }
      // ohlcv, positions, equity → empty array
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    });
    await login(page);
    // Empty state copy must be present somewhere on the page
    await expect(page.getByText(/no open positions/i)).toBeVisible();
    await expect(
      page.getByText(/Brain hasn't written any decisions yet/i),
    ).toBeVisible();
  });

  test("middleware redirects unauthenticated /dashboard to /login", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login(\?.*)?$/);
  });
});
