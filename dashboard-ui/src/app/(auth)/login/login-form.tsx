"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface LoginResponse {
  ok?: boolean;
  redirect?: string;
  error?: string;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") ?? "/dashboard";

  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password, next: nextPath }),
      });
      const body = (await res.json().catch(() => ({}))) as LoginResponse;
      if (!res.ok || !body.ok) {
        setError(body.error || "Invalid credentials.");
        setSubmitting(false);
        return;
      }
      const target =
        typeof body.redirect === "string" && body.redirect.startsWith("/")
          ? body.redirect
          : "/dashboard";
      router.replace(target);
      router.refresh();
    } catch {
      setError("Network error — could not reach the cockpit API.");
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-4"
      aria-describedby={error ? "login-error" : undefined}
      noValidate
    >
      <div className="space-y-2">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          name="username"
          type="text"
          autoComplete="username"
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={submitting}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={submitting}
        />
      </div>
      {error ? (
        <div
          id="login-error"
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}
      <Button
        type="submit"
        className="w-full"
        disabled={submitting || !username || !password}
      >
        {submitting ? "Signing in..." : "Sign in"}
      </Button>
    </form>
  );
}
