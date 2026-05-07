"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { JournalEntry as JournalEntryType } from "@/lib/api-types";

export interface JournalEntryProps {
  entry: JournalEntryType;
  expanded: boolean;
  onToggle: () => void;
}

function decisionVariant(
  decision: string,
): React.ComponentProps<typeof Badge>["variant"] {
  switch (decision) {
    case "approve":
      return "success";
    case "veto":
      return "danger";
    case "resize":
      return "warning";
    case "halt":
      return "destructive";
    default:
      return "outline";
  }
}

function outcomeVariant(
  outcome: string | null,
): React.ComponentProps<typeof Badge>["variant"] {
  if (outcome === null) return "outline";
  if (outcome === "win") return "success";
  if (outcome === "loss") return "danger";
  return "secondary";
}

function formatTs(iso: string): string {
  // Compact UTC timestamp — 2026-05-06 12:34:56Z
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}Z`
  );
}

export function JournalEntry({ entry, expanded, onToggle }: JournalEntryProps) {
  return (
    <div
      data-testid={`journal-entry-${entry.id}`}
      className={cn(
        "border-b border-border bg-card px-4 py-3 transition-colors",
        expanded ? "bg-muted/30" : "hover:bg-muted/20",
      )}
    >
      <div className="flex items-start gap-3">
        <Button
          variant="ghost"
          size="sm"
          aria-label={`expand entry ${entry.id}`}
          onClick={onToggle}
          aria-expanded={expanded}
          className="h-7 w-7 px-0"
        >
          <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
        </Button>

        <div className="grid flex-1 grid-cols-12 items-center gap-3 text-sm">
          <span className="col-span-3 font-mono text-xs text-muted-foreground">
            {formatTs(entry.ts)}
          </span>

          <Badge variant="outline" className="col-span-2 justify-self-start">
            {entry.regime}
          </Badge>

          <Badge
            variant={decisionVariant(entry.decision)}
            className="col-span-1 justify-self-start"
          >
            {entry.decision}
          </Badge>

          <span className="col-span-1 text-xs text-muted-foreground">
            conf {entry.confidence ?? "—"}
          </span>

          <span className="col-span-4 truncate text-muted-foreground">
            {entry.reasoning}
          </span>

          <Badge
            variant={outcomeVariant(entry.actual_outcome)}
            className="col-span-1 justify-self-end"
          >
            {entry.actual_outcome ?? "open"}
          </Badge>
        </div>
      </div>

      {expanded ? (
        <div className="mt-3 grid grid-cols-1 gap-4 px-9 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Reasoning
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">
              {entry.reasoning}
            </p>
          </div>

          <dl className="space-y-2 text-sm">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Confidence
              </dt>
              <dd className="font-mono">
                {entry.confidence ?? "—"} / 10
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Signal
              </dt>
              <dd className="font-mono">
                {entry.signal_id ?? "—"}
              </dd>
            </div>
          </dl>

          <div className="lg:col-span-3">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Expected vs actual
            </div>
            <div className="mt-1 grid grid-cols-1 gap-2 md:grid-cols-3">
              <div className="rounded-md border border-border bg-background px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Expected
                </div>
                <div className="text-sm">
                  {entry.expected_outcome ?? "—"}
                </div>
              </div>
              <div className="rounded-md border border-border bg-background px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Actual
                </div>
                <div className="text-sm">
                  {entry.actual_outcome ?? "—"}
                  {entry.actual_pnl_pct !== null
                    ? ` (${(entry.actual_pnl_pct * 100).toFixed(2)}%)`
                    : ""}
                </div>
              </div>
              <div className="rounded-md border border-border bg-background px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Recorded at
                </div>
                <div className="font-mono text-xs">
                  {entry.outcome_recorded_at
                    ? formatTs(entry.outcome_recorded_at)
                    : "—"}
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
