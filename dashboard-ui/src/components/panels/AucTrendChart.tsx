"use client";

import * as React from "react";
import {
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";

import type { FreqaiCalibration } from "@/lib/api-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface ChartHandles {
  chart: IChartApi;
  series: ISeriesApi<"Line">;
  cleanup: () => void;
}

function createAucChart(container: HTMLDivElement): ChartHandles {
  const chart = createChart(container, {
    layout: { background: { color: "#0b0b10" }, textColor: "#ededed" },
    grid: {
      vertLines: { color: "#1f1f2a" },
      horzLines: { color: "#1f1f2a" },
    },
    rightPriceScale: { borderColor: "#232331" },
    timeScale: {
      borderColor: "#232331",
      timeVisible: true,
      secondsVisible: false,
    },
    autoSize: true,
  });
  const series = chart.addSeries(LineSeries, {
    color: "#6366f1",
    lineWidth: 2,
    title: "AUC",
  });
  return { chart, series, cleanup: () => chart.remove() };
}

interface AucTrendChartProps {
  data: FreqaiCalibration | undefined;
  isLoading: boolean;
  error: Error | null;
}

export function AucTrendChart({ data, isLoading, error }: AucTrendChartProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const handlesRef = React.useRef<ChartHandles | null>(null);

  React.useEffect(() => {
    if (!containerRef.current) return;
    const handles = createAucChart(containerRef.current);
    handlesRef.current = handles;
    return () => {
      handles.cleanup();
      handlesRef.current = null;
    };
  }, []);

  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    if (!data || data.auc_history.length === 0) {
      h.series.setData([]);
      return;
    }
    // auc_history is newest-first from the backend; lightweight-charts needs
    // chronological order (ascending time).
    const sorted = [...data.auc_history].sort(
      (a, b) => new Date(a.retrained_at).getTime() - new Date(b.retrained_at).getTime(),
    );
    const lineData: LineData<UTCTimestamp>[] = sorted.map((p) => ({
      time: Math.floor(new Date(p.retrained_at).getTime() / 1000) as UTCTimestamp,
      value: p.auc,
    }));
    h.series.setData(lineData);
    h.chart.timeScale().fitContent();
  }, [data]);

  const latestAuc = React.useMemo(() => {
    if (!data || data.auc_history.length === 0) return null;
    // auc_history is ordered newest-first
    return data.auc_history[0].auc;
  }, [data]);

  const hasData = (data?.auc_history.length ?? 0) > 0;

  return (
    <section>
      <h2 className="mb-3 flex items-center gap-2 text-base font-semibold tracking-tight">
        AUC trend
        {latestAuc !== null ? (
          <Badge variant="outline" data-testid="freqai-latest-auc">
            {latestAuc.toFixed(2)}
          </Badge>
        ) : null}
      </h2>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>Failed to load AUC history: {error.message}</AlertDescription>
        </Alert>
      ) : isLoading && !data ? (
        <Skeleton className="h-[180px] w-full" />
      ) : !hasData ? (
        <Alert variant="muted">
          <AlertDescription>
            {data?.note
              ? data.note
              : "No AUC history yet."}
            {" "}The chart populates after Phase 7 daily retrain cron records
            the first model run into{" "}
            <code className="font-mono text-xs">brain.freqai_history</code>.
          </AlertDescription>
        </Alert>
      ) : null}

      <div
        ref={containerRef}
        className="h-[180px] w-full overflow-hidden rounded-md border border-border"
        style={{ display: hasData ? undefined : "none" }}
        aria-hidden={!hasData}
      />
    </section>
  );
}
