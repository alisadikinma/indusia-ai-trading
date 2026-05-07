"use client";

import * as React from "react";

import type { FreqaiPredictionHistogram } from "@/lib/api-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface PredictionHistogramProps {
  data: FreqaiPredictionHistogram | undefined;
  isLoading: boolean;
  error: Error | null;
}

export function PredictionHistogram({ data, isLoading, error }: PredictionHistogramProps) {
  const maxCount = React.useMemo(
    () => Math.max(...(data?.bins.map((b) => b.count) ?? [1]), 1),
    [data],
  );

  const hasData = (data?.bins.length ?? 0) > 0;

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2 text-base font-semibold tracking-tight">
        Live prediction histogram
        {data !== undefined ? (
          <Badge variant="outline" data-testid="freqai-prediction-total">
            {data.total}
          </Badge>
        ) : null}
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          last {data?.hours ?? 24}h
        </span>
      </h2>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load prediction histogram: {error.message}
          </AlertDescription>
        </Alert>
      ) : isLoading && !data ? (
        <Skeleton className="h-[140px] w-full" />
      ) : !hasData ? (
        <Alert variant="muted">
          <AlertDescription>
            {data?.note
              ? data.note
              : "No prediction data yet."}
            {" "}The histogram appears once the Phase 6 oversight cron begins
            approving and resizing signals in{" "}
            <code className="font-mono text-xs">brain.signals</code>.
          </AlertDescription>
        </Alert>
      ) : (
        <div className="space-y-1">
          {data!.bins.map((bin) => {
            const pct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
            const label = `${bin.lo.toFixed(1)}–${bin.hi.toFixed(1)}`;
            return (
              <div key={label} className="flex items-center gap-2 text-sm">
                <span className="w-20 shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                  {label}
                </span>
                <div className="relative h-4 flex-1 overflow-hidden rounded-sm bg-muted">
                  <div
                    className="absolute left-0 top-0 h-full rounded-sm bg-emerald-600 transition-all"
                    style={{ width: `${pct}%` }}
                    aria-hidden
                  />
                </div>
                <span className="w-8 shrink-0 text-right font-mono text-xs tabular-nums">
                  {bin.count}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
