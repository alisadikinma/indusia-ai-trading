import { cookies } from "next/headers";

import { Header } from "@/components/layout/header";
import { StrategyLabClient } from "./strategy-lab-client";
import { SESSION_COOKIE_NAME, getOperatorUsername } from "@/lib/auth";

export const metadata = { title: "Strategy Lab — Bot Cockpit" };
// Reading the session cookie + env-required JWT secret means this page is
// inherently dynamic; opt out of static rendering loudly.
export const dynamic = "force-dynamic";

export default async function StrategyLabPage() {
  // Touch the cookie so this page is server-rendered with the same session
  // semantics as /dashboard. The actual data flows client-side via TanStack
  // Query against /dashboard/backtest/runs.
  const cookieStore = await cookies();
  cookieStore.get(SESSION_COOKIE_NAME);
  const operator = getOperatorUsername();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <StrategyLabClient />
    </div>
  );
}
