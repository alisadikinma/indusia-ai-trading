"use client";

import * as React from "react";

import type { FreqaiHistoryRow } from "@/lib/api-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

function basename(path: string): string {
  // Cross-platform — handles both '/' and '\' separators.
  return path.replace(/.*[\\/]/, "");
}

function fmtDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

interface RetrainHistoryProps {
  data: FreqaiHistoryRow[] | undefined;
  isLoading: boolean;
  error: Error | null;
}

export function RetrainHistory({ data, isLoading, error }: RetrainHistoryProps) {
  return (
    <section>
      <h2 className="mb-3 text-base font-semibold tracking-tight">Retrain history</h2>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load retrain history: {error.message}
          </AlertDescription>
        </Alert>
      ) : isLoading && !data ? (
        <div className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
        </div>
      ) : !data || data.length === 0 ? (
        <Alert variant="muted">
          <AlertDescription>
            No retrain records yet. Phase 7 daily retrain cron inserts a row
            into{" "}
            <code className="font-mono text-xs">brain.freqai_history</code>{" "}
            after each XGBoost model fit.
          </AlertDescription>
        </Alert>
      ) : (
        <div className="overflow-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Retrained at</th>
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">TF</th>
                <th className="px-3 py-2 text-right">Train rows</th>
                <th className="px-3 py-2 text-right">AUC</th>
                <th className="px-3 py-2 text-left">Model</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                    {fmtDate(row.retrained_at)}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{row.pair}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.tf}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">
                    {row.train_rows.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">
                    {row.auc.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground" title={row.model_path}>
                    {basename(row.model_path)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
