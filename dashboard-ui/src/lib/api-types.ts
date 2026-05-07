// Types mirroring pulse_bridge.dashboard_routes Pydantic schemas.
// Keep in sync with pulse-bridge/pulse_bridge/dashboard_routes/*.py.

export interface OhlcvPoint {
  ts: string; // ISO 8601
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface JournalEntry {
  id: number;
  ts: string;
  signal_id: number | null;
  regime: string;
  decision: string;
  reasoning: string;
  confidence: number | null;
  expected_outcome: string | null;
  actual_outcome: string | null;
  actual_pnl_pct: number | null;
  outcome_recorded_at: string | null;
}

export interface JournalPage {
  items: JournalEntry[];
  total: number;
  page: number;
  size: number;
}

export interface Position {
  signal_id: number;
  pair: string;
  side: "long" | "short" | "unknown";
  decided_at: string;
  intended_size_mult: number | null;
  price_at_signal: number;
}

export interface EquityPoint {
  ts: string;
  equity_usd: number;
  realized_pnl: number;
  unrealized_pnl: number;
  open_positions: number;
  drawdown_pct: number;
}

export interface BacktestMetrics {
  sharpe?: number;
  sortino?: number;
  max_dd?: number;
  profit_factor?: number;
  total_trades?: number;
  win_rate?: number;
  expectancy?: number;
  [k: string]: unknown;
}

export interface BacktestEquityPoint {
  ts: string;
  equity: number;
}

export interface BacktestTrade {
  ts: string;
  side?: "long" | "short" | string;
  price?: number;
  pnl_pct?: number;
  pnl?: number;
  pair?: string;
  exit_ts?: string;
  exit_price?: number;
  [k: string]: unknown;
}

export interface BacktestRunMeta {
  id: number;
  started_at: string;
  completed_at: string | null;
  strategy_version: string;
  fold_index: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  metrics: BacktestMetrics;
  gate_passed: boolean;
  notes: string | null;
}

export interface BacktestRunDetail extends BacktestRunMeta {
  parameters: Record<string, unknown>;
  equity_curve: BacktestEquityPoint[] | null;
  trades: BacktestTrade[] | null;
}

// Phase 9 gate criteria — Iron Law 2.
export const PHASE_9_GATES = {
  sharpe_min: 1.5,
  max_dd_max: 0.25,
  profit_factor_min: 1.4,
  total_trades_min: 100,
} as const;

export interface FreqaiCalibration {
  calibration: Array<Record<string, unknown>>;
  auc_history: Array<Record<string, unknown>>;
  feature_importance: Record<string, unknown> | null;
  note: string;
}

export interface RiskState {
  drawdown_pct: number | null;
  daily_pnl: number | null;
  open_positions: number;
  circuit_breaker_state: "green" | "amber" | "red";
  note?: string | null;
}

export interface IterationRun {
  id: number;
  started_at: string;
  completed_at: string | null;
  run_type: string;
  cycle_n: number | null;
  failure_mode: string | null;
  hypothesis: string | null;
  adr_ref: string | null;
  metrics_before: Record<string, unknown> | null;
  metrics_after: Record<string, unknown> | null;
  outcome: string | null;
  summary: string | null;
}

export interface WsMessage {
  channel?: "dashboard_signals" | "dashboard_journal" | "dashboard_equity";
  payload?: unknown;
  type?: "ping" | "pong";
}
