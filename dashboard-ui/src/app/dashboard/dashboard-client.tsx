"use client";

import * as React from "react";

import { LiveChart } from "@/components/charts/LiveChart";
import { EquityCurve } from "@/components/charts/EquityCurve";
import { OpenPositions } from "@/components/panels/OpenPositions";
import { ReasoningSidebar } from "@/components/panels/ReasoningSidebar";
import { RiskMonitor } from "@/components/panels/RiskMonitor";
import { Card, CardContent } from "@/components/ui/card";

export interface DashboardClientProps {
  wsToken: string | null;
}

export function DashboardClient({ wsToken }: DashboardClientProps) {
  return (
    <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
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
        <Card className="lg:col-span-5">
          <CardContent className="flex h-full flex-col p-0">
            <ReasoningSidebar wsToken={wsToken} className="flex-1" />
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
