"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useOhlcv, usePositions } from "@/lib/api-client";
import { useDashboardWs } from "@/lib/ws-client";
import type { OhlcvPoint, Position } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

function fmtUsd(v: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(v);
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function timeHeld(decidedAt: string): string {
  const then = new Date(decidedAt).getTime();
  const diff = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400)
    return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`;
  return `${Math.floor(diff / 86400)}d ${Math.floor((diff % 86400) / 3600)}h`;
}

interface RowMetrics {
  currentPrice: number | null;
  unrealizedUsd: number | null;
  unrealizedPct: number | null;
}

function computeMetrics(
  position: Position,
  ohlcv: OhlcvPoint[] | undefined,
): RowMetrics {
  if (!ohlcv || ohlcv.length === 0) {
    return { currentPrice: null, unrealizedUsd: null, unrealizedPct: null };
  }
  const last = ohlcv[ohlcv.length - 1].close;
  const entry = position.price_at_signal;
  const sizeMult = position.intended_size_mult ?? 1.0;
  // Notional size proxy: 1 unit * sizeMult. Real PnL needs trade.amount once
  // public.trades is wired in Phase 3 — until then this is the best signal-side
  // approximation, computed from real OHLCV close.
  const direction = position.side === "short" ? -1 : 1;
  const pctDelta = ((last - entry) / entry) * direction * 100;
  const usdDelta = (last - entry) * direction * sizeMult;
  return {
    currentPrice: last,
    unrealizedUsd: usdDelta,
    unrealizedPct: pctDelta,
  };
}

function PositionRow({ position }: { position: Position }) {
  // Pull last close for this pair to compute current price + PnL.
  const { data: ohlcv } = useOhlcv(
    { pair: position.pair, tf: "1m", limit: 1 },
    { staleTime: 10_000 },
  );
  const metrics = computeMetrics(position, ohlcv);
  const positive = (metrics.unrealizedPct ?? 0) > 0;
  const negative = (metrics.unrealizedPct ?? 0) < 0;

  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-3 py-2 font-mono text-sm">{position.pair}</td>
      <td className="px-3 py-2">
        <Badge
          variant={
            position.side === "long"
              ? "success"
              : position.side === "short"
                ? "danger"
                : "secondary"
          }
        >
          {position.side}
        </Badge>
      </td>
      <td className="px-3 py-2 text-right font-mono text-sm">
        {fmtUsd(position.price_at_signal)}
      </td>
      <td className="px-3 py-2 text-right font-mono text-sm">
        {metrics.currentPrice == null
          ? "—"
          : fmtUsd(metrics.currentPrice)}
      </td>
      <td className="px-3 py-2 text-right font-mono text-sm">
        {position.intended_size_mult == null
          ? "1.00x"
          : `${position.intended_size_mult.toFixed(2)}x`}
      </td>
      <td
        className={cn(
          "px-3 py-2 text-right font-mono text-sm",
          positive && "text-emerald-400",
          negative && "text-rose-400",
        )}
      >
        {metrics.unrealizedUsd == null
          ? "—"
          : `${fmtUsd(metrics.unrealizedUsd)} (${fmtPct(metrics.unrealizedPct ?? 0)})`}
      </td>
      <td className="px-3 py-2 text-right font-mono text-sm text-muted-foreground">
        {timeHeld(position.decided_at)}
      </td>
    </tr>
  );
}

export interface OpenPositionsProps {
  className?: string;
  wsToken: string | null;
}

export function OpenPositions({ className, wsToken }: OpenPositionsProps) {
  const { data, isLoading, error } = usePositions();
  const queryClient = useQueryClient();
  const { lastMessage } = useDashboardWs(["dashboard_signals"], wsToken);

  React.useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.channel !== "dashboard_signals") return;
    queryClient.invalidateQueries({ queryKey: ["positions"] });
  }, [lastMessage, queryClient]);

  const positions = data ?? [];

  return (
    <section
      className={cn("flex h-full flex-col", className)}
      aria-label="Open positions"
    >
      <header className="flex items-center justify-between gap-3 px-1 pb-3">
        <h2 className="text-lg font-semibold tracking-tight">Open Positions</h2>
        <span className="text-xs text-muted-foreground">
          {positions.length} open
        </span>
      </header>
      <div className="overflow-auto rounded-md border border-border">
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load positions: {error.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {isLoading && !data ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-full" />
          </div>
        ) : null}
        {!isLoading && !error && positions.length === 0 ? (
          <Alert variant="muted" className="m-0 rounded-none border-0">
            <AlertDescription>No open positions.</AlertDescription>
          </Alert>
        ) : null}
        {positions.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Pair</th>
                <th className="px-3 py-2 text-left">Side</th>
                <th className="px-3 py-2 text-right">Entry</th>
                <th className="px-3 py-2 text-right">Last</th>
                <th className="px-3 py-2 text-right">Size</th>
                <th className="px-3 py-2 text-right">P/L</th>
                <th className="px-3 py-2 text-right">Held</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <PositionRow key={p.signal_id} position={p} />
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}
