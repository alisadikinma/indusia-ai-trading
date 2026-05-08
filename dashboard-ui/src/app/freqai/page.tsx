import { Header } from "@/components/layout/header";
import { FreqaiClient } from "./freqai-client";
import { requireOperatorSession } from "@/lib/auth";

export const metadata = { title: "FreqAI Insights — Indusia AI Trading" };
// Reading the session cookie means this page is dynamic; opt out of static rendering.
export const dynamic = "force-dynamic";

export default async function FreqaiPage() {
  // Defense-in-depth: require valid session + refresh on each page load.
  const { wsToken, operator } = await requireOperatorSession();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <FreqaiClient wsToken={wsToken} />
    </div>
  );
}
