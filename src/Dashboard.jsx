import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "./api";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [status, config, portfolio] = await Promise.all([api.status(), api.config(), api.portfolio()]);
      setData({ status, config, portfolio }); setError("");
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 5000); return () => clearInterval(timer); }, [refresh]);
  return <main className="dashboard">
    <header><div><h1>Adaptive Trading System</h1><p>Live monitoring dashboard · no simulated market data</p></div><button onClick={refresh}><RefreshCw size={15}/> Refresh</button></header>
    {error && <div className="error">{error}</div>}
    <section className="grid">
      <Card label="Backend" value={error ? "OFFLINE" : data ? "ONLINE" : "CONNECTING…"}/>
      <Card label="Exchange" value={data?.status?.exchange || "—"}/>
      <Card label="Environment" value={data?.status?.testnet ? "TESTNET" : data ? "LIVE" : "—"}/>
      <Card label="Kill switch" value={data?.status?.kill_switch ? "TRIPPED" : data ? "ARMED" : "—"}/>
    </section>
    <h2>Portfolio</h2>
    <section className="grid">
      <Card label="Equity" value={money(data?.portfolio?.equity)}/>
      <Card label="Daily P&L" value={percent(data?.portfolio?.daily_pnl_pct)}/>
      <Card label="Weekly P&L" value={percent(data?.portfolio?.weekly_pnl_pct)}/>
      <Card label="Gross exposure" value={percent(data?.portfolio?.gross_exposure)}/>
    </section>
    <div className="empty">{data?.portfolio?.positions?.length ? "Live positions available." : "No positions are currently reported by the backend."}</div>
  </main>;
}
function Card({ label, value }) { return <div className="card"><span>{label}</span><strong>{value}</strong></div>; }
function percent(v) { return v == null ? "—" : `${(Number(v) * 100).toFixed(2)}%`; }
function money(v) { return v == null ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }); }
