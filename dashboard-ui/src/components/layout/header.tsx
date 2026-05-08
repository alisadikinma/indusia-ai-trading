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
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);

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
        <Link href="/dashboard" className="flex shrink-0 items-center gap-2">
          <span className="text-lg font-semibold tracking-tight">
            <span className="text-primary">◤</span>{" "}
            <span className="hidden sm:inline">Indusia AI Trading</span>
            <span className="sm:hidden">Indusia</span>
          </span>
        </Link>

        {/* Desktop nav */}
        <nav
          className="hidden flex-1 items-center gap-1 md:flex"
          aria-label="Main navigation"
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

        {/* Right side */}
        <div className="flex flex-1 items-center justify-end gap-2 md:flex-none md:gap-3">
          <Badge variant="outline" className="hidden font-mono uppercase sm:flex">
            {envTag}
          </Badge>
          <span className="hidden items-center gap-2 text-sm text-muted-foreground sm:flex">
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full",
                dotClass,
              )}
              aria-label={`API connection ${connectionState}`}
            />
            <span className="font-medium text-foreground">{operator}</span>
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onSignOut}
            disabled={signingOut}
            className="hidden md:inline-flex"
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </Button>

          {/* Mobile hamburger */}
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
            aria-label={mobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMobileMenuOpen((v) => !v)}
          >
            {/* Hamburger icon using CSS — no external icon dep */}
            <span className="sr-only">{mobileMenuOpen ? "Close menu" : "Open menu"}</span>
            <svg
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
              aria-hidden="true"
            >
              {mobileMenuOpen ? (
                <>
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </>
              ) : (
                <>
                  <line x1="3" y1="7" x2="21" y2="7" />
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="17" x2="21" y2="17" />
                </>
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile nav drawer — shown below the header bar */}
      {mobileMenuOpen ? (
        <nav
          id="mobile-nav"
          className="border-t border-border bg-background px-4 pb-3 pt-2 md:hidden"
          aria-label="Mobile navigation"
        >
          {NAV_LINKS.map((l) => {
            const active =
              pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setMobileMenuOpen(false)}
                className={cn(
                  "flex rounded-md px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
          <div className="mt-2 flex items-center justify-between border-t border-border pt-2">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span
                className={cn("inline-block h-2 w-2 rounded-full", dotClass)}
                aria-label={`API connection ${connectionState}`}
              />
              <span className="font-medium text-foreground">{operator}</span>
              <Badge variant="outline" className="font-mono uppercase">
                {envTag}
              </Badge>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={onSignOut}
              disabled={signingOut}
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </Button>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
