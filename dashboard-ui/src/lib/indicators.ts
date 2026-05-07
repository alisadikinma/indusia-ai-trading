// Client-side technical indicator computation.
//
// Real formulas — no fake values, no constants. Iron Law 3.
// Indicators are display-only here; the strategy's authoritative indicators
// live server-side in freqtrade-fork (execution-only). The dashboard
// recomputes them visually so the operator can see what the brain sees.

export interface Candle {
  ts: number; // unix epoch (seconds)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LinePoint {
  time: number;
  value: number;
}

/**
 * Exponential Moving Average.
 *
 * EMA[i] = close[i] * k + EMA[i-1] * (1 - k), k = 2 / (period + 1)
 * Seed: SMA of the first `period` closes.
 *
 * Returns one LinePoint per input candle from index `period - 1` onward.
 */
export function ema(candles: Candle[], period: number): LinePoint[] {
  if (period < 1 || candles.length < period) return [];
  const k = 2 / (period + 1);
  const out: LinePoint[] = [];
  let sum = 0;
  for (let i = 0; i < period; i++) sum += candles[i].close;
  let prev = sum / period;
  out.push({ time: candles[period - 1].ts, value: prev });
  for (let i = period; i < candles.length; i++) {
    prev = candles[i].close * k + prev * (1 - k);
    out.push({ time: candles[i].ts, value: prev });
  }
  return out;
}

/**
 * Wilder's smoothing — used for ATR/ADX. Equivalent to EMA with alpha = 1/period.
 */
function wilderSmooth(values: number[], period: number): number[] {
  if (values.length < period) return [];
  const out: number[] = [];
  // Seed: simple sum of the first `period` values.
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum;
  out.push(prev);
  for (let i = period; i < values.length; i++) {
    prev = prev - prev / period + values[i];
    out.push(prev);
  }
  return out;
}

/**
 * Average Directional Index (ADX), Wilder's classic period-14 formulation.
 *
 *   TR     = max(high - low, |high - prev_close|, |low - prev_close|)
 *   +DM    = if (high - prev_high) > (prev_low - low) and > 0 then (high - prev_high) else 0
 *   -DM    = if (prev_low - low) > (high - prev_high) and > 0 then (prev_low - low) else 0
 *   ATR    = wilder-smoothed TR
 *   +DI14  = 100 * wilder-smoothed +DM / ATR
 *   -DI14  = 100 * wilder-smoothed -DM / ATR
 *   DX     = 100 * |+DI14 - -DI14| / (+DI14 + -DI14)
 *   ADX    = wilder-smoothed DX
 *
 * Returns one LinePoint per candle starting from the first index where ADX
 * is defined (≈ 2 * period).
 */
export function adx(candles: Candle[], period = 14): LinePoint[] {
  if (candles.length < period * 2 + 1) return [];

  const tr: number[] = [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];

  for (let i = 1; i < candles.length; i++) {
    const c = candles[i];
    const p = candles[i - 1];
    const highMinusLow = c.high - c.low;
    const highMinusPrevClose = Math.abs(c.high - p.close);
    const lowMinusPrevClose = Math.abs(c.low - p.close);
    tr.push(Math.max(highMinusLow, highMinusPrevClose, lowMinusPrevClose));
    const upMove = c.high - p.high;
    const downMove = p.low - c.low;
    plusDM.push(upMove > downMove && upMove > 0 ? upMove : 0);
    minusDM.push(downMove > upMove && downMove > 0 ? downMove : 0);
  }

  const atr = wilderSmooth(tr, period);
  const plusDMSmoothed = wilderSmooth(plusDM, period);
  const minusDMSmoothed = wilderSmooth(minusDM, period);
  if (atr.length === 0) return [];

  const dx: number[] = [];
  for (let i = 0; i < atr.length; i++) {
    const a = atr[i];
    if (a === 0) {
      dx.push(0);
      continue;
    }
    const plusDI = (100 * plusDMSmoothed[i]) / a;
    const minusDI = (100 * minusDMSmoothed[i]) / a;
    const sum = plusDI + minusDI;
    dx.push(sum === 0 ? 0 : (100 * Math.abs(plusDI - minusDI)) / sum);
  }

  // Smooth DX once more with Wilder to get ADX; need at least `period` DX values.
  if (dx.length < period) return [];
  const adxSmoothed: number[] = [];
  let sum = 0;
  for (let i = 0; i < period; i++) sum += dx[i];
  let prev = sum / period;
  adxSmoothed.push(prev);
  for (let i = period; i < dx.length; i++) {
    prev = (prev * (period - 1) + dx[i]) / period;
    adxSmoothed.push(prev);
  }

  // Map back to candle timestamps. ADX[i] corresponds to candle index
  // `period (TR offset) + period - 1 (atr seed) + period - 1 (adx seed) + i`.
  const offset = period + (period - 1) + (period - 1);
  const out: LinePoint[] = [];
  for (let i = 0; i < adxSmoothed.length; i++) {
    const idx = offset + i;
    if (idx >= candles.length) break;
    out.push({ time: candles[idx].ts, value: adxSmoothed[i] });
  }
  return out;
}
