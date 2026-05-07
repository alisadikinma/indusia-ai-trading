"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

// Semantic direction map: true = higher is better, false = lower is better.
// Keys match the BacktestMetrics interface + common variants from JSONB.
const HIGHER_IS_BETTER: Record<string, boolean> = {
  sharpe: true,
  sortino: true,
  profit_factor: true,
  pf: true,
  total_trades: true,
  win_rate: true,
  expectancy: true,
  max_dd: false,
  drawdown: false,
  volatility: false,
};

interface MetricsRow {
  key: string;
  before: number | null;
  after: number | null;
  delta: number | null;
}

function buildRows(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): MetricsRow[] {
  const allKeys = new Set([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ]);

  return Array.from(allKeys)
    .sort()
    .map((key) => {
      const bv = before?.[key];
      const av = after?.[key];
      const beforeNum = typeof bv === "number" ? bv : null;
      const afterNum = typeof av === "number" ? av : null;
      const delta =
        beforeNum !== null && afterNum !== null ? afterNum - beforeNum : null;
      return { key, before: beforeNum, after: afterNum, delta };
    });
}

function formatValue(v: number | null): string {
  if (v === null) return "—";
  // Round to 4 sig-figs for readability.
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (Math.abs(v) >= 1) return v.toFixed(3);
  return v.toFixed(4);
}

function deltaColor(key: string, delta: number | null): string {
  if (delta === null || delta === 0) return "text-muted-foreground";
  const higherBetter = HIGHER_IS_BETTER[key];
  if (higherBetter === undefined) return "text-muted-foreground";
  const improved = higherBetter ? delta > 0 : delta < 0;
  return improved ? "text-emerald-400" : "text-rose-400";
}

function deltaArrow(delta: number | null): string {
  if (delta === null || delta === 0) return "";
  return delta > 0 ? " ▲" : " ▼";
}

export interface MetricsDiffProps {
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

/**
 * Side-by-side diff visualiser for metrics_before vs metrics_after JSONB.
 *
 * - Union of keys from both blobs.
 * - Delta = after − before when both are numeric.
 * - Semantic coloring: green = improvement, red = regression, muted = neutral.
 * - Sharpe/PF/win_rate etc. → higher better; max_dd/drawdown → lower better.
 */
export function MetricsDiff({ before, after }: MetricsDiffProps) {
  if (!before && !after) {
    return (
      <p className="text-xs text-muted-foreground">
        No metrics recorded for this iteration.
      </p>
    );
  }

  const rows = buildRows(before, after);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border">
            <th className="pb-1 pr-4 text-left font-medium text-muted-foreground uppercase tracking-wide">
              Metric
            </th>
            <th className="pb-1 pr-4 text-right font-medium text-muted-foreground uppercase tracking-wide">
              Before
            </th>
            <th className="pb-1 pr-4 text-right font-medium text-muted-foreground uppercase tracking-wide">
              After
            </th>
            <th className="pb-1 text-right font-medium text-muted-foreground uppercase tracking-wide">
              Δ
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-border/50 last:border-0">
              <td className="py-1 pr-4 font-mono text-foreground">{row.key}</td>
              <td className="py-1 pr-4 text-right tabular-nums text-muted-foreground">
                {formatValue(row.before)}
              </td>
              <td className="py-1 pr-4 text-right tabular-nums text-foreground">
                {formatValue(row.after)}
              </td>
              <td
                className={cn(
                  "py-1 text-right tabular-nums",
                  deltaColor(row.key, row.delta),
                )}
              >
                {row.delta !== null
                  ? `${formatValue(row.delta)}${deltaArrow(row.delta)}`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
