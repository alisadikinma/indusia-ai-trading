import { Header } from "@/components/layout/header";
import { DashboardClient } from "./dashboard-client";
import { requireOperatorSession } from "@/lib/auth";

export const metadata = { title: "Live Dashboard — Bot Cockpit" };
// Reading the session cookie + env-required JWT secret means this page is
// inherently dynamic; opt out of static rendering loudly.
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  // Defense-in-depth: require valid session + refresh on each page load.
  const { wsToken, operator } = await requireOperatorSession();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <DashboardClient wsToken={wsToken} />
    </div>
  );
}
