"use client";

import * as React from "react";

import { useBacktestRun, useBacktestRuns } from "@/lib/api-client";
import type { BacktestRunMeta } from "@/lib/api-types";
import { BacktestChart } from "@/components/charts/BacktestChart";
import { MetricsTable } from "@/components/panels/MetricsTable";
import { ParameterSetSelector } from "@/components/panels/ParameterSetSelector";
import { FoldNavigator } from "@/components/panels/FoldNavigator";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

function groupRunsByStrategyVersion(
  runs: BacktestRunMeta[],
): Map<string, BacktestRunMeta[]> {
  const out = new Map<string, BacktestRunMeta[]>();
  for (const r of runs) {
    const key = r.strategy_version;
    const list = out.get(key);
    if (list) {
      list.push(r);
    } else {
      out.set(key, [r]);
    }
  }
  return out;
}

export function StrategyLabClient() {
  const { data: runs, isLoading: runsLoading, error: runsError } =
    useBacktestRuns();

  const grouped = React.useMemo(
    () => groupRunsByStrategyVersion(runs ?? []),
    [runs],
  );
  const strategyVersions = React.useMemo(
    () => Array.from(grouped.keys()).sort(),
    [grouped],
  );

  // Operator-initiated overrides; null means "use default (first version /
  // first fold)". Avoids setState-in-effect cascades — the effective values
  // are derived per render.
  const [versionOverride, setVersionOverride] = React.useState<string | null>(
    null,
  );
  const [runIdOverride, setRunIdOverride] = React.useState<number | null>(null);

  const effectiveVersion: string | null = React.useMemo(() => {
    if (versionOverride && grouped.has(versionOverride)) return versionOverride;
    return strategyVersions[0] ?? null;
  }, [versionOverride, grouped, strategyVersions]);

  const versionRuns = React.useMemo(
    () => (effectiveVersion ? (grouped.get(effectiveVersion) ?? []) : []),
    [grouped, effectiveVersion],
  );

  const effectiveRunId: number | null = React.useMemo(() => {
    if (runIdOverride && versionRuns.some((r) => r.id === runIdOverride)) {
      return runIdOverride;
    }
    const firstFold = versionRuns
      .slice()
      .sort((a, b) => a.fold_index - b.fold_index)[0];
    return firstFold ? firstFold.id : null;
  }, [runIdOverride, versionRuns]);

  const { data: detail, isLoading: detailLoading } = useBacktestRun(
    effectiveRunId,
  );

  const isLoadingRuns = runsLoading && !runs;
  const isEmpty = !isLoadingRuns && (runs?.length ?? 0) === 0;

  return (
    <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Strategy Lab
          </h1>
          <p className="text-sm text-muted-foreground">
            Walk-forward backtest viewer + hyperopt parameter comparison
            (Phase 9 / Phase 8 surface).
          </p>
        </div>
        {!isEmpty && !isLoadingRuns ? (
          <div className="flex items-center gap-3">
            <Label htmlFor="strategy-version-select" className="text-xs uppercase tracking-wide text-muted-foreground">
              Strategy version
            </Label>
            <Select
              id="strategy-version-select"
              value={effectiveVersion ?? ""}
              onChange={(e) => {
                setVersionOverride(e.target.value);
                // Reset fold override so the first fold of the new version
                // is auto-selected next render.
                setRunIdOverride(null);
              }}
              className="h-8 w-48"
            >
              {strategyVersions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </Select>
            <Badge variant="outline">{runs?.length ?? 0} runs</Badge>
          </div>
        ) : null}
      </header>

      {runsError ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load backtest runs: {runsError.message}
          </AlertDescription>
        </Alert>
      ) : isLoadingRuns ? (
        <Card>
          <CardContent className="p-4">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="mt-4 h-64 w-full" />
          </CardContent>
        </Card>
      ) : isEmpty ? (
        <Card>
          <CardContent className="p-6">
            <Alert variant="muted">
              <AlertDescription>
                No backtests yet. The brain.backtest_runs table populates
                after Phase 9 walk-forward orchestrator (or Phase 8 hyperopt
                sweeps) runs. See{" "}
                <a
                  className="underline"
                  href="/docs/plans/2026-05-06-ai-trading-247.md"
                >
                  the plan
                </a>{" "}
                for the gate criteria.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left column — chart + fold tabs + metrics */}
          <div className="flex flex-col gap-4 lg:col-span-8">
            <Card>
              <CardContent className="space-y-3 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm font-medium">Walk-forward</span>
                  <FoldNavigator
                    runs={versionRuns}
                    selectedRunId={effectiveRunId}
                    onSelect={setRunIdOverride}
                  />
                </div>
                <BacktestChart
                  detail={detail ?? null}
                  isLoading={detailLoading && !detail}
                />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <MetricsTable runs={versionRuns} />
              </CardContent>
            </Card>
          </div>

          {/* Right column — parameter set comparison */}
          <Card className="lg:col-span-4">
            <CardContent className="p-4">
              <ParameterSetSelector runs={versionRuns} />
            </CardContent>
          </Card>
        </div>
      )}
    </main>
  );
}
