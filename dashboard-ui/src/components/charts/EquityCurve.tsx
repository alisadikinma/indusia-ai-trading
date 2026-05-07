"use client";

import * as React from "react";
import {
  AreaSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";

import { useEquity } from "@/lib/api-client";
import type { EquityPoint } from "@/lib/api-types";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

interface ChartHandles {
  chart: IChartApi;
  equity: ISeriesApi<"Line">;
  drawdown: ISeriesApi<"Area">;
  cleanup: () => void;
}

function createEquityChart(container: HTMLDivElement): ChartHandles {
  const chart = createChart(container, {
    layout: { background: { color: "#0b0b10" }, textColor: "#ededed" },
    grid: {
      vertLines: { color: "#1f1f2a" },
      horzLines: { color: "#1f1f2a" },
    },
    rightPriceScale: { borderColor: "#232331" },
    leftPriceScale: { borderColor: "#232331", visible: true },
    timeScale: {
      borderColor: "#232331",
      timeVisible: true,
      secondsVisible: false,
    },
    autoSize: true,
  });
  const equity = chart.addSeries(LineSeries, {
    color: "#10b981",
    lineWidth: 2,
    priceScaleId: "right",
    title: "Equity USD",
  });
  const drawdown = chart.addSeries(AreaSeries, {
    topColor: "rgba(244, 63, 94, 0.25)",
    bottomColor: "rgba(244, 63, 94, 0.0)",
    lineColor: "rgba(244, 63, 94, 0.6)",
    lineWidth: 1,
    priceScaleId: "left",
    title: "Drawdown %",
  });

  return {
    chart,
    equity,
    drawdown,
    cleanup: () => chart.remove(),
  };
}

function toLineData(points: EquityPoint[]): {
  equity: LineData<UTCTimestamp>[];
  drawdown: LineData<UTCTimestamp>[];
} {
  const equity: LineData<UTCTimestamp>[] = [];
  const drawdown: LineData<UTCTimestamp>[] = [];
  for (const p of points) {
    const t = Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp;
    equity.push({ time: t, value: p.equity_usd });
    // drawdown_pct stored as fraction (0.10 = 10%); render as positive percent.
    drawdown.push({ time: t, value: p.drawdown_pct * 100 });
  }
  return { equity, drawdown };
}

function formatUsd(v: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(v);
}

export interface EquityCurveProps {
  className?: string;
}

export function EquityCurve({ className }: EquityCurveProps) {
  const { data, isLoading, error } = useEquity({ limit: 5000 });

  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const handlesRef = React.useRef<ChartHandles | null>(null);

  React.useEffect(() => {
    if (!containerRef.current) return;
    const handles = createEquityChart(containerRef.current);
    handlesRef.current = handles;
    return () => {
      handles.cleanup();
      handlesRef.current = null;
    };
  }, []);

  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    if (!data || data.length === 0) {
      h.equity.setData([]);
      h.drawdown.setData([]);
      return;
    }
    const { equity, drawdown } = toLineData(data);
    h.equity.setData(equity);
    h.drawdown.setData(drawdown);
    h.chart.timeScale().fitContent();
  }, [data]);

  const summary = React.useMemo(() => {
    if (!data || data.length === 0) return null;
    const first = data[0];
    const last = data[data.length - 1];
    const startEquity = first.equity_usd;
    const lastEquity = last.equity_usd;
    const pct = startEquity === 0 ? 0 : ((lastEquity - startEquity) / startEquity) * 100;
    return { lastEquity, pct, drawdownPct: last.drawdown_pct * 100 };
  }, [data]);

  return (
    <section
      className={cn("flex h-full flex-col gap-3", className)}
      aria-label="Equity curve"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Equity Curve</h2>
        {summary ? (
          <div className="flex items-center gap-4 text-sm">
            <span className="font-mono">{formatUsd(summary.lastEquity)}</span>
            <span
              className={cn(
                "font-mono font-medium",
                summary.pct >= 0 ? "text-emerald-400" : "text-rose-400",
              )}
            >
              {summary.pct >= 0 ? "+" : ""}
              {summary.pct.toFixed(2)}%
            </span>
            <span className="font-mono text-rose-400">
              DD {summary.drawdownPct.toFixed(2)}%
            </span>
          </div>
        ) : null}
      </header>

      <div className="relative flex-1">
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load equity curve: {error.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {isLoading && !data ? (
          <Skeleton className="h-[200px] w-full" />
        ) : null}
        {!isLoading && !error && (data?.length ?? 0) === 0 ? (
          <Alert variant="muted">
            <AlertDescription>
              No equity data yet. The brain.equity_curve table populates after
              Phase 12 live $100 begins.
            </AlertDescription>
          </Alert>
        ) : null}
        <div
          ref={containerRef}
          className={cn(
            "h-[200px] w-full overflow-hidden rounded-md border border-border",
            (data?.length ?? 0) === 0 && "hidden",
          )}
          aria-hidden={(data?.length ?? 0) === 0}
        />
      </div>
    </section>
  );
}
