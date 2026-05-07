"use client";

import * as React from "react";

import type { FreqaiCalibration } from "@/lib/api-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

interface CalibrationPlotProps {
  data: FreqaiCalibration | undefined;
  isLoading: boolean;
  error: Error | null;
}

// Hand-rolled SVG scatter plot with diagonal calibration reference line.
// 200x200px plot area; dots sized by bucket n; axis labels minimal.
//
// X axis: claude_size_mult (the brain's resize multiplier, used as a proxy for
//   prediction confidence). The schema CHECK constraint clamps this to
//   [0.5, 1.5]; the backend's _CALIBRATION_EDGES tile that range in 0.1 steps.
// Y axis: realised win_rate, naturally in [0, 1].
//
// The "perfect calibration" reference line maps the X domain linearly onto the
// Y domain — i.e. higher resize multiplier should correlate with higher win
// rate. (It is NOT y=x because the two axes don't share a domain.)
const X_DOMAIN_LO = 0.5;
const X_DOMAIN_HI = 1.5;

function CalibrationSvg({ calibration }: { calibration: FreqaiCalibration["calibration"] }) {
  const W = 200;
  const H = 200;
  const PAD = 20;
  const plotW = W - 2 * PAD;
  const plotH = H - 2 * PAD;

  // X normalised over [0.5, 1.5] so all real backend buckets land inside the
  // plot area. Y stays a direct fraction (already in [0, 1]).
  const toX = (v: number) =>
    PAD + ((v - X_DOMAIN_LO) / (X_DOMAIN_HI - X_DOMAIN_LO)) * plotW;
  const toY = (v: number) => PAD + (1 - v) * plotH; // flip Y axis

  const maxN = Math.max(...calibration.map((b) => b.n), 1);

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-label="Calibration plot"
      className="overflow-visible"
    >
      {/* Axes */}
      <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#232331" strokeWidth={1} />
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#232331" strokeWidth={1} />

      {/* Grid lines: X at quartiles of the [0.5, 1.5] domain (= 0.75, 1.0, 1.25),
          Y at quartiles of [0, 1] (= 0.25, 0.5, 0.75). */}
      {[0.75, 1.0, 1.25].map((v) => (
        <line
          key={`gx-${v}`}
          x1={toX(v)}
          y1={PAD}
          x2={toX(v)}
          y2={H - PAD}
          stroke="#1f1f2a"
          strokeWidth={1}
        />
      ))}
      {[0.25, 0.5, 0.75].map((v) => (
        <line
          key={`gy-${v}`}
          x1={PAD}
          y1={toY(v)}
          x2={W - PAD}
          y2={toY(v)}
          stroke="#1f1f2a"
          strokeWidth={1}
        />
      ))}

      {/* Axis labels */}
      <text x={PAD + plotW / 2} y={H - 2} textAnchor="middle" fontSize={9} fill="#888">
        Predicted (size_mult)
      </text>
      <text
        x={6}
        y={PAD + plotH / 2}
        textAnchor="middle"
        fontSize={9}
        fill="#888"
        transform={`rotate(-90, 6, ${PAD + plotH / 2})`}
      >
        Actual win rate
      </text>

      {/* Perfect-calibration diagonal: bottom-left (X=0.5, Y=0) to top-right
          (X=1.5, Y=1) — a straight line across the full plot area. */}
      <line
        x1={toX(X_DOMAIN_LO)}
        y1={toY(0)}
        x2={toX(X_DOMAIN_HI)}
        y2={toY(1)}
        stroke="#4b5563"
        strokeWidth={1}
        strokeDasharray="4 3"
      />

      {/* Data points sized by n */}
      {calibration.map((b, i) => {
        const r = 3 + (b.n / maxN) * 8;
        return (
          <circle
            key={i}
            cx={toX(b.predicted_mid)}
            cy={toY(b.actual_win_rate)}
            r={r}
            fill="rgba(16, 185, 129, 0.7)"
            stroke="#10b981"
            strokeWidth={1}
          >
            <title>
              predicted={b.predicted_mid.toFixed(2)} actual={b.actual_win_rate.toFixed(2)} n={b.n}
            </title>
          </circle>
        );
      })}
    </svg>
  );
}

export function CalibrationPlot({ data, isLoading, error }: CalibrationPlotProps) {
  return (
    <section>
      <h2 className="mb-3 text-base font-semibold tracking-tight">Calibration</h2>

      {error ? (
        <Alert variant="destructive">
          <AlertDescription>Failed to load calibration: {error.message}</AlertDescription>
        </Alert>
      ) : isLoading && !data ? (
        <Skeleton className="h-[240px] w-full" />
      ) : data && data.calibration.length > 0 ? (
        <div className="flex flex-col items-center gap-2">
          <CalibrationSvg calibration={data.calibration} />
          <p className="text-xs text-muted-foreground">
            Each dot: one predicted-probability bucket vs realised win rate. Size ∝ sample count.
          </p>
        </div>
      ) : (
        <Alert variant="muted">
          <AlertDescription>
            {data?.note
              ? data.note
              : "Calibration data not yet available."}
            {" "}Buckets appear once Phase 6 post-mortem cron records{" "}
            <code className="font-mono text-xs">actual_outcome</code> on{" "}
            <code className="font-mono text-xs">brain.brain_journal</code> rows,
            and Phase 7 daily retrain cron is running.
          </AlertDescription>
        </Alert>
      )}
    </section>
  );
}
