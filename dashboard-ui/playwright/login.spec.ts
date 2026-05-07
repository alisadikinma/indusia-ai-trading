import { test, expect } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const fixture = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, "fixtures/operator.json"),
    "utf-8",
  ),
) as { username: string; password: string; argon2Hash: string };

test.describe("Bot Cockpit /login", () => {
  test("renders username and password fields", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Username")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /sign in/i }),
    ).toBeVisible();
  });

  test("invalid credentials show an error message", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill("not-the-operator");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: /sign in/i }).click();
    // Scope to the form's own error region (not Next's route announcer).
    const errorBox = page.locator("#login-error");
    await expect(errorBox).toBeVisible();
    await expect(errorBox).toContainText(/invalid credentials/i);
    await expect(page).toHaveURL(/\/login(\?.*)?$/);
  });

  test("valid credentials redirect to /dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill(fixture.username);
    await page.getByLabel("Password").fill(fixture.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await page.waitForURL("**/dashboard");
    // Phase 1.5.D landed: real Live Dashboard, not the stub. Confirm at least
    // one of the panel headings is visible.
    await expect(
      page.getByRole("heading", { name: /^Live Chart$/ }),
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
