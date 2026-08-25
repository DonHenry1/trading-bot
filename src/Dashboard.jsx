import React,{useCallback,useEffect,useState} from "react";
import {Activity,Play,Square,ShieldAlert,RefreshCw,Wallet} from "lucide-react";
import {api} from "./api";

export default function Dashboard(){
 const [state,setState]=useState(null),[signals,setSignals]=useState([]),[events,setEvents]=useState([]),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 const refresh=useCallback(async()=>{try{const [status,portfolio,s,e]=await Promise.all([api.status(),api.portfolio(),api.signals(),api.events()]);setState({status,portfolio});setSignals(s.markets||[]);setEvents(e.events||[]);setError("")}catch(err){setError(err.message)}},[]);
 useEffect(()=>{refresh();const t=setInterval(refresh,5000);return()=>clearInterval(t)},[refresh]);
 const action=async fn=>{setBusy(true);try{await fn();await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}};
 const status=state?.status;
 return <main className="dashboard">
  <header><div><div className="eyebrow"><Activity size={14}/> ADAPTIVE PERPL ENGINE</div><h1>Trading Command Center</h1><p>Real market data · risk-gated execution · paper-first by default</p></div><button className="ghost" onClick={refresh}><RefreshCw size={15}/> Refresh</button></header>
  {error&&<div className="error">{error}</div>}
  <section className="hero"><div><span>BOT STATUS</span><strong>{status?.running?"RUNNING":"STOPPED"}</strong></div><div><span>MODE</span><strong>{status?.mode||"—"}</strong></div><div><span>EXCHANGE</span><strong>PERPL</strong></div><div><span>RISK GATE</span><strong>{status?.kill_switch?"LOCKED":"ARMED"}</strong></div></section>
  <section className="actions"><button disabled={busy} onClick={()=>action(api.start)}><Play size={15}/> Start bot</button><button disabled={busy} className="ghost" onClick={()=>action(api.stop)}><Square size={15}/> Stop</button><button disabled={busy} className="danger" onClick={()=>action(api.kill)}><ShieldAlert size={15}/> Emergency stop</button><a className="ghost link" href="https://app.perpl.xyz" target="_blank" rel="noreferrer"><Wallet size={15}/> Wallet / Deposit / Withdraw</a></section>
  <section className="grid"><Card label="Equity" value={money(state?.portfolio?.equity)}/><Card label="Balance" value={money(state?.portfolio?.balance)}/><Card label="Positions" value={state?.portfolio?.positions?.length??0}/><Card label="Last cycle" value={status?.last_cycle?new Date(status.last_cycle*1000).toLocaleTimeString():"—"}/></section>
  <div className="columns"><section className="panel"><div className="panelTitle"><h2>Market intelligence</h2><span>{signals.length} markets</span></div><div className="table"><div className="row head"><b>Market</b><b>Price</b><b>Signal</b><b>Confidence</b><b>RSI</b></div>{signals.map(x=><div className="row" key={x.id}><b>{x.symbol}</b><span>{money(x.signal?.price)}</span><span className={`pill ${String(x.signal?.action||"").toLowerCase()}`}>{x.signal?.action||"—"}</span><span>{x.signal?.confidence?`${(x.signal.confidence*100).toFixed(1)}%`:"—"}</span><span>{x.signal?.rsi?Number(x.signal.rsi).toFixed(1):"—"}</span></div>)}</div></section>
  <section className="panel"><div className="panelTitle"><h2>Engine events</h2><span>latest</span></div><div className="events">{events.slice(0,12).map((e,i)=><div className="event" key={i}><span>{new Date(e.ts*1000).toLocaleTimeString()}</span><b>{e.level}</b><p>{e.message}</p></div>)}{!events.length&&<div className="empty">Waiting for the first engine cycle.</div>}</div></section></div>
  <footer>Live execution is locked unless <code>PERPL_LIVE_TRADING=true</code> is explicitly configured. Perpl API keys cannot withdraw or transfer funds out.</footer>
 </main>;
}
function Card({label,value}){return <div className="card"><span>{label}</span><strong>{value}</strong></div>}
function money(v){return v==null?"—":Number(v).toLocaleString("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2})}
