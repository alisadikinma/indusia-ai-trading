"use client";

import * as React from "react";
import {
  CandlestickSeries,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { useJournal, useOhlcv } from "@/lib/api-client";
import type { JournalEntry, OhlcvPoint } from "@/lib/api-types";
import { adx, ema, type Candle } from "@/lib/indicators";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const PAIRS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "BTC/USDT", label: "BTC/USDT" },
  { value: "ETH/USDT", label: "ETH/USDT" },
];

const TIMEFRAMES: ReadonlyArray<string> = [
  "1m",
  "5m",
  "15m",
  "1h",
  "4h",
  "1d",
];

const DEFAULT_TF = "15m";
const DEFAULT_PAIR = "BTC/USDT";
const CANDLE_LIMIT = 500;

function toCandle(p: OhlcvPoint): Candle {
  return {
    ts: Math.floor(new Date(p.ts).getTime() / 1000),
    open: p.open,
    high: p.high,
    low: p.low,
    close: p.close,
    volume: p.volume,
  };
}

function toCandlestickData(c: Candle): CandlestickData<UTCTimestamp> {
  return {
    time: c.ts as UTCTimestamp,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  };
}

function toLineData(points: { time: number; value: number }[]): LineData<UTCTimestamp>[] {
  return points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}

function buildMarkers(
  candles: Candle[],
  entries: JournalEntry[],
): SeriesMarker<Time>[] {
  if (candles.length === 0 || entries.length === 0) return [];
  const firstTs = candles[0].ts;
  const lastTs = candles[candles.length - 1].ts;
  const out: SeriesMarker<Time>[] = [];
  for (const e of entries) {
    const t = Math.floor(new Date(e.ts).getTime() / 1000);
    if (t < firstTs || t > lastTs) continue;
    const isApprove = e.decision === "approve";
    const isVeto = e.decision === "veto";
    if (!isApprove && !isVeto) continue;
    out.push({
      time: t as UTCTimestamp,
      position: isApprove ? "belowBar" : "aboveBar",
      color: isApprove ? "#10b981" : "#f43f5e",
      shape: isApprove ? "arrowUp" : "arrowDown",
      text: isApprove ? "approve" : "veto",
    });
  }
  // Lightweight-charts requires markers in ascending time order.
  out.sort((a, b) => (a.time as number) - (b.time as number));
  return out;
}

interface ChartHandles {
  chart: IChartApi;
  candleSeries: ISeriesApi<"Candlestick">;
  ema20Series: ISeriesApi<"Line">;
  ema50Series: ISeriesApi<"Line">;
  adxChart: IChartApi;
  adxSeries: ISeriesApi<"Line">;
  cleanup: () => void;
}

function createCharts(
  mainContainer: HTMLDivElement,
  adxContainer: HTMLDivElement,
): ChartHandles {
  const baseOptions = {
    layout: {
      background: { color: "#0b0b10" },
      textColor: "#ededed",
    },
    grid: {
      vertLines: { color: "#1f1f2a" },
      horzLines: { color: "#1f1f2a" },
    },
    rightPriceScale: { borderColor: "#232331" },
    timeScale: { borderColor: "#232331", timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    autoSize: true,
  } as const;

  const chart = createChart(mainContainer, baseOptions);
  const candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: "#10b981",
    downColor: "#f43f5e",
    wickUpColor: "#10b981",
    wickDownColor: "#f43f5e",
    borderVisible: false,
  });
  const ema20Series = chart.addSeries(LineSeries, {
    color: "#6366f1",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA20",
  });
  const ema50Series = chart.addSeries(LineSeries, {
    color: "#f59e0b",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA50",
  });

  const adxChart = createChart(adxContainer, {
    ...baseOptions,
    timeScale: { ...baseOptions.timeScale, visible: false },
  });
  const adxSeries = adxChart.addSeries(LineSeries, {
    color: "#a78bfa",
    lineWidth: 2,
    title: "ADX(14)",
  });
  // Reference line at 25 (the classic ADX trend threshold).
  adxSeries.createPriceLine({
    price: 25,
    color: "#52525b",
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    axisLabelVisible: true,
    title: "trend",
  });

  // Sync time axes between main chart and ADX subchart.
  let syncing = false;
  const syncFromMain = () => {
    if (syncing) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    if (range) {
      syncing = true;
      adxChart.timeScale().setVisibleLogicalRange(range);
      syncing = false;
    }
  };
  const syncFromAdx = () => {
    if (syncing) return;
    const range = adxChart.timeScale().getVisibleLogicalRange();
    if (range) {
      syncing = true;
      chart.timeScale().setVisibleLogicalRange(range);
      syncing = false;
    }
  };
  chart.timeScale().subscribeVisibleLogicalRangeChange(syncFromMain);
  adxChart.timeScale().subscribeVisibleLogicalRangeChange(syncFromAdx);

  const cleanup = () => {
    try {
      chart
        .timeScale()
        .unsubscribeVisibleLogicalRangeChange(syncFromMain);
      adxChart
        .timeScale()
        .unsubscribeVisibleLogicalRangeChange(syncFromAdx);
    } catch {
      // no-op
    }
    chart.remove();
    adxChart.remove();
  };

  return {
    chart,
    candleSeries,
    ema20Series,
    ema50Series,
    adxChart,
    adxSeries,
    cleanup,
  };
}

export interface LiveChartProps {
  className?: string;
  defaultPair?: string;
  defaultTf?: string;
}

export function LiveChart({
  className,
  defaultPair = DEFAULT_PAIR,
  defaultTf = DEFAULT_TF,
}: LiveChartProps) {
  const [pair, setPair] = React.useState(defaultPair);
  const [tf, setTf] = React.useState(defaultTf);

  const { data, isLoading, error } = useOhlcv({
    pair,
    tf,
    limit: CANDLE_LIMIT,
  });

  const candles = React.useMemo<Candle[]>(
    () => (data ? data.map(toCandle) : []),
    [data],
  );

  // Window the journal lookup to the chart's visible time-range.
  const journalParams = React.useMemo(() => {
    if (candles.length === 0) return { size: 200 };
    return {
      from: new Date(candles[0].ts * 1000).toISOString(),
      to: new Date(candles[candles.length - 1].ts * 1000).toISOString(),
      size: 200,
    };
  }, [candles]);

  const journal = useJournal(journalParams);

  const mainRef = React.useRef<HTMLDivElement | null>(null);
  const adxRef = React.useRef<HTMLDivElement | null>(null);
  const handlesRef = React.useRef<ChartHandles | null>(null);
  const markersHandleRef = React.useRef<ReturnType<
    typeof createSeriesMarkers<Time>
  > | null>(null);

  // Mount/unmount the chart instance.
  React.useEffect(() => {
    if (!mainRef.current || !adxRef.current) return;
    const handles = createCharts(mainRef.current, adxRef.current);
    handlesRef.current = handles;
    return () => {
      markersHandleRef.current?.detach?.();
      markersHandleRef.current = null;
      handles.cleanup();
      handlesRef.current = null;
    };
  }, []);

  // Push candle + indicator data on every fetch.
  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    if (candles.length === 0) {
      h.candleSeries.setData([]);
      h.ema20Series.setData([]);
      h.ema50Series.setData([]);
      h.adxSeries.setData([]);
      return;
    }
    h.candleSeries.setData(candles.map(toCandlestickData));
    h.ema20Series.setData(toLineData(ema(candles, 20)));
    h.ema50Series.setData(toLineData(ema(candles, 50)));
    h.adxSeries.setData(toLineData(adx(candles, 14)));
    h.chart.timeScale().fitContent();
    h.adxChart.timeScale().fitContent();
  }, [candles]);

  // Push trade markers (approve/veto) onto the candle series.
  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    const entries = journal.data?.items ?? [];
    const markers = buildMarkers(candles, entries);
    if (markersHandleRef.current) {
      markersHandleRef.current.setMarkers(markers);
    } else {
      markersHandleRef.current = createSeriesMarkers(h.candleSeries, markers);
    }
  }, [candles, journal.data]);

  return (
    <section
      className={cn("flex h-full flex-col gap-3", className)}
      aria-label="Live chart"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Live Chart</h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Label htmlFor="pair-select" className="text-xs uppercase tracking-wide text-muted-foreground">
              Pair
            </Label>
            <Select
              id="pair-select"
              value={pair}
              onChange={(e) => setPair(e.target.value)}
              className="h-8 w-32"
            >
              {PAIRS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </div>
          <div
            className="flex items-center gap-1 rounded-md border border-border bg-input p-0.5"
            role="tablist"
            aria-label="Timeframe"
          >
            {TIMEFRAMES.map((t) => {
              const active = t === tf;
              return (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  data-active={active ? "true" : "false"}
                  onClick={() => setTf(t)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      <div className="relative flex-1">
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load OHLCV: {error.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {isLoading && !data ? (
          <Skeleton className="h-full min-h-[320px] w-full" />
        ) : null}
        {!isLoading && (data?.length ?? 0) === 0 && !error ? (
          <Alert variant="muted">
            <AlertDescription>
              No OHLCV data for {pair} {tf} yet.
            </AlertDescription>
          </Alert>
        ) : null}
        <div
          ref={mainRef}
          className={cn(
            "h-[360px] w-full overflow-hidden rounded-md border border-border",
            (data?.length ?? 0) === 0 && "hidden",
          )}
          aria-hidden={(data?.length ?? 0) === 0}
        />
        <div
          ref={adxRef}
          className={cn(
            "mt-2 h-[100px] w-full overflow-hidden rounded-md border border-border",
            (data?.length ?? 0) === 0 && "hidden",
          )}
          aria-hidden={(data?.length ?? 0) === 0}
        />
      </div>
    </section>
  );
}
