"use client";

import * as React from "react";

import {
  PHASE_9_GATES,
  type BacktestMetrics,
  type BacktestRunMeta,
} from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

interface GateResult {
  pass: boolean;
  observed: number | null;
  threshold: number;
  comparator: ">" | "<" | ">=";
  fmt: (v: number) => string;
}

function fmtNum(v: number, digits = 2): string {
  return v.toFixed(digits);
}

function fmtPct(v: number, digits = 2): string {
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtInt(v: number): string {
  return Math.round(v).toString();
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.length > 0) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function gateSharpe(m: BacktestMetrics): GateResult {
  const v = asNumber(m.sharpe);
  return {
    pass: v != null && v > PHASE_9_GATES.sharpe_min,
    observed: v,
    threshold: PHASE_9_GATES.sharpe_min,
    comparator: ">",
    fmt: (x) => fmtNum(x, 2),
  };
}

function gateMaxDd(m: BacktestMetrics): GateResult {
  const v = asNumber(m.max_dd);
  return {
    pass: v != null && v < PHASE_9_GATES.max_dd_max,
    observed: v,
    threshold: PHASE_9_GATES.max_dd_max,
    comparator: "<",
    fmt: (x) => fmtPct(x, 2),
  };
}

function gateProfitFactor(m: BacktestMetrics): GateResult {
  const v = asNumber(m.profit_factor);
  return {
    pass: v != null && v > PHASE_9_GATES.profit_factor_min,
    observed: v,
    threshold: PHASE_9_GATES.profit_factor_min,
    comparator: ">",
    fmt: (x) => fmtNum(x, 2),
  };
}

function gateTotalTrades(m: BacktestMetrics): GateResult {
  const v = asNumber(m.total_trades);
  return {
    pass: v != null && v >= PHASE_9_GATES.total_trades_min,
    observed: v,
    threshold: PHASE_9_GATES.total_trades_min,
    comparator: ">=",
    fmt: (x) => fmtInt(x),
  };
}

interface CellProps {
  result: GateResult;
}

function GateCell({ result }: CellProps) {
  const { pass, observed, fmt } = result;
  if (observed == null) {
    return <span className="font-mono text-muted-foreground">—</span>;
  }
  return (
    <span
      data-gate-pass={pass ? "true" : "false"}
      className={cn(
        "font-mono",
        pass ? "text-emerald-400" : "text-rose-400",
      )}
    >
      {fmt(observed)}
    </span>
  );
}

function NeutralCell({ value, fmt }: { value: number | null; fmt: (v: number) => string }) {
  if (value == null) {
    return <span className="font-mono text-muted-foreground">—</span>;
  }
  return <span className="font-mono">{fmt(value)}</span>;
}

export interface MetricsTableProps {
  runs: BacktestRunMeta[];
  className?: string;
}

/**
 * Per-fold metrics table. Color-codes each gate metric (green PASS / red
 * FAIL) against the Phase 9 thresholds (Iron Law 2):
 *
 *   sharpe > 1.5
 *   max_dd < 25%
 *   profit_factor > 1.4
 *   total_trades >= 100
 *
 * Rendered as one row per fold. Empty arr → "no metrics" notice.
 */
export function MetricsTable({ runs, className }: MetricsTableProps) {
  const sorted = React.useMemo(
    () => [...runs].sort((a, b) => a.fold_index - b.fold_index),
    [runs],
  );

  if (sorted.length === 0) {
    return (
      <div
        className={cn(
          "rounded-md border border-dashed border-border bg-muted/20 px-3 py-4 text-sm text-muted-foreground",
          className,
        )}
      >
        No metrics yet — Phase 9 walk-forward populates this table.
      </div>
    );
  }

  // Aggregate gate pass/fail across all folds — Iron Law 2 requires ALL folds
  // pass before live capital. Show the operator the consensus at a glance.
  const allFoldsPass = sorted.every((r) => {
    const m = r.metrics;
    return (
      gateSharpe(m).pass &&
      gateMaxDd(m).pass &&
      gateProfitFactor(m).pass &&
      gateTotalTrades(m).pass
    );
  });

  return (
    <section
      className={cn("flex flex-col gap-3", className)}
      aria-label="Per-fold backtest metrics"
    >
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Per-fold metrics
        </h3>
        <Badge variant={allFoldsPass ? "success" : "danger"}>
          Phase 9 gate {allFoldsPass ? "PASS" : "FAIL"}
        </Badge>
      </header>
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Fold</th>
              <th
                className="px-3 py-2 text-right"
                title="Sharpe ratio — gate: > 1.5"
              >
                Sharpe
              </th>
              <th
                className="px-3 py-2 text-right"
                title="Max drawdown — gate: < 25%"
              >
                MaxDD
              </th>
              <th
                className="px-3 py-2 text-right"
                title="Profit factor — gate: > 1.4"
              >
                PF
              </th>
              <th
                className="px-3 py-2 text-right"
                title="Total trades — gate: ≥ 100"
              >
                Trades
              </th>
              <th className="px-3 py-2 text-right">Win rate</th>
              <th className="px-3 py-2 text-right">Expectancy</th>
              <th className="px-3 py-2 text-center">Gate</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const m = r.metrics;
              const sharpe = gateSharpe(m);
              const maxDd = gateMaxDd(m);
              const pf = gateProfitFactor(m);
              const trades = gateTotalTrades(m);
              const winRate = asNumber(m.win_rate);
              const expectancy = asNumber(m.expectancy);
              const allPass =
                sharpe.pass && maxDd.pass && pf.pass && trades.pass;
              return (
                <tr
                  key={r.id}
                  className="border-b border-border last:border-0"
                  data-fold={r.fold_index}
                >
                  <td className="px-3 py-2 font-mono text-sm">
                    Fold {r.fold_index}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <GateCell result={sharpe} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <GateCell result={maxDd} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <GateCell result={pf} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <GateCell result={trades} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <NeutralCell
                      value={winRate}
                      fmt={(v) => fmtPct(v, 1)}
                    />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <NeutralCell
                      value={expectancy}
                      fmt={(v) => fmtNum(v, 4)}
                    />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Badge variant={allPass ? "success" : "danger"}>
                      {allPass ? "PASS" : "FAIL"}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Gate criteria (Iron Law 2): Sharpe &gt;{" "}
        {PHASE_9_GATES.sharpe_min}, MaxDD &lt;{" "}
        {(PHASE_9_GATES.max_dd_max * 100).toFixed(0)}%, PF &gt;{" "}
        {PHASE_9_GATES.profit_factor_min}, trades ≥{" "}
        {PHASE_9_GATES.total_trades_min}. ALL 5 folds must pass before live
        capital.
      </p>
    </section>
  );
}
