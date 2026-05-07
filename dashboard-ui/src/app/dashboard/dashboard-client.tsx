"use client";

import * as React from "react";

import { LiveChart } from "@/components/charts/LiveChart";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { OpenPositions } from "@/components/panels/OpenPositions";
import { ReasoningSidebar } from "@/components/panels/ReasoningSidebar";
import { RiskMonitor } from "@/components/panels/RiskMonitor";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorBoundary } from "@/components/error-boundary";

export interface DashboardClientProps {
  wsToken: string | null;
}

export function DashboardClient({ wsToken }: DashboardClientProps) {
  return (
    <ErrorBoundary viewName="Live Dashboard">
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
        {/* Mobile: single column → desktop: 12-col grid */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Left column: chart + equity + positions + risk */}
          <div className="flex flex-col gap-4 lg:col-span-7">
            <Card>
              <CardContent className="p-4">
                <LiveChart />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <EquityCurve />
              </CardContent>
            </Card>
            {/* Positions + risk: 1-col on sm, 2-col on md+ */}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Card>
                <CardContent className="p-4">
                  <OpenPositions wsToken={wsToken} />
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <RiskMonitor />
                </CardContent>
              </Card>
            </div>
          </div>
          {/* Right column: AI reasoning sidebar — full width on sm/md */}
          <Card className="lg:col-span-5">
            <CardContent className="flex h-full flex-col p-0">
              <ReasoningSidebar wsToken={wsToken} className="flex-1" />
            </CardContent>
          </Card>
        </div>
      </main>
    </ErrorBoundary>
  );
}
