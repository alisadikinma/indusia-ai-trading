import { Header } from "@/components/layout/header";
import { IterationHistoryClient } from "./iteration-history-client";
import { getOperatorUsername } from "@/lib/auth";

export const metadata = { title: "Iteration History — Bot Cockpit" };
// getOperatorUsername reads an env var, which is enough to opt the page out of
// static rendering. No session-cookie read here — IterationHistoryClient does
// not subscribe to a WebSocket (the iteration_runs table is written by Phase
// 6/9.5 cron, not the live brain).
export const dynamic = "force-dynamic";

export default function IterationHistoryPage() {
  const operator = getOperatorUsername();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <IterationHistoryClient />
    </div>
  );
}
