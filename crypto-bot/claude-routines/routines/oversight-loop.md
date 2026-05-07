# Oversight Loop Routine

The 5-minute cron that drives the crypto bot's Claude oversight brain. This
routine is what fires every cycle against pulse-bridge; it composes the five
playbook skills, classifies regime, decides on each pending signal, runs
post-mortem when losing trades close, and POSTs structured decisions to
`/v1/decide`.

## Cadence

```cron
*/5 * * * *   /opt/ai-trading/crypto-bot/claude-routines/routines/oversight-loop.invoke.sh
```

Every 5 minutes (UTC). Cycle budget target: <= 30 seconds end-to-end.
Hard timeout: 60 seconds; on timeout the cron wrapper logs
`decision='halt'` to `brain.brain_journal` and exits.

The 5-minute cadence aligns with the Anthropic prompt-cache TTL (5 minutes)
so the stable prefix of `/v1/context_bundle` (Iron Laws + skill list +
schema summary, see `pulse-bridge/pulse_bridge/v1_routes/context.py`) hits
cache on the vast majority of cycles.

## Procedure

1. **Fetch context.** GET
   `/v1/context_bundle?pair=BTC/USDT&tf=15m` with HMAC headers
   (`X-PULSE-Timestamp`, `X-PULSE-Signature`) added by the cron wrapper.
   Returns `stable` (Iron Laws + 5-skill playbook) + `dynamic` (last 4h
   OHLCV, open positions, pending signals, recent journal, equity,
   drawdown_pct).
2. **Load knowledge surfaces.** Per ADR-002 precedence
   (Iron Laws > skills > references > memory > training data), read in
   order: skills (`regime-detection.md`, `signal-evaluation.md`,
   `trading-discipline.md`, `known-traps.md`, `post-mortem-protocol.md`),
   then memory under `crypto-bot/claude-routines/memory/*.md`, then the 10
   most-recent `recent_journal` entries in the bundle. References inject
   automatically via `--append-system-prompt-file` per the routine
   template.
3. **Classify regime.** Run `regime-detection.md` against
   `dynamic.ohlcv_last_4h` plus 30-day ATR baseline. Output exactly one
   of `trending_up | trending_down | ranging | volatile` plus a 1-10
   confidence integer.
4. **Decide each pending signal.** For every entry in
   `dynamic.pending_signals`:
   a. If signal `ts` older than 15 minutes -> skip (Iron Rule 3 in
      `trading-discipline.md`).
   b. Run the 7-item checklist from `signal-evaluation.md`.
   c. Apply Iron Rules from `trading-discipline.md` (rules override any
      checklist APPROVE).
   d. POST `/v1/decide` per the API contract below.
5. **Post-mortem.** Query `brain.brain_journal` for rows with
   `actual_pnl_pct < -1.0` and `ts >= now() - interval '5 minutes'`. For
   each hit, run `post-mortem-protocol.md` Procedure. The runtime brain
   emits the structured JSON to stdout only; file writes to
   `known-traps.md` and `memory/*` are reserved for the Phase 6 weekly
   cron (Iron Law 4).

## API contract

The exact JSON shape POSTed in step 4.d, matching `DecideRequest` in
`pulse-bridge/pulse_bridge/v1_routes/decide.py`:

```json
{
  "signal_id": 1234,
  "regime": "trending_up",
  "decision": "approve",
  "size_mult": null,
  "reasoning": "Regime=trending_up (conf 8/10): ADX14=31.4. Checklist 7/7 pass.",
  "confidence": 8,
  "expected_outcome": "Hold to ROI ladder; trail 2x ATR(14)."
}
```

Field rules (enforced by Pydantic, the routine MUST NOT violate):
- `signal_id`: int >= 1.
- `regime`: one of `trending_up | trending_down | ranging | volatile`.
- `decision`: one of `approve | veto | resize`.
- `size_mult`: float in [0.5, 1.5], REQUIRED if `decision='resize'`,
  forbidden otherwise.
- `reasoning`: 10-4000 chars. Iron Rule 5 enforced both here and by API.
- `confidence`: int in [1, 10].
- `expected_outcome`: optional, max 2000 chars.

Endpoint requires HMAC auth via `X-PULSE-Timestamp` + `X-PULSE-Signature`
(see `pulse-bridge/pulse_bridge/v1_routes/auth.py`). 200 returns
`{signal_id, decision_recorded_at, journal_id}`. 409 means the signal
already has a decision (idempotent; do not retry). 422 means a Pydantic
violation in our payload (bug; halt + alert). 401 means HMAC mismatch
(halt + alert).

The 5 skill files this routine loads:
- `regime-detection.md`
- `signal-evaluation.md`
- `trading-discipline.md`
- `known-traps.md`
- `post-mortem-protocol.md`

## Failure handling

- pulse-bridge unreachable / 5xx -> log to systemd journal, exit cycle
  cleanly, retry next 5-min tick. Do NOT write to
  `crypto-bot/claude-routines/memory/*` from a failed run -- partial
  state corrupts the append-only audit log.
- pulse-bridge 401 (HMAC mismatch) -> emit Telegram alert, halt loop
  until operator resets HMAC secret.
- pulse-bridge 422 (validation) -> bug in routine output formatter; emit
  Telegram alert, halt loop, dump raw payload to systemd journal.
- pulse-bridge 409 (already decided) -> benign idempotency; skip the
  signal and continue.
- Reference-vs-skill conflict detected during step 2 -> per ADR-002 the
  brain must abstain: POST `decision='veto'` (when a pending signal is in
  scope) with reasoning containing "ref-skill-conflict" and emit
  Telegram alert.
- Cycle timeout (>60s) -> wrapper kills the process, logs
  `decision='halt'` once to `brain.brain_journal`, no skill-side
  recovery required.
