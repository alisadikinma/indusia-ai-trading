"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useFreqai, useFreqaiHistory, useFreqaiPredictions } from "@/lib/api-client";
import { useDashboardWs } from "@/lib/ws-client";
import type { WsMessage } from "@/lib/api-types";
import { Card, CardContent } from "@/components/ui/card";
import { CalibrationPlot } from "@/components/panels/CalibrationPlot";
import { AucTrendChart } from "@/components/panels/AucTrendChart";
import { FeatureImportance } from "@/components/panels/FeatureImportance";
import { RetrainHistory } from "@/components/panels/RetrainHistory";
import { PredictionHistogram } from "@/components/panels/PredictionHistogram";
import { ErrorBoundary } from "@/components/error-boundary";

// Hoisted to module-level constant to prevent new array ref on every
// render — an inline literal would cause useEffect dep churn → WS reconnect.
const WS_CHANNELS: ReadonlyArray<NonNullable<WsMessage["channel"]>> = [
  "dashboard_freqai",
];

export interface FreqaiClientProps {
  wsToken: string | null;
}

export function FreqaiClient({ wsToken }: FreqaiClientProps) {
  const queryClient = useQueryClient();

  // Data hooks
  const { data: calibration, isLoading: calLoading, error: calError } = useFreqai();
  const { data: history, isLoading: histLoading, error: histError } = useFreqaiHistory();
  const { data: predictions, isLoading: predLoading, error: predError } =
    useFreqaiPredictions({ hours: 24 });

  // WS live-update subscription — invalidate all three queries on new retrain.
  const { lastMessage } = useDashboardWs(WS_CHANNELS, wsToken);

  React.useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.channel !== "dashboard_freqai") return;
    queryClient.invalidateQueries({ queryKey: ["freqai-calibration"] });
    queryClient.invalidateQueries({ queryKey: ["freqai-history"] });
    queryClient.invalidateQueries({ queryKey: ["freqai-predictions"] });
  }, [lastMessage, queryClient]);

  return (
    <ErrorBoundary viewName="FreqAI Insights">
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold tracking-tight">FreqAI Insights</h1>
          <p className="text-sm text-muted-foreground">
            XGBoost model calibration, AUC trend, feature importance, and retrain history
            (Phase 7 surface).
          </p>
        </header>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left column — calibration + AUC trend: full-width on sm/md, 5/12 on lg+ */}
          <div className="flex flex-col gap-4 lg:col-span-5">
            <Card>
              <CardContent className="p-4">
                <CalibrationPlot
                  data={calibration}
                  isLoading={calLoading}
                  error={calError}
                />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <AucTrendChart
                  data={calibration}
                  isLoading={calLoading}
                  error={calError}
                />
              </CardContent>
            </Card>
          </div>

          {/* Right column — feature importance + prediction histogram */}
          <div className="flex flex-col gap-4 lg:col-span-7">
            <Card>
              <CardContent className="p-4">
                <FeatureImportance
                  data={calibration}
                  isLoading={calLoading}
                  error={calError}
                />
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-4">
                <PredictionHistogram
                  data={predictions}
                  isLoading={predLoading}
                  error={predError}
                />
              </CardContent>
            </Card>
          </div>

          {/* Full-width — retrain history table: horizontal scroll on sm */}
          <div className="lg:col-span-12">
            <Card>
              <CardContent className="overflow-x-auto p-4">
                <RetrainHistory
                  data={history}
                  isLoading={histLoading}
                  error={histError}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      </main>
    </ErrorBoundary>
  );
}
