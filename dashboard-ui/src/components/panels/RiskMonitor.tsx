"use client";

import * as React from "react";

import { useRisk } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const MAX_POSITIONS = 3; // Iron Law 1.

function fmtUsd(v: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(v);
}

function ddColor(pctFraction: number): string {
  if (pctFraction >= 0.10) return "text-rose-400";
  if (pctFraction >= 0.05) return "text-amber-400";
  return "text-emerald-400";
}

function cbVariant(state: string): "success" | "warning" | "danger" {
  if (state === "red") return "danger";
  if (state === "amber") return "warning";
  return "success";
}

interface MetricProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  className?: string;
}

function Metric({ label, value, hint, className }: MetricProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-md border border-border bg-card p-3",
        className,
      )}
    >
      <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="font-mono text-xl">{value}</span>
      {hint ? (
        <span className="text-xs text-muted-foreground">{hint}</span>
      ) : null}
    </div>
  );
}

export interface RiskMonitorProps {
  className?: string;
}

export function RiskMonitor({ className }: RiskMonitorProps) {
  const { data, isLoading, error } = useRisk();

  return (
    <section
      className={cn("flex h-full flex-col gap-3", className)}
      aria-label="Risk monitor"
    >
      <header className="flex items-center justify-between gap-3 px-1">
        <h2 className="text-lg font-semibold tracking-tight">Risk Monitor</h2>
        {data ? (
          <Badge variant={cbVariant(data.circuit_breaker_state)}>
            <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-current" />
            CB {data.circuit_breaker_state}
          </Badge>
        ) : null}
      </header>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load risk state: {error.message}
          </AlertDescription>
        </Alert>
      ) : null}

      {isLoading && !data ? (
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : null}

      {data ? (
        <div className="grid grid-cols-2 gap-3">
          <Metric
            label="Drawdown"
            value={
              <span
                className={cn(
                  data.drawdown_pct == null
                    ? "text-muted-foreground"
                    : ddColor(data.drawdown_pct),
                )}
              >
                {data.drawdown_pct == null
                  ? "—"
                  : `${(data.drawdown_pct * 100).toFixed(2)}%`}
              </span>
            }
            hint="Max −20% kill-switch"
          />
          <Metric
            label="Daily PnL"
            value={
              <span
                className={cn(
                  data.daily_pnl == null
                    ? "text-muted-foreground"
                    : data.daily_pnl >= 0
                      ? "text-emerald-400"
                      : "text-rose-400",
                )}
              >
                {data.daily_pnl == null ? "—" : fmtUsd(data.daily_pnl)}
              </span>
            }
            hint="Daily −5% halts 24h"
          />
          <Metric
            label="Open Positions"
            value={`${data.open_positions} / ${MAX_POSITIONS}`}
            hint="Hard cap per Iron Law 1"
          />
          <Metric
            label="Drift vs Backtest"
            value={
              <span className="text-muted-foreground">
                — pending Phase 12
              </span>
            }
            hint="Populates after live trading begins"
          />
        </div>
      ) : null}

      {data?.note ? (
        <Alert variant="muted">
          <AlertDescription>{data.note}</AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
