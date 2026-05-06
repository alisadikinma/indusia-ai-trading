import { Suspense } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LoginForm } from "./login-form";

export const metadata = {
  title: "Sign in — Bot Cockpit",
};

// useSearchParams() inside <LoginForm /> requires a Suspense boundary to
// avoid bailing out of static rendering during the production build.
export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Bot Cockpit</CardTitle>
          <CardDescription>
            Operator sign-in. Tailscale-only access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </CardContent>
      </Card>
    </main>
  );
}
