import { defineConfig, devices } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const fixturePath = path.resolve(
  __dirname,
  "playwright/fixtures/operator.json",
);
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf-8")) as {
  username: string;
  password: string;
  argon2Hash: string;
};

const TEST_JWT_SECRET =
  "test-secret-do-not-use-in-prod-aaaaaaaaaaaaaaaaaaaa";

export default defineConfig({
  testDir: "./playwright",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run start",
    url: "http://127.0.0.1:3000/login",
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      HOST: "127.0.0.1",
      PORT: "3000",
      DASHBOARD_OPERATOR_USERNAME: fixture.username,
      DASHBOARD_OPERATOR_PASSWORD_ARGON2_HASH: fixture.argon2Hash,
      DASHBOARD_JWT_SECRET: TEST_JWT_SECRET,
    },
  },
});
