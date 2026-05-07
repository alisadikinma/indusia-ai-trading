"use client";

// TanStack Query setup for the Bot Cockpit dashboard.
//
// HARD-FAIL on missing NEXT_PUBLIC_DASHBOARD_API_URL. No silent fallback —
// Iron Law 3 (Anti-placeholder). Server-rendered code paths import this
// module too; if the env var is absent we want the build/runtime to crash
// loudly rather than fetch from the wrong origin.

import {
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useQuery,
  type UseInfiniteQueryOptions,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";

import type {
  BacktestRunDetail,
  BacktestRunMeta,
  BrainJournalFilters,
  EquityPoint,
  FreqaiCalibration,
  FreqaiHistoryRow,
  FreqaiPredictionHistogram,
  IterationRun,
  JournalPage,
  OhlcvPoint,
  Position,
  RiskState,
} from "./api-types";

function requirePublicEnv(name: string): string {
  const value =
    name === "NEXT_PUBLIC_DASHBOARD_API_URL"
      ? process.env.NEXT_PUBLIC_DASHBOARD_API_URL
      : process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;
  if (!value || value.length === 0) {
    throw new Error(
      `Missing required public environment variable: ${name}. ` +
        "The Bot Cockpit refuses to start without an explicit dashboard API URL.",
    );
  }
  return value;
}

export const DASHBOARD_API_URL = requirePublicEnv("NEXT_PUBLIC_DASHBOARD_API_URL");

class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { searchParams?: Record<string, string | number | undefined> },
): Promise<T> {
  const url = new URL(path, DASHBOARD_API_URL);
  if (init?.searchParams) {
    for (const [k, v] of Object.entries(init.searchParams)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  const res = await fetch(url.toString(), {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // ignore
    }
    throw new ApiError(`Dashboard API ${res.status} on ${path}`, res.status, body);
  }
  return (await res.json()) as T;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: 1,
        staleTime: 15_000,
      },
    },
  });
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => createQueryClient(), []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// ---------------------------------------------------------------------------
// Typed query hooks — one per route.
// ---------------------------------------------------------------------------

type HookOpts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, "queryKey" | "queryFn">;

export function useOhlcv(
  params: { pair?: string; tf?: string; from?: string; to?: string; limit?: number },
  options?: HookOpts<OhlcvPoint[]>,
) {
  return useQuery<OhlcvPoint[], Error, OhlcvPoint[], readonly unknown[]>({
    queryKey: ["ohlcv", params],
    queryFn: () =>
      apiFetch<OhlcvPoint[]>("/dashboard/chart/ohlcv", { searchParams: params }),
    ...options,
  });
}

export function useJournal(
  params: {
    regime?: string;
    decision?: string;
    from?: string;
    to?: string;
    q?: string;
    page?: number;
    size?: number;
  },
  options?: HookOpts<JournalPage>,
) {
  return useQuery<JournalPage, Error, JournalPage, readonly unknown[]>({
    queryKey: ["journal", params],
    queryFn: () => apiFetch<JournalPage>("/dashboard/journal", { searchParams: params }),
    ...options,
  });
}

// Phase 1.5.F — Brain Journal browser hook. Supersedes useJournal for the
// dedicated /journal view (which adds the `outcome` filter + CSV export).
// Existing callers of useJournal (LiveChart, ReasoningSidebar) keep working.
export function useBrainJournal(
  args: { filters: BrainJournalFilters; page: number; size: number },
  options?: HookOpts<JournalPage>,
) {
  const { filters, page, size } = args;
  const searchParams: Record<string, string | number | undefined> = {
    page,
    size,
  };
  if (filters.regime && filters.regime.length > 0) searchParams.regime = filters.regime;
  if (filters.decision && filters.decision.length > 0)
    searchParams.decision = filters.decision;
  if (filters.outcome && filters.outcome.length > 0)
    searchParams.outcome = filters.outcome;
  if (filters.from) searchParams.from = filters.from;
  if (filters.to) searchParams.to = filters.to;
  if (filters.q && filters.q.trim().length > 0) searchParams.q = filters.q.trim();

  return useQuery<JournalPage, Error, JournalPage, readonly unknown[]>({
    queryKey: ["brain-journal", filters, page, size],
    queryFn: () =>
      apiFetch<JournalPage>("/dashboard/journal", { searchParams }),
    ...options,
  });
}

/**
 * Infinite-scroll variant of useBrainJournal.
 *
 * Journal grows ~3000 rows/day at 5-min cadence; a single 200-row fetch is
 * useless for Phase 6+ post-mortem. This hook paginates by `page` (1-indexed)
 * and returns `{ data: { pages: JournalPage[] }, fetchNextPage, hasNextPage,
 * isFetchingNextPage }`. The consumer flattens `pages` into entries and drives
 * `fetchNextPage()` from the virtualizer when the user scrolls near the end.
 */
type InfiniteHookOpts = Omit<
  UseInfiniteQueryOptions<
    JournalPage,
    Error,
    { pages: JournalPage[]; pageParams: number[] },
    readonly unknown[],
    number
  >,
  "queryKey" | "queryFn" | "getNextPageParam" | "initialPageParam"
>;

export function useBrainJournalInfinite(
  args: { filters: BrainJournalFilters; size: number },
  options?: InfiniteHookOpts,
) {
  const { filters, size } = args;

  return useInfiniteQuery<
    JournalPage,
    Error,
    { pages: JournalPage[]; pageParams: number[] },
    readonly unknown[],
    number
  >({
    queryKey: ["brain-journal-infinite", filters, size],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const searchParams: Record<string, string | number | undefined> = {
        page: pageParam as number,
        size,
      };
      if (filters.regime && filters.regime.length > 0)
        searchParams.regime = filters.regime;
      if (filters.decision && filters.decision.length > 0)
        searchParams.decision = filters.decision;
      if (filters.outcome && filters.outcome.length > 0)
        searchParams.outcome = filters.outcome;
      if (filters.from) searchParams.from = filters.from;
      if (filters.to) searchParams.to = filters.to;
      if (filters.q && filters.q.trim().length > 0)
        searchParams.q = filters.q.trim();
      return apiFetch<JournalPage>("/dashboard/journal", { searchParams });
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, p) => acc + p.items.length, 0);
      // No next page when:
      //  - server returned an empty page (defensive — shouldn't happen mid-list)
      //  - we've materialized everything the server reports as `total`
      if (lastPage.items.length === 0) return undefined;
      if (loaded >= lastPage.total) return undefined;
      return lastPage.page + 1;
    },
    ...options,
  });
}

/** Build the CSV export URL with the same filter contract as useBrainJournal. */
export function brainJournalCsvUrl(filters: BrainJournalFilters): string {
  const url = new URL("/dashboard/journal/export.csv", DASHBOARD_API_URL);
  if (filters.regime && filters.regime.length > 0)
    url.searchParams.set("regime", filters.regime);
  if (filters.decision && filters.decision.length > 0)
    url.searchParams.set("decision", filters.decision);
  if (filters.outcome && filters.outcome.length > 0)
    url.searchParams.set("outcome", filters.outcome);
  if (filters.from) url.searchParams.set("from", filters.from);
  if (filters.to) url.searchParams.set("to", filters.to);
  if (filters.q && filters.q.trim().length > 0)
    url.searchParams.set("q", filters.q.trim());
  return url.toString();
}

export function usePositions(options?: HookOpts<Position[]>) {
  return useQuery<Position[], Error, Position[], readonly unknown[]>({
    queryKey: ["positions"],
    queryFn: () => apiFetch<Position[]>("/dashboard/positions"),
    ...options,
  });
}

export function useEquity(
  params: { from?: string; to?: string; limit?: number },
  options?: HookOpts<EquityPoint[]>,
) {
  return useQuery<EquityPoint[], Error, EquityPoint[], readonly unknown[]>({
    queryKey: ["equity", params],
    queryFn: () => apiFetch<EquityPoint[]>("/dashboard/equity", { searchParams: params }),
    ...options,
  });
}

export function useBacktestRuns(options?: HookOpts<BacktestRunMeta[]>) {
  return useQuery<BacktestRunMeta[], Error, BacktestRunMeta[], readonly unknown[]>({
    queryKey: ["backtest-runs"],
    queryFn: () => apiFetch<BacktestRunMeta[]>("/dashboard/backtest/runs"),
    ...options,
  });
}

export function useBacktestRun(id: number | null, options?: HookOpts<BacktestRunDetail>) {
  return useQuery<BacktestRunDetail, Error, BacktestRunDetail, readonly unknown[]>({
    queryKey: ["backtest-run", id],
    queryFn: () => apiFetch<BacktestRunDetail>(`/dashboard/backtest/runs/${id}`),
    enabled: id != null,
    ...options,
  });
}

export function useFreqai(options?: HookOpts<FreqaiCalibration>) {
  return useQuery<FreqaiCalibration, Error, FreqaiCalibration, readonly unknown[]>({
    queryKey: ["freqai-calibration"],
    queryFn: () => apiFetch<FreqaiCalibration>("/dashboard/freqai/calibration"),
    ...options,
  });
}

export function useFreqaiHistory(options?: HookOpts<FreqaiHistoryRow[]>) {
  return useQuery<FreqaiHistoryRow[], Error, FreqaiHistoryRow[], readonly unknown[]>({
    queryKey: ["freqai-history"],
    queryFn: () => apiFetch<FreqaiHistoryRow[]>("/dashboard/freqai/history"),
    ...options,
  });
}

export function useFreqaiPredictions(
  args: { hours?: number },
  options?: HookOpts<FreqaiPredictionHistogram>,
) {
  const hours = args.hours ?? 24;
  return useQuery<FreqaiPredictionHistogram, Error, FreqaiPredictionHistogram, readonly unknown[]>({
    queryKey: ["freqai-predictions", hours],
    queryFn: () =>
      apiFetch<FreqaiPredictionHistogram>("/dashboard/freqai/predictions", {
        searchParams: { hours },
      }),
    ...options,
  });
}

export function useRisk(options?: HookOpts<RiskState>) {
  return useQuery<RiskState, Error, RiskState, readonly unknown[]>({
    queryKey: ["risk-state"],
    queryFn: () => apiFetch<RiskState>("/dashboard/risk/state"),
    ...options,
  });
}

export function useIterations(options?: HookOpts<IterationRun[]>) {
  return useQuery<IterationRun[], Error, IterationRun[], readonly unknown[]>({
    queryKey: ["iterations"],
    queryFn: () => apiFetch<IterationRun[]>("/dashboard/iteration-runs"),
    ...options,
  });
}

export { ApiError };
