"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const NAV_LINKS: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/dashboard", label: "Live" },
  { href: "/strategy-lab", label: "Strategy Lab" },
  { href: "/journal", label: "Brain Journal" },
  { href: "/freqai", label: "FreqAI" },
  { href: "/iteration-history", label: "Iterations" },
];

export interface HeaderProps {
  /** Operator name shown in the top-right. */
  operator: string;
  /** Environment tag — 'dev' / 'paper' / 'live $100' / etc. */
  envTag?: string;
  /**
   * Connection state pill. Maps to circuit-breaker style colours:
   *   green = healthy, amber = degraded, red = unreachable.
   */
  connectionState?: "green" | "amber" | "red";
}

export function Header({
  operator,
  envTag = "dev",
  connectionState = "green",
}: HeaderProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = React.useState(false);

  async function onSignOut() {
    setSigningOut(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } finally {
      setSigningOut(false);
    }
  }

  const dotClass =
    connectionState === "green"
      ? "bg-emerald-500"
      : connectionState === "amber"
        ? "bg-amber-500"
        : "bg-rose-500";

  return (
    <header
      className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60"
      role="banner"
    >
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4">
        <Link href="/dashboard" className="flex items-center gap-2">
          <span className="text-lg font-semibold tracking-tight">
            <span className="text-primary">◤</span> Bot Cockpit
          </span>
        </Link>
        <nav
          className="hidden flex-1 items-center gap-1 md:flex"
          aria-label="Main"
        >
          {NAV_LINKS.map((l) => {
            const active =
              pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex flex-1 items-center justify-end gap-3 md:flex-none">
          <Badge variant="outline" className="font-mono uppercase">
            {envTag}
          </Badge>
          <span className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex">
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full",
                dotClass,
              )}
              aria-label={`API ${connectionState}`}
            />
            <span className="font-medium text-foreground">{operator}</span>
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onSignOut}
            disabled={signingOut}
          >
            {signingOut ? "Signing out..." : "Sign out"}
          </Button>
        </div>
      </div>
    </header>
  );
}
