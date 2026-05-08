import { Header } from "@/components/layout/header";
import { JournalClient } from "./journal-client";
import { requireOperatorSession } from "@/lib/auth";

export const metadata = { title: "Brain Journal — Indusia AI Trading" };
// Reading the session cookie + env-required JWT secret means this page is
// inherently dynamic; opt out of static rendering loudly.
export const dynamic = "force-dynamic";

export default async function JournalPage() {
  // Defense-in-depth: require valid session + refresh on each page load.
  const { operator } = await requireOperatorSession();
  const envTag = process.env.DASHBOARD_ENV_TAG ?? "dev";

  return (
    <div className="flex min-h-screen flex-col">
      <Header operator={operator} envTag={envTag} />
      <JournalClient />
    </div>
  );
}
