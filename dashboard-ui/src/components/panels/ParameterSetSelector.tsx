"use client";

import * as React from "react";

import type { BacktestRunDetail, BacktestRunMeta } from "@/lib/api-types";
import { useBacktestRun } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * Stable hash of a parameter set so multiple runs with identical parameters
 * collapse into one "set" for top-3 comparison. Object key order is sorted
 * for determinism.
 */
function hashParameters(p: Record<string, unknown>): string {
  const sortedKeys = Object.keys(p).sort();
  const normalised: Record<string, unknown> = {};
  for (const k of sortedKeys) normalised[k] = p[k];
  return JSON.stringify(normalised);
}

interface ParameterSetCandidate {
  hash: string;
  parameters: Record<string, unknown>;
  /** Mean Sharpe across all folds for this parameter set. */
  meanSharpe: number;
  /** Sample run id we'll fetch detail for (lowest fold_index). */
  representativeRunId: number;
  foldCount: number;
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}

function buildCandidates(
  runs: BacktestRunMeta[],
  details: Map<number, BacktestRunDetail>,
): ParameterSetCandidate[] {
  const groups = new Map<
    string,
    {
      parameters: Record<string, unknown>;
      sharpes: number[];
      runs: BacktestRunMeta[];
    }
  >();

  for (const r of runs) {
    const detail = details.get(r.id);
    if (!detail || !detail.parameters) continue;
    const hash = hashParameters(detail.parameters);
    const sharpe = asNumber(r.metrics.sharpe);
    if (sharpe == null) continue;
    const existing = groups.get(hash);
    if (existing) {
      existing.sharpes.push(sharpe);
      existing.runs.push(r);
    } else {
      groups.set(hash, {
        parameters: detail.parameters,
        sharpes: [sharpe],
        runs: [r],
      });
    }
  }

  // Compute representative AFTER all runs are grouped — pick the run with the
  // minimum fold_index in this set. Avoids the arrival-order bug where
  // comparing against runs[0] (the first inserted, not the current min) lets
  // a later mid-fold run wrongly overwrite an earlier-fold representative.
  return Array.from(groups.entries())
    .map(([hash, g]) => {
      const minRun = g.runs.reduce(
        (min, r) => (r.fold_index < min.fold_index ? r : min),
        g.runs[0],
      );
      return {
        hash,
        parameters: g.parameters,
        meanSharpe:
          g.sharpes.reduce((a, b) => a + b, 0) / g.sharpes.length,
        representativeRunId: minRun.id,
        foldCount: g.runs.length,
      };
    })
    .sort((a, b) => b.meanSharpe - a.meanSharpe);
}

interface ParameterCardProps {
  candidate: ParameterSetCandidate;
  rank: number;
}

function formatParamValue(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number")
    return Number.isInteger(v) ? v.toString() : v.toFixed(4);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

function ParameterCard({ candidate, rank }: ParameterCardProps) {
  const entries = Object.entries(candidate.parameters);
  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border bg-card p-3"
      data-rank={rank}
    >
      <header className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Rank #{rank}
        </span>
        <Badge variant="outline" className="font-mono">
          Sharpe {candidate.meanSharpe.toFixed(2)}
        </Badge>
      </header>
      <span className="text-[10px] text-muted-foreground">
        {candidate.foldCount} fold{candidate.foldCount === 1 ? "" : "s"}
      </span>
      <dl className="grid grid-cols-1 gap-1 text-xs">
        {entries.length === 0 ? (
          <div className="text-muted-foreground">No parameters recorded.</div>
        ) : (
          entries.map(([k, v]) => (
            <div
              key={k}
              className="flex items-center justify-between gap-2 border-b border-border/50 py-1 last:border-0"
            >
              <dt className="font-mono text-muted-foreground">{k}</dt>
              <dd className="truncate font-mono">{formatParamValue(v)}</dd>
            </div>
          ))
        )}
      </dl>
    </div>
  );
}

/** Internal: fetches one detail and forwards it via the onLoaded callback. */
function DetailLoader({
  runId,
  onLoaded,
}: {
  runId: number;
  onLoaded: (id: number, detail: BacktestRunDetail) => void;
}) {
  const { data } = useBacktestRun(runId);
  React.useEffect(() => {
    if (data) onLoaded(runId, data);
  }, [data, runId, onLoaded]);
  return null;
}

export interface ParameterSetSelectorProps {
  runs: BacktestRunMeta[];
  className?: string;
}

/**
 * Top-3 hyperopt parameter sets ranked by mean Sharpe across folds. Each run
 * is fetched once via /dashboard/backtest/runs/{id} (TanStack Query handles
 * caching). If Phase 8 hasn't populated parameter sets yet, render an empty
 * state pointing to docs.
 *
 * Iron Law 3 — empty state is REAL (driven by the size of the runs array
 * from Postgres), not a placeholder.
 */
export function ParameterSetSelector({
  runs,
  className,
}: ParameterSetSelectorProps) {
  const [details, setDetails] = React.useState<Map<number, BacktestRunDetail>>(
    () => new Map(),
  );

  const handleLoaded = React.useCallback(
    (id: number, detail: BacktestRunDetail) => {
      setDetails((prev) => {
        if (prev.has(id)) return prev;
        const next = new Map(prev);
        next.set(id, detail);
        return next;
      });
    },
    [],
  );

  // Stable key for the current runs collection — drives the cache-reset
  // effect below and is exposed as `data-runids` for e2e debugging.
  const runIdsKey = React.useMemo(
    () => runs.map((r) => r.id).join(","),
    [runs],
  );

  // Reset cached run details when the runs collection identity changes,
  // so a stale detail from a previous strategy version can never leak
  // into the candidate set for a different run set.
  React.useEffect(() => {
    setDetails(new Map());
  }, [runIdsKey]);

  const candidates = React.useMemo(
    () => buildCandidates(runs, details),
    [runs, details],
  );

  const top3 = candidates.slice(0, 3);
  const allDetailsLoaded = runs.every((r) => details.has(r.id));

  if (runs.length === 0) {
    return (
      <Alert variant="muted" className={className}>
        <AlertDescription>
          No backtest runs to compare yet. Phase 8 populates parameter sets
          via hyperopt sweeps; until then this panel is empty.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <section
      className={cn("flex flex-col gap-3", className)}
      aria-label="Parameter set comparison"
      data-runids={runIdsKey}
    >
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Top-3 parameter sets
        </h3>
        <span className="text-xs text-muted-foreground">
          {candidates.length} unique
        </span>
      </header>
      {/* Hidden loaders fetch each run's detail once. */}
      {runs
        .filter((r) => !details.has(r.id))
        .map((r) => (
          <DetailLoader key={r.id} runId={r.id} onLoaded={handleLoaded} />
        ))}
      {!allDetailsLoaded && top3.length === 0 ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : null}
      {top3.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {top3.map((c, idx) => (
            <ParameterCard key={c.hash} candidate={c} rank={idx + 1} />
          ))}
        </div>
      ) : null}
      {allDetailsLoaded && top3.length === 0 ? (
        <Alert variant="muted">
          <AlertDescription>
            No parameter sets with finite Sharpe to rank yet.
          </AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
