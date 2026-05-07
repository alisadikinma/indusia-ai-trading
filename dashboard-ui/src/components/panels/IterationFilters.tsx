"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  ITERATION_FAILURE_MODES,
  ITERATION_OUTCOMES,
  ITERATION_RUN_TYPES,
  type IterationFailureMode,
  type IterationFilters,
  type IterationOutcome,
  type IterationRunType,
} from "@/lib/api-types";

export interface IterationFiltersProps {
  value: IterationFilters;
  onChange: (next: IterationFilters) => void;
}

/**
 * Filter controls for the Iteration History view.
 *
 * Single-value selects (run_type/outcome/failure_mode) emit '' when "all" is
 * selected — server interprets empty/missing as "no filter". Date range uses
 * datetime-local inputs.
 *
 * Mirrors JournalFilters.tsx UX conventions.
 */
export function IterationFilters({ value, onChange }: IterationFiltersProps) {
  const setField = React.useCallback(
    <K extends keyof IterationFilters>(key: K, v: IterationFilters[K]) => {
      onChange({ ...value, [key]: v });
    },
    [value, onChange],
  );

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-5">
      <div className="flex flex-col gap-1">
        <Label
          htmlFor="iter-filter-run-type"
          className="text-xs uppercase tracking-wide text-muted-foreground"
        >
          Run Type
        </Label>
        <Select
          id="iter-filter-run-type"
          data-testid="filter-run-type"
          value={value.run_type ?? ""}
          onChange={(e) =>
            setField(
              "run_type",
              e.target.value as Exclude<IterationRunType, "all"> | "",
            )
          }
          className="h-9"
        >
          {ITERATION_RUN_TYPES.map((t) => (
            <option key={t} value={t === "all" ? "" : t}>
              {t}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label
          htmlFor="iter-filter-outcome"
          className="text-xs uppercase tracking-wide text-muted-foreground"
        >
          Outcome
        </Label>
        <Select
          id="iter-filter-outcome"
          data-testid="filter-outcome"
          value={value.outcome ?? ""}
          onChange={(e) =>
            setField(
              "outcome",
              e.target.value as Exclude<IterationOutcome, "all"> | "",
            )
          }
          className="h-9"
        >
          {ITERATION_OUTCOMES.map((o) => (
            <option key={o} value={o === "all" ? "" : o}>
              {o}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label
          htmlFor="iter-filter-failure-mode"
          className="text-xs uppercase tracking-wide text-muted-foreground"
        >
          Failure Mode
        </Label>
        <Select
          id="iter-filter-failure-mode"
          data-testid="filter-failure-mode"
          value={value.failure_mode ?? ""}
          onChange={(e) =>
            setField(
              "failure_mode",
              e.target.value as Exclude<IterationFailureMode, "all"> | "",
            )
          }
          className="h-9"
        >
          {ITERATION_FAILURE_MODES.map((m) => (
            <option key={m} value={m === "all" ? "" : m}>
              {m}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-1">
        <Label
          htmlFor="iter-filter-from"
          className="text-xs uppercase tracking-wide text-muted-foreground"
        >
          From
        </Label>
        <Input
          id="iter-filter-from"
          type="datetime-local"
          value={value.from ?? ""}
          onChange={(e) => setField("from", e.target.value)}
          className="h-9"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label
          htmlFor="iter-filter-to"
          className="text-xs uppercase tracking-wide text-muted-foreground"
        >
          To
        </Label>
        <Input
          id="iter-filter-to"
          type="datetime-local"
          value={value.to ?? ""}
          onChange={(e) => setField("to", e.target.value)}
          className="h-9"
        />
      </div>
    </div>
  );
}
