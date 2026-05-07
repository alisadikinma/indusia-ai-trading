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
  useQuery,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";

import type {
  BacktestRunDetail,
  BacktestRunMeta,
  EquityPoint,
  FreqaiCalibration,
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
