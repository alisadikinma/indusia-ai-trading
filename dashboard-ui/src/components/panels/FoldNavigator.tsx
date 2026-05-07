"use client";

import * as React from "react";

import type { BacktestRunMeta } from "@/lib/api-types";
import { cn } from "@/lib/utils";

export interface FoldNavigatorProps {
  /** Runs in the currently-selected strategy version. */
  runs: BacktestRunMeta[];
  /** ID of the currently-selected run, if any. */
  selectedRunId: number | null;
  /** Notify parent that operator clicked a fold tab. */
  onSelect: (runId: number) => void;
  className?: string;
}

/**
 * Fold 1/2/3/4/5 navigator. Walk-forward by convention emits exactly 5 OOS
 * folds; if the runs collection has more or fewer (e.g. partial backtest in
 * progress, or a non-walk-forward sweep), we render whatever fold_index
 * values exist — never fabricate placeholders.
 */
export function FoldNavigator({
  runs,
  selectedRunId,
  onSelect,
  className,
}: FoldNavigatorProps) {
  // Sort by fold_index for stable left-to-right order.
  const sorted = React.useMemo(
    () => [...runs].sort((a, b) => a.fold_index - b.fold_index),
    [runs],
  );

  if (sorted.length === 0) {
    return (
      <div
        className={cn(
          "rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground",
          className,
        )}
      >
        No folds in this strategy version yet.
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-md border border-border bg-input p-0.5",
        className,
      )}
      role="tablist"
      aria-label="Walk-forward fold"
    >
      {sorted.map((r) => {
        const active = r.id === selectedRunId;
        const passed = r.gate_passed;
        return (
          <button
            key={r.id}
            type="button"
            role="tab"
            aria-selected={active}
            data-active={active ? "true" : "false"}
            data-fold={r.fold_index}
            onClick={() => onSelect(r.id)}
            className={cn(
              "flex items-center gap-1.5 rounded px-3 py-1 text-xs font-medium transition-colors",
              active
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <span>Fold {r.fold_index}</span>
            <span
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                passed ? "bg-emerald-500" : "bg-rose-500",
              )}
              aria-label={passed ? "PASS" : "FAIL"}
            />
          </button>
        );
      })}
    </div>
  );
}
