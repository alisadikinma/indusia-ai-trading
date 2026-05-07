import { cookies } from "next/headers";

import { Header } from "@/components/layout/header";
import { FreqaiClient } from "./freqai-client";
import { SESSION_COOKIE_NAME, getOperatorUsername } from "@/lib/auth";

export const metadata = { title: "FreqAI Insights — Bot Cockpit" };
// Reading the session cookie means this page is dynamic; opt out of static rendering.
export const dynamic = "force-dynamic";

export default async function FreqaiPage() {
  const cookieStore = await cookies();
  const wsToken = cookieStore.get(SESSION_COOKIE_NAME)?.value ?? null;
  const operator = getOperatorUsername();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <FreqaiClient wsToken={wsToken} />
    </div>
  );
}
