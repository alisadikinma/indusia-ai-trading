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
  // Bypass the login form (controlled-input hydration race under React 19 +
  // Next 16 Suspense, see strategy-lab.spec.ts). Hit the JSON API directly.
  const res = await page.request.post("/api/auth/login", {
    data: {
      username: fixture.username,
      password: fixture.password,
      next: "/freqai",
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

const EMPTY_CALIBRATION = JSON.stringify({
  calibration: [],
  auc_history: [],
  feature_importance: null,
  note:
    "No FreqAI retrains recorded yet — Phase 7 cron populates "
    + "brain.freqai_history on each daily retrain.",
});

const EMPTY_HISTORY = JSON.stringify([]);
const EMPTY_PREDICTIONS = JSON.stringify({
  bins: [],
  total: 0,
  hours: 24,
  note: "No Claude oversight decisions in the last 24h yet.",
});

// Calibration buckets MUST come from the [0.5, 1.5] claude_size_mult domain
// (schema CHECK constraint + backend _CALIBRATION_EDGES). Any value outside
// this range is impossible from real DB data and would mask plot-domain bugs.
const SEEDED_CALIBRATION = JSON.stringify({
  calibration: [
    { bucket_lo: 0.5, bucket_hi: 0.6, predicted_mid: 0.55, actual_win_rate: 0.18, n: 12 },
    { bucket_lo: 1.0, bucket_hi: 1.1, predicted_mid: 1.05, actual_win_rate: 0.55, n: 31 },
    { bucket_lo: 1.4, bucket_hi: 1.5, predicted_mid: 1.45, actual_win_rate: 0.92, n: 8 },
  ],
  auc_history: [
    { retrained_at: "2026-05-01T06:00:00Z", auc: 0.61, pair: "BTC/USDT", tf: "15m" },
    { retrained_at: "2026-05-04T06:00:00Z", auc: 0.64, pair: "BTC/USDT", tf: "15m" },
    { retrained_at: "2026-05-07T06:00:00Z", auc: 0.66, pair: "BTC/USDT", tf: "15m" },
  ],
  feature_importance: {
    "%-volatility_4h": 0.1025,
    "%-ema_dist_50": 0.0898,
    "%-volatility_1h": 0.0837,
    "%-return_12h": 0.0544,
    "%-ema_dist_14": 0.0532,
  },
  note: "",
});

const SEEDED_HISTORY = JSON.stringify([
  {
    id: 3,
    retrained_at: "2026-05-07T06:00:00Z",
    pair: "BTC/USDT",
    tf: "15m",
    train_window_days: 30,
    train_rows: 2880,
    auc: 0.66,
    model_path: "user_data/models/ClaudeOversightModel-v3.pkl",
    notes: null,
  },
  {
    id: 2,
    retrained_at: "2026-05-04T06:00:00Z",
    pair: "BTC/USDT",
    tf: "15m",
    train_window_days: 30,
    train_rows: 2880,
    auc: 0.64,
    model_path: "user_data/models/ClaudeOversightModel-v2.pkl",
    notes: null,
  },
]);

const SEEDED_PREDICTIONS = JSON.stringify({
  bins: [
    { lo: 0.5, hi: 0.6, count: 4 },
    { lo: 0.6, hi: 0.7, count: 2 },
    { lo: 0.9, hi: 1.0, count: 1 },
  ],
  total: 7,
  hours: 24,
  note: "",
});

async function stubFreqai(
  page: Page,
  responses: {
    calibration: string;
    history: string;
    predictions: string;
  },
  recorder?: { urls: string[] },
) {
  await page.route("**/dashboard/**", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    const url = route.request().url();
    recorder?.urls.push(url);
    let body = "{}";
    if (url.includes("/freqai/calibration")) body = responses.calibration;
    else if (url.includes("/freqai/history")) body = responses.history;
    else if (url.includes("/freqai/predictions")) body = responses.predictions;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: CORS_HEADERS,
      body,
    });
  });
}

test.describe("Bot Cockpit /freqai", () => {
  test("renders empty state when no FreqAI retrains yet", async ({ page }) => {
    await stubFreqai(page, {
      calibration: EMPTY_CALIBRATION,
      history: EMPTY_HISTORY,
      predictions: EMPTY_PREDICTIONS,
    });

    await login(page);
    await page.goto("/freqai");

    // Stub copy must NOT be present (would still appear if the page route
    // hadn't been replaced from the 1.5.A StubPage placeholder).
    await expect(page.getByText(/coming in 1\.5\.G/i)).toHaveCount(0);

    // Page heading is real.
    await expect(
      page.getByRole("heading", { name: /^FreqAI Insights$/ }),
    ).toBeVisible();

    // All five panel headings are present (each renders even when its data is
    // empty — the empty-state copy lives inside the panel).
    const main = page.locator("main");
    await expect(
      main.getByRole("heading", { name: /Calibration/i }),
    ).toBeVisible();
    await expect(
      main.getByRole("heading", { name: /AUC trend/i }),
    ).toBeVisible();
    await expect(
      main.getByRole("heading", { name: /Feature importance/i }),
    ).toBeVisible();
    await expect(
      main.getByRole("heading", { name: /Retrain history/i }),
    ).toBeVisible();
    await expect(
      main.getByRole("heading", { name: /Live prediction histogram/i }),
    ).toBeVisible();

    // Empty-state copy mentions Phase 7 (retrain dependency).
    await expect(main.getByText(/Phase 7/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("renders seeded calibration, AUC trend, feature importance, retrain history, and prediction histogram", async ({
    page,
  }) => {
    await stubFreqai(page, {
      calibration: SEEDED_CALIBRATION,
      history: SEEDED_HISTORY,
      predictions: SEEDED_PREDICTIONS,
    });

    await login(page);
    await page.goto("/freqai");

    const main = page.locator("main");

    // AUC summary surfaces the latest AUC (0.66 from seeded data).
    await expect(main.getByTestId("freqai-latest-auc")).toContainText("0.66", {
      timeout: 15_000,
    });

    // Feature importance: top feature shown by name.
    await expect(main.getByText("%-volatility_4h").first()).toBeVisible();

    // Retrain history table has both seeded rows.
    await expect(main.getByText("ClaudeOversightModel-v3.pkl")).toBeVisible();
    await expect(main.getByText("ClaudeOversightModel-v2.pkl")).toBeVisible();

    // Live prediction histogram total badge surfaces 7.
    await expect(main.getByTestId("freqai-prediction-total")).toContainText("7");
  });

  test("calls all three freqai endpoints on mount", async ({ page }) => {
    const recorder = { urls: [] as string[] };
    await stubFreqai(
      page,
      {
        calibration: EMPTY_CALIBRATION,
        history: EMPTY_HISTORY,
        predictions: EMPTY_PREDICTIONS,
      },
      recorder,
    );

    await login(page);
    await page.goto("/freqai");

    await expect
      .poll(
        () => recorder.urls.some((u) => u.includes("/freqai/calibration")),
        { timeout: 15_000 },
      )
      .toBe(true);
    await expect
      .poll(() => recorder.urls.some((u) => u.includes("/freqai/history")), {
        timeout: 15_000,
      })
      .toBe(true);
    await expect
      .poll(
        () => recorder.urls.some((u) => u.includes("/freqai/predictions")),
        { timeout: 15_000 },
      )
      .toBe(true);
  });
});
