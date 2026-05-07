"use client";

import * as React from "react";
import {
  CandlestickSeries,
  CrosshairMode,
  LineSeries,
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

import { useOhlcv, usePairs } from "@/lib/api-client";
import type {
  BacktestRunDetail,
  BacktestTrade,
  OhlcvPoint,
} from "@/lib/api-types";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

interface ChartHandles {
  chart: IChartApi;
  candleSeries: ISeriesApi<"Candlestick">;
  equitySeries: ISeriesApi<"Line">;
  cleanup: () => void;
}

function createBacktestChart(container: HTMLDivElement): ChartHandles {
  const chart = createChart(container, {
    layout: {
      background: { color: "#0b0b10" },
      textColor: "#ededed",
    },
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
    crosshair: { mode: CrosshairMode.Normal },
    autoSize: true,
  });
  const candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: "#10b981",
    downColor: "#f43f5e",
    wickUpColor: "#10b981",
    wickDownColor: "#f43f5e",
    borderVisible: false,
    priceScaleId: "right",
  });
  const equitySeries = chart.addSeries(LineSeries, {
    color: "#a78bfa",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    priceScaleId: "left",
    title: "Equity",
  });

  return {
    chart,
    candleSeries,
    equitySeries,
    cleanup: () => chart.remove(),
  };
}

function toCandlestickData(p: OhlcvPoint): CandlestickData<UTCTimestamp> {
  return {
    time: Math.floor(new Date(p.ts).getTime() / 1000) as UTCTimestamp,
    open: p.open,
    high: p.high,
    low: p.low,
    close: p.close,
  };
}

function buildTradeMarkers(
  trades: BacktestTrade[],
): SeriesMarker<Time>[] {
  const out: SeriesMarker<Time>[] = [];
  for (const t of trades) {
    if (!t.ts) continue;
    const ts = Math.floor(new Date(t.ts).getTime() / 1000);
    if (!Number.isFinite(ts)) continue;
    const long = t.side === "long";
    const winning = (t.pnl_pct ?? 0) >= 0;
    out.push({
      time: ts as UTCTimestamp,
      position: long ? "belowBar" : "aboveBar",
      color: winning ? "#10b981" : "#f43f5e",
      shape: long ? "arrowUp" : "arrowDown",
      text: t.side ?? "",
    });
  }
  out.sort((a, b) => (a.time as number) - (b.time as number));
  return out;
}

function buildEquityLine(
  equityCurve: BacktestRunDetail["equity_curve"],
): LineData<UTCTimestamp>[] {
  if (!equityCurve || equityCurve.length === 0) return [];
  const out: LineData<UTCTimestamp>[] = [];
  for (const p of equityCurve) {
    const t = Math.floor(new Date(p.ts).getTime() / 1000);
    if (!Number.isFinite(t)) continue;
    if (typeof p.equity !== "number" || !Number.isFinite(p.equity)) continue;
    out.push({ time: t as UTCTimestamp, value: p.equity });
  }
  out.sort((a, b) => (a.time as number) - (b.time as number));
  return out;
}

// Phase 9 walk-forward folds can emit hundreds of thousands of equity-curve
// points. Lightweight-charts chokes above ~50k points, and the human eye can't
// distinguish beyond ~5k anyway. Decimate to at most TARGET_CHART_POINTS by
// striding through the source array.
const TARGET_CHART_POINTS = 5000;
function decimate<T>(rows: readonly T[]): T[] {
  if (rows.length <= TARGET_CHART_POINTS) return rows.slice();
  const stride = Math.ceil(rows.length / TARGET_CHART_POINTS);
  return rows.filter((_, i) => i % stride === 0);
}

/**
 * Regime bands for train/test windows. Walk-forward folds always have a
 * train window followed by a test window — the band lets the operator see
 * at a glance which segment they're in. Implemented as a faint line
 * (LineSeries with opacity) rather than a real "band" because lightweight-
 * charts v5 doesn't ship a built-in band primitive — the alternative would
 * be a custom plugin which exceeds this phase's scope.
 *
 * For now we render train/test boundary as dashed price-lines on the candle
 * series.
 */
function applyRegimeBands(
  candleSeries: ISeriesApi<"Candlestick">,
  detail: BacktestRunDetail,
) {
  // Remove any pre-existing price lines (lightweight-charts has no listAll).
  // The cleanest approach is to recreate the lines on each detail change;
  // we attach them via createPriceLine and store handles for removal.
  // Note: this returns the handles so the caller can remove them on next
  // detail.
  const lines = [
    {
      ts: detail.train_start,
      title: "train start",
      color: "#6366f1",
    },
    {
      ts: detail.train_end,
      title: "train end",
      color: "#6366f1",
    },
    {
      ts: detail.test_start,
      title: "test start",
      color: "#f59e0b",
    },
    {
      ts: detail.test_end,
      title: "test end",
      color: "#f59e0b",
    },
  ];
  // Lightweight-charts price-lines are horizontal; for vertical time markers
  // we use the chart's time-axis-grid lines via setVisibleRange + custom
  // overlay — but the simpler real solution is markers on the candle series.
  const regimeMarkers: SeriesMarker<Time>[] = [];
  for (const l of lines) {
    const ts = Math.floor(new Date(l.ts).getTime() / 1000);
    if (!Number.isFinite(ts)) continue;
    regimeMarkers.push({
      time: ts as UTCTimestamp,
      position: "aboveBar",
      color: l.color,
      shape: "circle",
      text: l.title,
    });
  }
  regimeMarkers.sort((a, b) => (a.time as number) - (b.time as number));
  return regimeMarkers;
}

const TIMEFRAMES: ReadonlyArray<string> = ["15m", "1h", "4h", "1d"];

const DEFAULT_PAIR = "BTC/USDT";
const DEFAULT_TF = "1h";
const CANDLE_LIMIT = 1000;

export interface BacktestChartProps {
  /** Selected backtest run detail, if any. */
  detail: BacktestRunDetail | null;
  /** Loading flag from upstream. */
  isLoading?: boolean;
  className?: string;
}

export function BacktestChart({
  detail,
  isLoading,
  className,
}: BacktestChartProps) {
  const [pair, setPair] = React.useState(DEFAULT_PAIR);
  const [tf, setTf] = React.useState(DEFAULT_TF);

  // Pair whitelist from /dashboard/chart/pairs — driven by crypto-bot config.
  // Backend hard-fails if config is missing (Iron Law 3); empty defensive UI
  // is a belt-and-suspenders guard only.
  const { data: pairsData, isLoading: pairsLoading } = usePairs();
  const pairs = pairsData ?? [];

  // OHLCV bounded to the test window — fall back to recent data if the
  // window has no rows in brain.ohlcv.
  const ohlcvParams = React.useMemo(() => {
    if (!detail) return { pair, tf, limit: CANDLE_LIMIT };
    return {
      pair,
      tf,
      from: detail.train_start,
      to: detail.test_end,
      limit: CANDLE_LIMIT,
    };
  }, [pair, tf, detail]);

  const { data: ohlcv, isLoading: ohlcvLoading, error: ohlcvError } =
    useOhlcv(ohlcvParams);

  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const handlesRef = React.useRef<ChartHandles | null>(null);
  const tradeMarkersRef = React.useRef<ReturnType<
    typeof createSeriesMarkers<Time>
  > | null>(null);

  React.useEffect(() => {
    if (!containerRef.current) return;
    const handles = createBacktestChart(containerRef.current);
    handlesRef.current = handles;
    return () => {
      tradeMarkersRef.current?.detach?.();
      tradeMarkersRef.current = null;
      handles.cleanup();
      handlesRef.current = null;
    };
  }, []);

  // Push candles
  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    if (!ohlcv || ohlcv.length === 0) {
      h.candleSeries.setData([]);
      return;
    }
    h.candleSeries.setData(ohlcv.map(toCandlestickData));
    h.chart.timeScale().fitContent();
  }, [ohlcv]);

  // Push equity curve
  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    if (!detail) {
      h.equitySeries.setData([]);
      return;
    }
    h.equitySeries.setData(decimate(buildEquityLine(detail.equity_curve)));
  }, [detail]);

  // Push trade + regime markers
  React.useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    const trades = detail?.trades ?? [];
    const tradeMarkers = buildTradeMarkers(trades);
    const regimeMarkers = detail ? applyRegimeBands(h.candleSeries, detail) : [];
    const combined = [...tradeMarkers, ...regimeMarkers].sort(
      (a, b) => (a.time as number) - (b.time as number),
    );
    if (tradeMarkersRef.current) {
      tradeMarkersRef.current.setMarkers(combined);
    } else {
      tradeMarkersRef.current = createSeriesMarkers(h.candleSeries, combined);
    }
  }, [detail]);

  const showLoading = isLoading || ohlcvLoading;
  const noChartData =
    !showLoading && !ohlcvError && (ohlcv?.length ?? 0) === 0;

  return (
    <section
      className={cn("flex h-full flex-col gap-3", className)}
      aria-label="Backtest chart"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Trades + equity overlay
          </h3>
        </div>
        <div className="flex items-center gap-3">
          <div
            className="flex items-center gap-1 rounded-md border border-border bg-input p-0.5"
            role="tablist"
            aria-label="Pair"
          >
            {pairsLoading ? (
              <Skeleton className="h-6 w-24 rounded" />
            ) : pairs.length === 0 ? (
              <span className="px-2 text-xs text-muted-foreground">No pairs</span>
            ) : (
              pairs.map((p) => {
                const active = p === pair;
                return (
                  <button
                    key={p}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    data-active={active ? "true" : "false"}
                    onClick={() => setPair(p)}
                    className={cn(
                      "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                      active
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    {p}
                  </button>
                );
              })
            )}
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
        {ohlcvError ? (
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load OHLCV: {ohlcvError.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {showLoading ? (
          <Skeleton className="h-full min-h-[400px] w-full" />
        ) : null}
        {noChartData && !detail ? (
          <Alert variant="muted">
            <AlertDescription>
              Select a backtest run to plot trades + equity curve.
            </AlertDescription>
          </Alert>
        ) : null}
        {noChartData && detail ? (
          <Alert variant="muted">
            <AlertDescription>
              No OHLCV data for {pair} {tf} in window{" "}
              {new Date(detail.train_start).toISOString().slice(0, 10)} →{" "}
              {new Date(detail.test_end).toISOString().slice(0, 10)}. Try a
              different pair or timeframe.
            </AlertDescription>
          </Alert>
        ) : null}
        <div
          ref={containerRef}
          className={cn(
            "h-[400px] w-full overflow-hidden rounded-md border border-border",
            (ohlcv?.length ?? 0) === 0 && "hidden",
          )}
          aria-hidden={(ohlcv?.length ?? 0) === 0}
        />
      </div>
    </section>
  );
}
