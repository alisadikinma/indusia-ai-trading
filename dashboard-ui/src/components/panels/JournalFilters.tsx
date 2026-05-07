"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  JOURNAL_DECISIONS,
  JOURNAL_OUTCOMES,
  JOURNAL_REGIMES,
  type BrainJournalFilters,
} from "@/lib/api-types";

export interface JournalFiltersProps {
  value: BrainJournalFilters;
  onChange: (next: BrainJournalFilters) => void;
}

/**
 * Filter controls for the Brain Journal view.
 *
 * Single-value selects (regime/decision/outcome) emit '' when "all" is
 * selected — server interprets empty/missing as "no filter". Multi-value
 * support is wire-level (comma-separated); the UI ships single-select for
 * Phase 1.5.F to keep the surface tight and matches operator workflow
 * (filter to one regime, scan, switch). Multi-select can land later without
 * an API change.
 *
 * Search input is debounced via the parent (parent passes a stable
 * onChange and decides when to fire); we just propagate every keystroke.
 */
export function JournalFilters({ value, onChange }: JournalFiltersProps) {
  const setField = React.useCallback(
    <K extends keyof BrainJournalFilters>(
      key: K,
      v: BrainJournalFilters[K],
    ) => {
      onChange({ ...value, [key]: v });
    },
    [value, onChange],
  );

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-6">
      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-regime" className="text-xs uppercase tracking-wide text-muted-foreground">
          Regime
        </Label>
        <Select
          id="journal-filter-regime"
          value={value.regime ?? ""}
          onChange={(e) =>
            setField("regime", e.target.value === "all" ? "" : e.target.value)
          }
          className="h-9"
        >
          {JOURNAL_REGIMES.map((r) => (
            <option key={r} value={r === "all" ? "" : r}>
              {r}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-decision" className="text-xs uppercase tracking-wide text-muted-foreground">
          Decision
        </Label>
        <Select
          id="journal-filter-decision"
          value={value.decision ?? ""}
          onChange={(e) =>
            setField("decision", e.target.value === "all" ? "" : e.target.value)
          }
          className="h-9"
        >
          {JOURNAL_DECISIONS.map((d) => (
            <option key={d} value={d === "all" ? "" : d}>
              {d}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-outcome" className="text-xs uppercase tracking-wide text-muted-foreground">
          Outcome
        </Label>
        <Select
          id="journal-filter-outcome"
          value={value.outcome ?? ""}
          onChange={(e) =>
            setField("outcome", e.target.value === "all" ? "" : e.target.value)
          }
          className="h-9"
        >
          {JOURNAL_OUTCOMES.map((o) => (
            <option key={o} value={o === "all" ? "" : o}>
              {o}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-from" className="text-xs uppercase tracking-wide text-muted-foreground">
          From
        </Label>
        <Input
          id="journal-filter-from"
          type="datetime-local"
          value={value.from ?? ""}
          onChange={(e) => setField("from", e.target.value)}
          className="h-9"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-to" className="text-xs uppercase tracking-wide text-muted-foreground">
          To
        </Label>
        <Input
          id="journal-filter-to"
          type="datetime-local"
          value={value.to ?? ""}
          onChange={(e) => setField("to", e.target.value)}
          className="h-9"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="journal-filter-q" className="text-xs uppercase tracking-wide text-muted-foreground">
          Search reasoning
        </Label>
        <Input
          id="journal-filter-q"
          type="search"
          placeholder="full-text..."
          value={value.q ?? ""}
          onChange={(e) => setField("q", e.target.value)}
          className="h-9"
        />
      </div>
    </div>
  );
}
