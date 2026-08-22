import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  Power, TrendingUp, TrendingDown, AlertTriangle, Activity, Radio,
} from "lucide-react";

/* ============================================================================
   DATA LAYER — replace this whole block with real fetch/WebSocket calls.
   Field shapes mirror the Python backend directly:
     - PortfolioState  (src/risk/risk_engine.py)
     - RiskEvent       (src/risk/risk_engine.py)
     - RiskConfig      (config/config.yaml -> risk:)
   Wire points are marked TODO below.
   ========================================================================== */

const RISK_LIMITS = {
  maxDrawdownPct: 0.15,
  dailyLossLimitPct: 0.04,
  weeklyLossLimitPct: 0.08,
  maxLeverage: 2.0,
};

const BLEND_WEIGHTS = [
  { name: "momentum", weight: 0.35 },
  { name: "mean_reversion", weight: 0.35 },
  { name: "vol_regime", weight: 0.15 },
  { name: "satellite", weight: 0.15 },
];

function genEquitySeed(points = 180, start = 100000) {
  let eq = start;
  let peak = start;
  const out = [];
  const now = Date.now();
  for (let i = 0; i < points; i++) {
    const drift = (Math.random() - 0.47) * 0.006;
    eq = Math.max(eq * (1 + drift), start * 0.5);
    peak = Math.max(peak, eq);
    out.push({
      t: now - (points - i) * 3600 * 1000,
      equity: Math.round(eq),
      peak: Math.round(peak),
      drawdown: (peak - eq) / peak,
    });
  }
  return out;
}

function genPositions() {
  return [
    { asset: "BTC/USDT", weight: 0.182, uPnlPct: 0.0231, stop: 61120, take: 68420, price: 64810 },
    { asset: "ETH/USDT", weight: -0.094, uPnlPct: -0.0087, stop: 3390, take: 2960, price: 3210 },
    { asset: "SOL/USDT:USDT", weight: 0.071, uPnlPct: 0.0412, stop: 138.2, take: 168.5, price: 152.4 },
  ];
}

function genEvents() {
  const now = Date.now();
  return [
    { t: now - 1000 * 60 * 4, level: "info", text: "Correlation cap applied to [BTC/USDT, ETH/USDT]: gross 51% -> scaled by 0.88" },
    { t: now - 1000 * 60 * 47, level: "warn", text: "Realized vol z-score 2.8 — approaching extreme_vol_zscore threshold" },
    { t: now - 1000 * 60 * 60 * 3, level: "info", text: "Daily loss limit reset at UTC day rollover" },
    { t: now - 1000 * 60 * 60 * 9, level: "danger", text: "KILL SWITCH TRIGGERED: EXTREME_VOLATILITY — vol z-score 4.3 >= 4.0" },
    { t: now - 1000 * 60 * 60 * 9, level: "info", text: "Kill switch manually reset. Note: reviewed BTC funding spike, resuming." },
  ];
}

/* ========================================================================== */

const fmtPct = (v, d = 1) => `${(v * 100).toFixed(d)}%`;
const fmtUsd = (v) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const fmtTime = (ts) =>
  new Date(ts).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const timeAgo = (ts) => {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

function riskLevel(ratio) {
  if (ratio >= 0.85) return "danger";
  if (ratio >= 0.6) return "warn";
  return "safe";
}

function Gauge({ label, value, limit, format = fmtPct, unit = "" }) {
  const ratio = Math.min(value / limit, 1.25);
  const level = riskLevel(value / limit);
  const fillPct = Math.min(ratio / 1.25, 1) * 100;
  const tickPct = (1 / 1.25) * 100;
  return (
    <div className="gauge">
      <div className="gauge-row">
        <span className="gauge-label">{label}</span>
        <span className={`gauge-value c-${level}`}>
          {format(value)}
          <span className="gauge-limit"> / {format(limit)}{unit}</span>
        </span>
      </div>
      <div className="gauge-track">
        <div className={`gauge-fill c-${level}`} style={{ width: `${fillPct}%` }} />
        <div className="gauge-tick" style={{ left: `${tickPct}%` }} />
      </div>
    </div>
  );
}

function KillSwitch({ armed, onToggle }) {
  return (
    <button className={`kill-switch ${armed ? "armed" : "tripped"}`} onClick={onToggle}>
      <Power size={14} strokeWidth={2.2} />
      <span>{armed ? "ARMED" : "TRIPPED"}</span>
    </button>
  );
}

function EquityChart({ data }) {
  const last = data[data.length - 1];
  const domainMin = Math.min(...data.map((d) => d.equity)) * 0.995;
  const domainMax = Math.max(...data.map((d) => d.equity)) * 1.005;
  return (
    <ResponsiveContainer width="100%" height={230}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3FB6A8" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#3FB6A8" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1B222C" vertical={false} />
        <XAxis
          dataKey="t"
          tickFormatter={fmtTime}
          stroke="#5A6572"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
          axisLine={{ stroke: "#232B36" }}
          tickLine={false}
          minTickGap={40}
        />
        <YAxis
          domain={[domainMin, domainMax]}
          tickFormatter={(v) => `$${Math.round(v / 1000)}k`}
          stroke="#5A6572"
          tick={{ fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        <ReferenceLine y={last.peak} stroke="#5A6572" strokeDasharray="3 3" strokeWidth={1} />
        <Tooltip
          contentStyle={{
            background: "#161D27", border: "1px solid #232B36", borderRadius: 4,
            fontFamily: "IBM Plex Mono, monospace", fontSize: 12, color: "#E7EDF3",
          }}
          labelFormatter={fmtTime}
          formatter={(v) => [fmtUsd(v), "equity"]}
        />
        <Area type="monotone" dataKey="equity" stroke="#3FB6A8" strokeWidth={1.75} fill="url(#eqFill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export default function Dashboard() {
  const [equitySeries, setEquitySeries] = useState(() => genEquitySeed());
  const [positions, setPositions] = useState(() => genPositions());
  const [events, setEvents] = useState(() => genEvents());
  const [armed, setArmed] = useState(true);
  const [now, setNow] = useState(Date.now());
  const [mode] = useState("PAPER"); // TODO: read from execution engine mode
  const tickRef = useRef(0);

  // Simulated live updates — TODO: replace with WebSocket/poll to your
  // monitoring API. Keep the same field shapes so components don't change.
  useEffect(() => {
    const id = setInterval(() => {
      setNow(Date.now());
      tickRef.current += 1;
      setEquitySeries((prev) => {
        const last = prev[prev.length - 1];
        const drift = (Math.random() - 0.48) * 0.0035;
        const eq = Math.max(last.equity * (1 + drift), 1000);
        const peak = Math.max(last.peak, eq);
        const next = { t: Date.now(), equity: Math.round(eq), peak: Math.round(peak), drawdown: (peak - eq) / peak };
        return [...prev.slice(1), next];
      });
      if (tickRef.current % 9 === 0) {
        setPositions((prev) =>
          prev.map((p) => ({ ...p, uPnlPct: p.uPnlPct + (Math.random() - 0.5) * 0.004 }))
        );
      }
    }, 2600);
    return () => clearInterval(id);
  }, []);

  const last = equitySeries[equitySeries.length - 1];
  const dayStart = equitySeries[Math.max(0, equitySeries.length - 24)];
  const dailyPnlPct = (last.equity - dayStart.equity) / dayStart.equity;
  const drawdownPct = last.drawdown;
  const weeklyPnlPct = (last.equity - equitySeries[0].equity) / equitySeries[0].equity;
  const grossExposure = positions.reduce((s, p) => s + Math.abs(p.weight), 0);
  const leverage = grossExposure; // simplified: assumes 1x equity base

  const chartData = useMemo(() => equitySeries, [equitySeries]);

  return (
    <div className="dash">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
        .dash {
          --bg: #0B0F14; --panel: #121821; --panel-alt: #161D27; --border: #232B36;
          --text: #E7EDF3; --text-dim: #8A97A6; --text-faint: #5A6572;
          --safe: #3FB6A8; --warn: #E0A63A; --danger: #D6524A; --info: #5B8DEF;
          background: var(--bg); color: var(--text); font-family: 'IBM Plex Mono', monospace;
          border-radius: 10px; border: 1px solid var(--border); overflow: hidden;
          font-size: 13px; line-height: 1.4;
        }
        .dash * { box-sizing: border-box; }
        .c-safe { color: var(--safe); } .c-warn { color: var(--warn); } .c-danger { color: var(--danger); } .c-info { color: var(--info); }
        .eyebrow {
          font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 11px;
          letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-faint); margin-bottom: 10px; display: block;
        }
        .statusbar {
          display: flex; align-items: center; gap: 24px; padding: 14px 20px;
          border-bottom: 1px solid var(--border); background: var(--panel-alt); flex-wrap: wrap;
        }
        .status-item { display: flex; flex-direction: column; gap: 2px; }
        .status-item .k { font-size: 10px; color: var(--text-faint); letter-spacing: 0.06em; text-transform: uppercase; }
        .status-item .v { font-size: 15px; font-weight: 500; }
        .mode-pill {
          display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 20px;
          background: rgba(91,141,239,0.12); color: var(--info); font-size: 11px; font-weight: 500; letter-spacing: 0.04em;
        }
        .kill-switch {
          margin-left: auto; display: flex; align-items: center; gap: 7px; padding: 7px 14px;
          border-radius: 6px; border: 1px solid; font-family: 'IBM Plex Mono', monospace; font-size: 12px;
          font-weight: 600; letter-spacing: 0.06em; cursor: pointer; background: transparent; transition: opacity 0.15s;
        }
        .kill-switch:hover { opacity: 0.85; }
        .kill-switch.armed { color: var(--safe); border-color: var(--safe); }
        .kill-switch.tripped { color: var(--danger); border-color: var(--danger); background: rgba(214,82,74,0.08); }
        .grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 1px; background: var(--border); }
        .col { display: flex; flex-direction: column; gap: 1px; background: var(--border); }
        .panel { background: var(--panel); padding: 16px 20px; }
        .panel-title {
          font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 12px;
          letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-dim); margin-bottom: 12px;
        }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th { text-align: left; color: var(--text-faint); font-weight: 500; font-size: 10.5px; letter-spacing: 0.05em; text-transform: uppercase; padding-bottom: 8px; }
        td { padding: 7px 0; border-top: 1px solid var(--border); }
        td.num { font-variant-numeric: tabular-nums; }
        .pos-asset { font-weight: 500; }
        .dir-tag { font-size: 10px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; letter-spacing: 0.03em; }
        .dir-long { background: rgba(63,182,168,0.14); color: var(--safe); }
        .dir-short { background: rgba(214,82,74,0.14); color: var(--danger); }
        .gauge { margin-bottom: 14px; }
        .gauge:last-child { margin-bottom: 0; }
        .gauge-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 5px; }
        .gauge-label { color: var(--text-dim); font-size: 12px; }
        .gauge-value { font-weight: 600; font-size: 12.5px; font-variant-numeric: tabular-nums; }
        .gauge-limit { color: var(--text-faint); font-weight: 400; }
        .gauge-track { position: relative; height: 6px; background: var(--panel-alt); border-radius: 3px; overflow: visible; }
        .gauge-fill { position: absolute; left: 0; top: 0; height: 100%; border-radius: 3px; transition: width 0.4s ease; }
        .gauge-fill.c-safe { background: var(--safe); } .gauge-fill.c-warn { background: var(--warn); } .gauge-fill.c-danger { background: var(--danger); }
        .gauge-tick { position: absolute; top: -2px; width: 2px; height: 10px; background: var(--text-faint); }
        .blend-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .blend-row:last-child { margin-bottom: 0; }
        .blend-name { width: 108px; font-size: 12px; color: var(--text-dim); flex-shrink: 0; }
        .blend-bar-track { flex: 1; height: 5px; background: var(--panel-alt); border-radius: 3px; }
        .blend-bar-fill { height: 100%; background: var(--info); border-radius: 3px; }
        .blend-val { width: 40px; text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; color: var(--text-dim); }
        .log-list { display: flex; flex-direction: column; gap: 0; max-height: 210px; overflow-y: auto; }
        .log-row { display: flex; gap: 10px; padding: 7px 0; border-top: 1px solid var(--border); font-size: 12px; }
        .log-row:first-child { border-top: none; }
        .log-dot { width: 6px; height: 6px; border-radius: 50%; margin-top: 5px; flex-shrink: 0; }
        .log-dot.info { background: var(--info); } .log-dot.warn { background: var(--warn); } .log-dot.danger { background: var(--danger); }
        .log-text { color: var(--text-dim); flex: 1; }
        .log-time { color: var(--text-faint); font-size: 11px; white-space: nowrap; }
        .heartbeat { display: flex; align-items: center; gap: 5px; color: var(--text-faint); font-size: 11px; }
        .pulse { width: 6px; height: 6px; border-radius: 50%; background: var(--safe); animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
        @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } .gauge-fill { transition: none; } }
        @media (max-width: 880px) { .grid { grid-template-columns: 1fr; } }
      `}</style>

      <div className="statusbar">
        <span className="mode-pill"><Radio size={11} />{mode}</span>
        <div className="status-item">
          <span className="k">Equity</span>
          <span className="v">{fmtUsd(last.equity)}</span>
        </div>
        <div className="status-item">
          <span className="k">Daily P&amp;L</span>
          <span className={`v ${dailyPnlPct >= 0 ? "c-safe" : "c-danger"}`}>
            {dailyPnlPct >= 0 ? "+" : ""}{fmtPct(dailyPnlPct, 2)}
          </span>
        </div>
        <div className="status-item">
          <span className="k">Drawdown</span>
          <span className={`v c-${riskLevel(drawdownPct / RISK_LIMITS.maxDrawdownPct)}`}>{fmtPct(drawdownPct, 2)}</span>
        </div>
        <div className="heartbeat"><span className="pulse" />last heartbeat {timeAgo(now - 1200)}</div>
        <KillSwitch armed={armed} onToggle={() => setArmed((a) => !a)} />
      </div>

      <div className="grid">
        <div className="col">
          <div className="panel">
            <div className="panel-title">Equity curve</div>
            <EquityChart data={chartData} />
          </div>
          <div className="panel">
            <div className="panel-title">Positions</div>
            <table>
              <thead>
                <tr><th>Asset</th><th>Weight</th><th>uPnL</th><th>Stop / Take</th></tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.asset}>
                    <td>
                      <span className="pos-asset">{p.asset}</span>
                      <span className={`dir-tag ${p.weight >= 0 ? "dir-long" : "dir-short"}`}>
                        {p.weight >= 0 ? "LONG" : "SHORT"}
                      </span>
                    </td>
                    <td className="num">{fmtPct(Math.abs(p.weight))}</td>
                    <td className={`num ${p.uPnlPct >= 0 ? "c-safe" : "c-danger"}`}>
                      {p.uPnlPct >= 0 ? "+" : ""}{fmtPct(p.uPnlPct, 2)}
                    </td>
                    <td className="num c-faint">{p.stop.toLocaleString()} / {p.take.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="col">
          <div className="panel">
            <div className="panel-title">Risk gauges</div>
            <Gauge label="Drawdown" value={drawdownPct} limit={RISK_LIMITS.maxDrawdownPct} />
            <Gauge label="Daily loss" value={Math.max(-dailyPnlPct, 0)} limit={RISK_LIMITS.dailyLossLimitPct} />
            <Gauge label="Weekly loss" value={Math.max(-weeklyPnlPct, 0)} limit={RISK_LIMITS.weeklyLossLimitPct} />
            <Gauge
              label="Leverage"
              value={leverage}
              limit={RISK_LIMITS.maxLeverage}
              format={(v) => `${v.toFixed(2)}x`}
            />
          </div>
          <div className="panel">
            <div className="panel-title">Strategy blend</div>
            {BLEND_WEIGHTS.map((s) => (
              <div className="blend-row" key={s.name}>
                <span className="blend-name">{s.name}</span>
                <div className="blend-bar-track">
                  <div className="blend-bar-fill" style={{ width: `${s.weight * 100}%` }} />
                </div>
                <span className="blend-val">{s.weight.toFixed(2)}</span>
              </div>
            ))}
          </div>
          <div className="panel">
            <div className="panel-title">Event log</div>
            <div className="log-list">
              {events.map((e, i) => (
                <div className="log-row" key={i}>
                  <span className={`log-dot ${e.level}`} />
                  <span className="log-text">{e.text}</span>
                  <span className="log-time">{timeAgo(e.t)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
