"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import { useIterations } from "@/lib/api-client";
import type { IterationFilters } from "@/lib/api-types";
import { IterationCard } from "@/components/panels/IterationCard";
import { IterationFilters as IterationFiltersBar } from "@/components/panels/IterationFilters";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const ROW_ESTIMATE = 72; // collapsed card height estimate; virtualizer corrects on measure

/**
 * Iteration History browser — Phase 1.5.G2 surface.
 *
 * Reads brain.iteration_runs via /dashboard/iteration-runs. Displays a
 * timeline of Phase 9.5 iteration cycles, post-mortem runs, and health
 * checks. Each card expands to reveal the metrics diff visualiser.
 *
 * Data is empty until Phase 9.5 fires (iteration cycles) or Phase 6 cron
 * fires (post-mortem / health_check rows). The empty-state copy explains
 * this so the operator knows the state is correct, not a bug.
 */
export function IterationHistoryClient() {
  const [filters, setFilters] = React.useState<IterationFilters>({});

  const { data: items, isLoading, error } = useIterations(filters);

  const [expandedId, setExpandedId] = React.useState<number | null>(null);

  const runs = items ?? [];

  // Virtualizer — iteration history is bounded (≤200 rows per fetch, Phase 9.5
  // max 3 cycles × bots) but we virtualise for consistency with the journal.
  const parentRef = React.useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: runs.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_ESTIMATE,
    overscan: 5,
    measureElement: (el) =>
      el?.getBoundingClientRect().height ?? ROW_ESTIMATE,
  });

  React.useEffect(() => {
    rowVirtualizer.measure();
  }, [expandedId, rowVirtualizer]);

  const isFirstLoad = isLoading && !items;

  return (
    <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Iteration History
          </h1>
          <p className="text-sm text-muted-foreground">
            Walk-forward iteration loop ledger (Phase 9.5) — wins, losses, and
            ADRs per cycle. Also shows Phase 6 post-mortem and health-check runs.
          </p>
        </div>
        <Badge variant="outline" data-testid="iteration-total-count">
          {runs.length} runs
        </Badge>
      </header>

      <Card className="mb-4">
        <CardContent className="p-4">
          <IterationFiltersBar value={filters} onChange={setFilters} />
        </CardContent>
      </Card>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load iteration runs: {error.message}
          </AlertDescription>
        </Alert>
      ) : isFirstLoad ? (
        <Card>
          <CardContent className="p-4">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="mt-3 h-24 w-full" />
          </CardContent>
        </Card>
      ) : runs.length === 0 ? (
        <Card>
          <CardContent className="p-6">
            <Alert variant="muted">
              <AlertDescription>
                No iteration runs found for the current filter. This table is
                populated by two automated crons:
                <ul className="mt-2 list-inside list-disc text-sm">
                  <li>
                    <strong>Phase 6 post-mortem cron</strong> — weekly
                    post-mortem analysis and daily retrain health checks
                    (run_type: <code>post_mortem</code>,{" "}
                    <code>health_check</code>).
                  </li>
                  <li>
                    <strong>Phase 9.5 iteration loop</strong> — triggered when
                    the walk-forward backtest fails a gate criterion. Up to 3
                    cycles before architectural rethink (run_type:{" "}
                    <code>iteration</code>).
                  </li>
                </ul>
                Until those crons fire, this view will remain empty. See the{" "}
                <a
                  className="underline"
                  href="/docs/plans/2026-05-06-ai-trading-247.md"
                >
                  implementation plan
                </a>{" "}
                for Phase 9.5 gate criteria.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div
              ref={parentRef}
              className="relative max-h-[75vh] overflow-auto"
              data-testid="iteration-virtual-scroll"
            >
              <div
                style={{
                  height: `${rowVirtualizer.getTotalSize()}px`,
                  position: "relative",
                  width: "100%",
                }}
              >
                {rowVirtualizer.getVirtualItems().map((vi) => {
                  const run = runs[vi.index];
                  return (
                    <div
                      key={run.id}
                      data-index={vi.index}
                      ref={rowVirtualizer.measureElement}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        right: 0,
                        transform: `translateY(${vi.start}px)`,
                      }}
                    >
                      <IterationCard
                        run={run}
                        expanded={expandedId === run.id}
                        onToggle={() =>
                          setExpandedId((prev) =>
                            prev === run.id ? null : run.id,
                          )
                        }
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
