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
  const res = await page.request.post("/api/auth/login", {
    data: {
      username: fixture.username,
      password: fixture.password,
      next: "/iteration-history",
    },
  });
  if (!res.ok()) {
    throw new Error(`Login API failed: ${res.status()} ${await res.text()}`);
  }
}

const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:3000",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "content-type,accept,authorization",
};

const EMPTY_ITERATIONS = JSON.stringify([]);

// Seeded fixtures live in playwright/ (allowed by Iron Law 3 — test-only).
const SEEDED_ITERATIONS = JSON.stringify([
  {
    id: 3,
    started_at: "2026-05-07T08:00:00Z",
    completed_at: "2026-05-07T09:30:00Z",
    run_type: "iteration",
    cycle_n: 3,
    failure_mode: "overfit",
    hypothesis: "Reduce lookback window from 100 to 60 to cut overfit to 2024 bull regime.",
    adr_ref: "docs/decisions/2026-05-07-003-strategy-v2.md",
    metrics_before: { sharpe: 1.1, max_dd: 0.28, profit_factor: 1.2, total_trades: 87 },
    metrics_after: { sharpe: 1.6, max_dd: 0.22, profit_factor: 1.5, total_trades: 112 },
    outcome: "PASS",
    summary: "Lookback reduction improved Sharpe and reduced MaxDD below gate.",
  },
  {
    id: 2,
    started_at: "2026-05-05T10:00:00Z",
    completed_at: "2026-05-05T12:00:00Z",
    run_type: "iteration",
    cycle_n: 2,
    failure_mode: "regime_specific",
    hypothesis: "Add volatile-regime filter to skip entries during high ATR periods.",
    adr_ref: null,
    metrics_before: { sharpe: 0.9, max_dd: 0.31, profit_factor: 1.1, total_trades: 95 },
    metrics_after: { sharpe: 1.1, max_dd: 0.28, profit_factor: 1.2, total_trades: 87 },
    outcome: "FAIL_RETRY",
    summary: "Regime filter helped MaxDD but Sharpe still below gate.",
  },
  {
    id: 1,
    started_at: "2026-05-03T06:00:00Z",
    completed_at: "2026-05-03T07:00:00Z",
    run_type: "post_mortem",
    cycle_n: null,
    failure_mode: null,
    hypothesis: null,
    adr_ref: null,
    metrics_before: null,
    metrics_after: null,
    outcome: "PASS",
    summary: "Weekly post-mortem: 3 wins, 1 loss, regime stable.",
  },
]);

async function stubIterations(
  page: Page,
  response: string,
  recorder?: { urls: string[] },
) {
  await page.route("**/dashboard/**", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    const url = route.request().url();
    recorder?.urls.push(url);
    if (url.includes("/iteration-runs")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS_HEADERS,
        body: response,
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS_HEADERS,
        body: "{}",
      });
    }
  });
}

test.describe("Bot Cockpit /iteration-history", () => {
  test("renders empty state when iteration_runs table empty", async ({ page }) => {
    await stubIterations(page, EMPTY_ITERATIONS);

    await login(page);
    await page.goto("/iteration-history");

    // StubPage coming-in text MUST be absent — page is real now.
    await expect(page.getByText(/coming in 1\.5\.G2/i)).toHaveCount(0);

    // Page heading is present.
    await expect(
      page.getByRole("heading", { name: /^Iteration History$/ }),
    ).toBeVisible({ timeout: 15_000 });

    // Empty-state copy mentions Phase 9.5 AND/OR Phase 6.
    const main = page.locator("main");
    const emptyText = main.getByText(/Phase 9\.5|Phase 6/i);
    await expect(emptyText.first()).toBeVisible({ timeout: 15_000 });
  });

  test("renders seeded iteration cards with outcome badges and metrics diff", async ({
    page,
  }) => {
    await stubIterations(page, SEEDED_ITERATIONS);

    await login(page);
    await page.goto("/iteration-history");

    const main = page.locator("main");

    // Heading visible.
    await expect(
      page.getByRole("heading", { name: /^Iteration History$/ }),
    ).toBeVisible({ timeout: 15_000 });

    // PASS badge visible.
    await expect(main.getByText("PASS").first()).toBeVisible({
      timeout: 15_000,
    });

    // FAIL_RETRY badge visible.
    await expect(main.getByText("FAIL_RETRY").first()).toBeVisible({
      timeout: 15_000,
    });

    // ADR link present for the run that has adr_ref set.
    const adrLink = main.getByText(/strategy-v2/i).first();
    await expect(adrLink).toBeVisible({ timeout: 15_000 });

    // Metrics diff headings visible (Before / After / Δ or Delta).
    // The seeded run with id=3 has both metrics_before and metrics_after set.
    // Expand the first iteration card to reveal the diff.
    const firstCard = main.locator("[data-testid='iteration-card']").first();
    await firstCard.locator("[data-testid='expand-btn']").click();

    await expect(main.getByText(/Before/i).first()).toBeVisible({
      timeout: 10_000,
    });
    await expect(main.getByText(/After/i).first()).toBeVisible({
      timeout: 10_000,
    });
    // Delta column heading: "Δ" or similar.
    await expect(
      main.getByText(/[ΔDelta]/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("filter change triggers a re-fetch with updated query params", async ({
    page,
  }) => {
    const recorder = { urls: [] as string[] };
    await stubIterations(page, SEEDED_ITERATIONS, recorder);

    await login(page);
    await page.goto("/iteration-history");

    // Wait for initial fetch to land.
    await expect(
      page.getByRole("heading", { name: /^Iteration History$/ }),
    ).toBeVisible({ timeout: 15_000 });

    // Reset recorder to only capture the filter-driven fetch.
    recorder.urls = [];

    // Change the outcome filter to PASS — the select has data-testid.
    await page
      .locator("[data-testid='filter-outcome']")
      .selectOption("PASS");

    // Poll until a request with outcome=PASS lands.
    await expect
      .poll(
        () =>
          recorder.urls.some(
            (u) =>
              u.includes("/iteration-runs") && u.includes("outcome=PASS"),
          ),
        { timeout: 15_000 },
      )
      .toBe(true);
  });
});
