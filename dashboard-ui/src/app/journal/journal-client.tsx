"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

import {
  brainJournalCsvUrl,
  useBrainJournalInfinite,
} from "@/lib/api-client";
import { ErrorBoundary } from "@/components/error-boundary";
import type { BrainJournalFilters } from "@/lib/api-types";
import { JournalEntry } from "@/components/panels/JournalEntry";
import { JournalFilters } from "@/components/panels/JournalFilters";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const PAGE_SIZE = 200;
const ROW_ESTIMATE = 56; // collapsed row height ~56px; virtualizer corrects on measure
const SEARCH_DEBOUNCE_MS = 300;
// When the last visible row is within this many rows of the end of the
// loaded list, prefetch the next page. Tuned to keep scrolling smooth at
// virtualizer overscan=8.
const FETCH_AHEAD = 10;

/**
 * Brain Journal browser — Phase 1.5.F surface.
 *
 * Reads brain.brain_journal via /dashboard/journal. Append-only by Iron Law 5
 * (Postgres trigger), so this view is strictly read-only. Operator can filter,
 * search, expand entries, and export the filtered slice as CSV.
 *
 * Virtualization: TanStack Virtual renders only the visible window. With
 * 5-min cycles × 24h × N pairs the journal grows ~thousands of rows/day, and
 * post-mortem deep-dives need to scroll history without DOM-blowup.
 */
export function JournalClient() {
  // Filters live in component state. The hook re-fetches on filter change.
  const [filters, setFilters] = React.useState<BrainJournalFilters>({});
  // Debounced copy used for the actual fetch — avoids one API call per keystroke
  // on the search box.
  const [debouncedFilters, setDebouncedFilters] =
    React.useState<BrainJournalFilters>({});

  React.useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedFilters(filters);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [filters]);

  const {
    data,
    isLoading,
    error,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useBrainJournalInfinite({
    filters: debouncedFilters,
    size: PAGE_SIZE,
  });

  // Flatten the page envelopes into one entries array. The virtualizer below
  // only renders the visible window, so this stays cheap even at 10k+ rows.
  const items = React.useMemo(
    () => (data?.pages ?? []).flatMap((p) => p.items),
    [data],
  );
  // `total` reflects the full filtered set on the server — same on every page.
  const total = data?.pages?.[0]?.total ?? 0;

  const [expandedId, setExpandedId] = React.useState<number | null>(null);

  // Virtualizer.
  const parentRef = React.useRef<HTMLDivElement>(null);
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_ESTIMATE,
    overscan: 8,
    // Re-measure whenever the expanded id flips, so an expanded card grows.
    measureElement: (el) =>
      el?.getBoundingClientRect().height ?? ROW_ESTIMATE,
  });

  React.useEffect(() => {
    rowVirtualizer.measure();
  }, [expandedId, rowVirtualizer]);

  // Drive fetchNextPage from the virtualizer: when the last virtual item is
  // within FETCH_AHEAD rows of the loaded length, request the next page.
  const virtualItems = rowVirtualizer.getVirtualItems();
  const lastVisibleIndex =
    virtualItems.length > 0
      ? virtualItems[virtualItems.length - 1].index
      : -1;
  React.useEffect(() => {
    if (lastVisibleIndex < 0) return;
    if (
      lastVisibleIndex >= items.length - FETCH_AHEAD &&
      hasNextPage &&
      !isFetchingNextPage
    ) {
      fetchNextPage();
    }
  }, [
    lastVisibleIndex,
    items.length,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ]);

  const [exportError, setExportError] = React.useState<string | null>(null);

  const handleExportCsv = React.useCallback(async () => {
    setExportError(null);
    const url = brainJournalCsvUrl(debouncedFilters);
    try {
      const res = await fetch(url, {
        credentials: "include",
        headers: { Accept: "text/csv" },
      });
      if (!res.ok) {
        throw new Error(`Export failed: ${res.status}`);
      }
      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = "brain_journal.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Defer revoke so the click has time to start the download.
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setExportError(message);
    }
  }, [debouncedFilters]);

  const isFirstLoad = isLoading && !data;

  return (
    <ErrorBoundary viewName="Brain Journal">
    <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
      {/* Header: stacks on sm, row on md+ */}
      <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Brain Journal
          </h1>
          <p className="text-sm text-muted-foreground">
            Append-only audit log of every decision Claude has logged
            (regime, decision, reasoning, confidence, outcome).
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="outline" data-testid="journal-total-count">
            {total} entries
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={handleExportCsv}
            disabled={isFirstLoad}
          >
            Export CSV
          </Button>
        </div>
      </header>

      <Card className="mb-4">
        <CardContent className="p-4">
          <JournalFilters value={filters} onChange={setFilters} />
        </CardContent>
      </Card>

      {exportError ? (
        <Alert variant="destructive" className="mb-3">
          <AlertDescription>
            CSV export failed: {exportError}
          </AlertDescription>
        </Alert>
      ) : null}

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>
            Failed to load journal: {error.message}
          </AlertDescription>
        </Alert>
      ) : isFirstLoad ? (
        <Card>
          <CardContent className="p-4">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="mt-3 h-32 w-full" />
          </CardContent>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-6">
            <Alert variant="muted">
              <AlertDescription>
                Brain Journal is empty for the current filter. The journal is
                populated by the Phase 6 oversight routine when the brain
                starts logging decisions — until then this table only shows
                rows seeded by tests or manual inserts. See{" "}
                <a
                  className="underline"
                  href="/docs/plans/2026-05-06-ai-trading-247.md"
                >
                  the plan
                </a>{" "}
                for the cron schedule.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            {/* Single overflow-x-auto container wraps BOTH the column-header
                strip and the virtualized body so they scroll horizontally
                together on <640px viewports. The virtualized body keeps its
                own overflow-y-auto for vertical scrolling (TanStack Virtual
                requires a scrollable element for parentRef). */}
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <div className="grid grid-cols-12 gap-3 border-b border-border bg-muted/30 px-4 py-2 pl-12 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <span className="col-span-3">Timestamp</span>
                  <span className="col-span-2">Regime</span>
                  <span className="col-span-1">Decision</span>
                  <span className="col-span-1">Conf.</span>
                  <span className="col-span-4">Reasoning</span>
                  <span className="col-span-1 justify-self-end">Outcome</span>
                </div>

                <div
                  ref={parentRef}
                  className="relative max-h-[70vh] overflow-y-auto"
                  data-testid="journal-virtual-scroll"
                >
                  <div
                    style={{
                      height: `${rowVirtualizer.getTotalSize()}px`,
                      position: "relative",
                      width: "100%",
                    }}
                  >
                    {rowVirtualizer.getVirtualItems().map((vi) => {
                      const entry = items[vi.index];
                      return (
                        <div
                          key={entry.id}
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
                          <JournalEntry
                            entry={entry}
                            expanded={expandedId === entry.id}
                            onToggle={() =>
                              setExpandedId((prev) =>
                                prev === entry.id ? null : entry.id,
                              )
                            }
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>

                {isFetchingNextPage ? (
                  <div
                    className="border-t border-border px-4 py-2 text-xs text-muted-foreground"
                    data-testid="journal-loading-more"
                  >
                    Loading older entries…
                  </div>
                ) : isFetching && !isFirstLoad ? (
                  <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
                    Refreshing…
                  </div>
                ) : !hasNextPage && items.length > 0 ? (
                  <div
                    className="border-t border-border px-4 py-2 text-xs text-muted-foreground"
                    data-testid="journal-end-of-list"
                  >
                    End of journal — {items.length} of {total} entries loaded.
                  </div>
                ) : null}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </main>
    </ErrorBoundary>
  );
}
