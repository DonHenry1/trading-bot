# Dashboard

Instrument-panel style monitoring UI for the trading system: equity curve,
per-asset positions, risk gauges (drawdown / daily / weekly / leverage —
each plotted against the actual limit from `config/config.yaml`), the
strategy blend weights, and a live event log for kill-switch / circuit
breaker activity.

Currently running on **generated mock data** so you can see it end to end
before any backend exists. Every value it shows corresponds 1:1 to a real
field in the Python backend — swapping to live data is a data-fetching
change, not a redesign.

## Run it

```bash
cd frontend
npm install
npm run dev
```

Opens on `http://localhost:5173`.

## Wiring to the real backend

Everything to change lives in `src/Dashboard.jsx`, marked with `TODO`:

1. **Data layer block at the top of the file** (`genEquitySeed`,
   `genPositions`, `genEvents`) — replace with fetch calls to whatever you
   expose from the Python side. Suggested shape: a small FastAPI/Flask
   service that reads `RiskEngine.events`, `PortfolioState`, and the paper
   or live `ExecutionEngine`'s current positions, and serves them as JSON.
2. **The `useEffect` polling interval** — replace the `setInterval` mock
   tick with either a `fetch()` poll (every 2–5s is plenty for hourly-bar
   strategies) or a WebSocket subscription if you want push updates.
3. **`RISK_LIMITS` and `BLEND_WEIGHTS` constants** — these should come
   from `config/config.yaml` (serve it as JSON alongside the live data, or
   hardcode-mirror it — just keep it in sync, since the gauges are only
   meaningful if the limit shown matches the limit actually enforced).

The kill-switch button in the UI is currently **display-only** — it
flips local state so you can see both visual states, but it isn't wired
to `RiskEngine.manual_kill_switch()` / `reset_kill_switch()`. Wire that
deliberately and with a confirmation step; this is the one control in
the dashboard that should never fire on a stray click.
