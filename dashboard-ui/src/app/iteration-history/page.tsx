import { Header } from "@/components/layout/header";
import { IterationHistoryClient } from "./iteration-history-client";
import { requireOperatorSession } from "@/lib/auth";

export const metadata = { title: "Iteration History — Bot Cockpit" };
// Reading the session cookie means this page is dynamic; opt out of static rendering.
export const dynamic = "force-dynamic";

export default async function IterationHistoryPage() {
  // Defense-in-depth: require valid session + refresh on each page load.
  const { operator } = await requireOperatorSession();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <IterationHistoryClient />
    </div>
  );
}
