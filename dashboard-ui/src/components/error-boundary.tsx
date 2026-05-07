"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// CockpitErrorBoundary — A.5 Error Boundaries
//
// Wraps each *-client.tsx render tree so that render-time exceptions (not just
// fetch errors) produce a recoverable UI instead of a blank screen.
//
// React 19 doesn't ship a hooks-only error boundary — this must be a class
// component. The `fallback` prop can be a ReactNode (static message) or a
// render-prop `(error, reset) => ReactNode` for custom recovery UIs.
// ---------------------------------------------------------------------------

type FallbackFn = (error: Error, reset: () => void) => React.ReactNode;

export interface ErrorBoundaryProps {
  /**
   * Static node or render-prop:
   *   <ErrorBoundary fallback={<p>boom</p>}>
   *   <ErrorBoundary fallback={(err, reset) => <button onClick={reset}>retry</button>}>
   */
  fallback?: React.ReactNode | FallbackFn;
  /**
   * Optional human-readable name used in the console.error prefix so the
   * operator knows which view crashed.
   */
  viewName?: string;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    const view = this.props.viewName ?? "unknown view";
    // eslint-disable-next-line no-console
    console.error(
      `[cockpit-error-boundary] Render exception in "${view}":`,
      error,
      info.componentStack,
    );
  }

  reset(): void {
    this.setState({ hasError: false, error: null });
  }

  render(): React.ReactNode {
    if (!this.state.hasError || this.state.error == null) {
      return this.props.children;
    }

    const { fallback, viewName } = this.props;
    const error = this.state.error;
    const reset = this.reset;

    if (typeof fallback === "function") {
      return (fallback as FallbackFn)(error, reset);
    }

    if (fallback !== undefined) {
      return fallback;
    }

    // Default fallback — consistent style across all 5 views.
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-6 text-center">
        <p className="text-sm font-medium text-destructive">
          Something broke in the {viewName ?? "cockpit"} view.
        </p>
        <p className="max-w-sm text-xs text-muted-foreground">
          {error.message}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.location.reload()}
          aria-label="Reload the page to recover"
        >
          Reload
        </Button>
      </div>
    );
  }
}
