"use client";

import * as React from "react";

import type { FreqaiCalibration } from "@/lib/api-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const TOP_N = 20;

interface FeatureImportanceProps {
  data: FreqaiCalibration | undefined;
  isLoading: boolean;
  error: Error | null;
}

export function FeatureImportance({ data, isLoading, error }: FeatureImportanceProps) {
  const sorted = React.useMemo(() => {
    if (!data?.feature_importance) return [];
    return Object.entries(data.feature_importance)
      .map(([name, value]) => ({ name, value: Number(value) }))
      .sort((a, b) => b.value - a.value)
      .slice(0, TOP_N);
  }, [data]);

  const maxValue = sorted.length > 0 ? sorted[0].value : 1;

  return (
    <section>
      <h2 className="mb-3 text-base font-semibold tracking-tight">Feature importance</h2>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load feature importance: {error.message}
          </AlertDescription>
        </Alert>
      ) : isLoading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-5 w-full" />
          ))}
        </div>
      ) : sorted.length === 0 ? (
        <Alert variant="muted">
          <AlertDescription>
            Feature importance not yet available. It is recorded into{" "}
            <code className="font-mono text-xs">brain.freqai_history.feature_importance</code>{" "}
            after each Phase 7 XGBoost retrain.
          </AlertDescription>
        </Alert>
      ) : (
        <ol className="space-y-1.5" aria-label="Top feature importances">
          {sorted.map(({ name, value }) => {
            const pct = maxValue > 0 ? (value / maxValue) * 100 : 0;
            return (
              <li key={name} className="flex items-center gap-2 text-sm">
                <span
                  className="w-44 shrink-0 truncate font-mono text-xs text-foreground"
                  title={name}
                >
                  {name}
                </span>
                <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-muted">
                  <div
                    className={cn(
                      "absolute left-0 top-0 h-full rounded-sm bg-indigo-500 transition-all",
                    )}
                    style={{ width: `${pct}%` }}
                    aria-hidden
                  />
                </div>
                <span className="w-16 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {value.toFixed(4)}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
