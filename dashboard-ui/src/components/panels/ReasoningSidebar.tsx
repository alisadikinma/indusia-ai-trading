"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useJournal } from "@/lib/api-client";
import { useDashboardWs } from "@/lib/ws-client";
import type { JournalEntry, WsMessage } from "@/lib/api-types";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

// Hoisted to module-level constant to prevent new array ref on every
// render — an inline literal would cause useEffect dep churn → WS reconnect.
const WS_CHANNELS: ReadonlyArray<NonNullable<WsMessage["channel"]>> = [
  "dashboard_journal",
];

const DECISION_FILTERS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "all", label: "All" },
  { value: "approve", label: "Approve" },
  { value: "veto", label: "Veto" },
  { value: "resize", label: "Resize" },
];

const REGIME_COLORS: Record<string, string> = {
  bull_trend: "bg-emerald-600/20 text-emerald-400",
  bear_trend: "bg-rose-600/20 text-rose-400",
  sideways: "bg-slate-600/20 text-slate-300",
  high_vol: "bg-amber-600/20 text-amber-400",
  low_vol: "bg-indigo-600/20 text-indigo-300",
  unknown: "bg-zinc-700/40 text-zinc-300",
};

function decisionVariant(
  d: string,
): "success" | "danger" | "warning" | "secondary" {
  if (d === "approve") return "success";
  if (d === "veto") return "danger";
  if (d === "resize") return "warning";
  if (d === "halt") return "danger";
  return "secondary";
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, Math.floor((now - then) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

interface JournalRowProps {
  entry: JournalEntry;
  highlighted: boolean;
}

function JournalRow({ entry, highlighted }: JournalRowProps) {
  const [expanded, setExpanded] = React.useState(false);
  const regimeClass =
    REGIME_COLORS[entry.regime] ?? REGIME_COLORS.unknown;
  return (
    <li
      className={cn(
        "border-b border-border px-3 py-2 text-sm transition-colors",
        highlighted && "bg-primary/5",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="font-mono text-xs text-muted-foreground"
          title={new Date(entry.ts).toISOString()}
        >
          {timeAgo(entry.ts)}
        </span>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
              regimeClass,
            )}
          >
            {entry.regime}
          </span>
          <Badge variant={decisionVariant(entry.decision)}>
            {entry.decision}
          </Badge>
          {entry.confidence != null ? (
            <span className="rounded-full border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              c{entry.confidence}
            </span>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "mt-1 block w-full cursor-pointer text-left text-foreground/90",
          !expanded && "line-clamp-4",
        )}
        aria-expanded={expanded}
      >
        {entry.reasoning}
      </button>
    </li>
  );
}

export interface ReasoningSidebarProps {
  className?: string;
  /** Pass the session JWT once it's surfaced; null disables WS. */
  wsToken: string | null;
}

export function ReasoningSidebar({ className, wsToken }: ReasoningSidebarProps) {
  const [filter, setFilter] = React.useState<string>("all");
  const params = React.useMemo(
    () =>
      filter === "all"
        ? { size: 50 }
        : { size: 50, decision: filter },
    [filter],
  );
  const { data, isLoading, error } = useJournal(params);

  const queryClient = useQueryClient();
  const { lastMessage } = useDashboardWs(WS_CHANNELS, wsToken);

  const [highlightedIds, setHighlightedIds] = React.useState<Set<number>>(
    new Set(),
  );

  React.useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.channel !== "dashboard_journal") return;
    // Trigger a refetch — we let the server be source of truth for ordering.
    queryClient.invalidateQueries({ queryKey: ["journal"] });
    // Pull the new id out of the payload if present and highlight on next render.
    const payload = lastMessage.payload as { id?: number } | undefined;
    if (!payload || typeof payload.id !== "number") return;
    const newId = payload.id;
    let cancelled = false;
    // Defer setState out of the effect body to avoid the cascading-render warning.
    const addHandle = window.setTimeout(() => {
      if (cancelled) return;
      setHighlightedIds((prev) => {
        const next = new Set(prev);
        next.add(newId);
        return next;
      });
    }, 0);
    const removeHandle = window.setTimeout(() => {
      if (cancelled) return;
      setHighlightedIds((prev) => {
        if (!prev.has(newId)) return prev;
        const next = new Set(prev);
        next.delete(newId);
        return next;
      });
    }, 1000);
    return () => {
      cancelled = true;
      window.clearTimeout(addHandle);
      window.clearTimeout(removeHandle);
    };
  }, [lastMessage, queryClient]);

  const items = data?.items ?? [];

  return (
    <section
      className={cn("flex h-full flex-col", className)}
      aria-label="AI reasoning"
    >
      <header className="flex items-center justify-between gap-3 border-b border-border px-3 py-3">
        <h2 className="text-lg font-semibold tracking-tight">AI Reasoning</h2>
        <div className="flex items-center gap-2">
          <Label
            htmlFor="decision-filter"
            className="text-xs uppercase tracking-wide text-muted-foreground"
          >
            Filter
          </Label>
          <Select
            id="decision-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="h-8 w-28"
          >
            {DECISION_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </Select>
        </div>
      </header>
      <div className="flex-1 overflow-y-auto">
        {error ? (
          <Alert variant="destructive" className="m-3">
            <AlertDescription>
              Failed to load journal: {error.message}
            </AlertDescription>
          </Alert>
        ) : null}
        {isLoading && !data ? (
          <ul className="space-y-2 p-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <li key={i}>
                <Skeleton className="h-16 w-full" />
              </li>
            ))}
          </ul>
        ) : null}
        {!isLoading && !error && items.length === 0 ? (
          <Alert variant="muted" className="m-3">
            <AlertDescription>
              Brain hasn&apos;t written any decisions yet. Run a routine to
              populate.
            </AlertDescription>
          </Alert>
        ) : null}
        {items.length > 0 ? (
          <ul role="list">
            {items.map((entry) => (
              <JournalRow
                key={entry.id}
                entry={entry}
                highlighted={highlightedIds.has(entry.id)}
              />
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
