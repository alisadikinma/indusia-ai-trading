import { StubPage } from "@/components/stub-page";

export const metadata = { title: "Brain Journal — Bot Cockpit" };

export default function JournalPage() {
  return (
    <StubPage
      title="Brain Journal"
      comingIn="1.5.F"
      description="Append-only feed of every decision Claude has logged, with reasoning + outcome — lands in sub-block 1.5.F."
    />
  );
}
