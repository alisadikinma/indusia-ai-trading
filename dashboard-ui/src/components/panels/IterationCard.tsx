"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricsDiff } from "@/components/panels/MetricsDiff";
import type { IterationRun } from "@/lib/api-types";

// ---------------------------------------------------------------------------
// Outcome badge styling
// ---------------------------------------------------------------------------
function outcomeBadgeVariant(
  outcome: string | null,
): "success" | "warning" | "danger" | "secondary" {
  switch (outcome) {
    case "PASS":
      return "success";
    case "FAIL_RETRY":
      return "warning";
    case "FAIL_ESCALATE":
      return "danger";
    default:
      return "secondary";
  }
}

function runTypeBadgeVariant(run_type: string): "secondary" | "outline" {
  return run_type === "iteration" ? "secondary" : "outline";
}

function formatDuration(
  started_at: string,
  completed_at: string | null,
): string {
  if (!completed_at) return "in progress";
  const diffMs =
    new Date(completed_at).getTime() - new Date(started_at).getTime();
  const mins = Math.round(diffMs / 60_000);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export interface IterationCardProps {
  run: IterationRun;
  expanded: boolean;
  onToggle: () => void;
}

export function IterationCard({ run, expanded, onToggle }: IterationCardProps) {
  const startedDate = new Date(run.started_at).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  const duration = formatDuration(run.started_at, run.completed_at);

  return (
    <div
      data-testid="iteration-card"
      className={cn(
        "border-b border-border transition-colors last:border-0",
        expanded ? "bg-muted/30" : "hover:bg-muted/20",
      )}
    >
      {/* Header row */}
      <div className="flex flex-wrap items-start gap-2 px-4 py-3">
        {/* Left: badges + timestamp */}
        <div className="flex flex-1 flex-wrap items-center gap-2">
          {run.outcome ? (
            <Badge variant={outcomeBadgeVariant(run.outcome)}>
              {run.outcome}
            </Badge>
          ) : null}
          <Badge variant={runTypeBadgeVariant(run.run_type)}>
            {run.run_type}
          </Badge>
          {run.cycle_n != null ? (
            <Badge variant="outline" className="font-mono">
              cycle {run.cycle_n}/3
            </Badge>
          ) : null}
          <span className="text-xs text-muted-foreground">
            {startedDate} · {duration}
          </span>
        </div>
        {/* Right: expand toggle */}
        <Button
          data-testid="expand-btn"
          variant="ghost"
          size="sm"
          onClick={onToggle}
          aria-expanded={expanded}
          className="h-7 px-2 text-xs text-muted-foreground"
        >
          {expanded ? "▲ Collapse" : "▼ Expand"}
        </Button>
      </div>

      {/* Summary line (always visible) */}
      {run.failure_mode || run.hypothesis ? (
        <div className="px-4 pb-2 text-sm">
          {run.failure_mode ? (
            <span className="font-medium text-amber-400">
              {run.failure_mode}
            </span>
          ) : null}
          {run.failure_mode && run.hypothesis ? (
            <span className="text-muted-foreground"> — </span>
          ) : null}
          {run.hypothesis ? (
            <span className="text-muted-foreground line-clamp-2">
              {run.hypothesis}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* ADR link */}
      {run.adr_ref ? (
        <div className="px-4 pb-2">
          <a
            href={`/${run.adr_ref}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary underline underline-offset-2"
          >
            {run.adr_ref}
          </a>
        </div>
      ) : null}

      {/* Expandable section */}
      {expanded ? (
        <div className="border-t border-border/50 px-4 py-3">
          {/* Summary text (full) */}
          {run.summary ? (
            <div className="mb-3">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Summary
              </p>
              <p className="text-sm text-foreground">{run.summary}</p>
            </div>
          ) : null}

          {/* Hypothesis (full) */}
          {run.hypothesis ? (
            <div className="mb-3">
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Hypothesis
              </p>
              <p className="text-sm text-foreground">{run.hypothesis}</p>
            </div>
          ) : null}

          {/* Metrics diff */}
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Metrics
            </p>
            <MetricsDiff
              before={run.metrics_before}
              after={run.metrics_after}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
