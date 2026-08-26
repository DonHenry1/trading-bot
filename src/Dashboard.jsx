import React,{useCallback,useEffect,useState} from "react";
import {Activity,Play,Square,ShieldAlert,RefreshCw,Wallet,Link2,Unlink} from "lucide-react";
import {api} from "./api";

function short(a){return a?`${a.slice(0,6)}…${a.slice(-4)}`:""}
export default function Dashboard(){
 const [state,setState]=useState(null),[signals,setSignals]=useState([]),[events,setEvents]=useState([]),[error,setError]=useState(""),[busy,setBusy]=useState(false),[account,setAccount]=useState("");
 const refresh=useCallback(async()=>{try{const [status,portfolio,s,e]=await Promise.all([api.status(),api.portfolio(),api.signals(),api.events()]);setState({status,portfolio});setSignals(s.markets||[]);setEvents(e.events||[]);setError("")}catch(err){setError(err.message)}},[]);
 useEffect(()=>{refresh();const t=setInterval(refresh,5000);return()=>clearInterval(t)},[refresh]);
 useEffect(()=>{try{const saved=localStorage.getItem("perpl_wallet");if(saved)setAccount(saved)}catch{}}
 ,[]);
 const connect=async()=>{setError("");if(!window.ethereum){setError("MetaMask was not detected. Install MetaMask and open this dashboard in the same browser.");return}try{const accounts=await window.ethereum.request({method:"eth_requestAccounts"});if(!accounts?.[0])throw Error("No wallet account was returned");setAccount(accounts[0]);localStorage.setItem("perpl_wallet",accounts[0]);}catch(e){setError(e?.message||"Wallet connection was rejected")}};
 const disconnect=()=>{setAccount("");localStorage.removeItem("perpl_wallet")};
 useEffect(()=>{if(!window.ethereum)return;const changed=(a)=>{const next=a?.[0]||"";setAccount(next);if(next)localStorage.setItem("perpl_wallet",next);else localStorage.removeItem("perpl_wallet")};window.ethereum.on?.("accountsChanged",changed);return()=>window.ethereum.removeListener?.("accountsChanged",changed)},[]);
 const action=async fn=>{setBusy(true);try{await fn();await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}};
 const status=state?.status;
 return <main className="dashboard">
  <header><div><div className="eyebrow"><Activity size={14}/> ADAPTIVE PERPL ENGINE</div><h1>Trading Command Center</h1><p>Real market data · risk-gated execution · paper-first by default</p></div><div className="headerActions"><button className="ghost" onClick={refresh}><RefreshCw size={15}/> Refresh</button>{account?<button className="wallet connected" onClick={disconnect}><Wallet size={15}/> {short(account)} <Unlink size={14}/></button>:<button className="wallet" onClick={connect}><Wallet size={15}/> Connect MetaMask</button>}</div></header>
  {error&&<div className="error">{error}</div>}
  <section className="hero"><div><span>BOT STATUS</span><strong>{status?.running?"RUNNING":"STOPPED"}</strong></div><div><span>MODE</span><strong>{status?.mode||"—"}</strong></div><div><span>EXCHANGE</span><strong>PERPL</strong></div><div><span>WALLET</span><strong>{account?short(account):"NOT CONNECTED"}</strong></div></section>
  <section className="actions"><button disabled={busy} onClick={()=>action(api.start)}><Play size={15}/> Start bot</button><button disabled={busy} className="ghost" onClick={()=>action(api.stop)}><Square size={15}/> Stop</button><button disabled={busy} className="danger" onClick={()=>action(api.kill)}><ShieldAlert size={15}/> Emergency stop</button><a className="ghost link" href="https://app.perpl.xyz" target="_blank" rel="noreferrer"><Link2 size={15}/> Open Perpl</a></section>
  <section className="walletPanel"><div><b>Wallet connection</b><span>{account?`MetaMask: ${account}`:"Connect the wallet that you already use with Perpl."}</span></div><div className="walletActions">{account?<button className="ghost" onClick={disconnect}>Disconnect</button>:<button className="wallet" onClick={connect}>Connect MetaMask</button>}<a className="wallet" href="https://app.perpl.xyz" target="_blank" rel="noreferrer"><Wallet size={15}/> Deposit / Withdraw on Perpl</a></div></section>
  <section className="grid"><Card label="Equity" value={money(state?.portfolio?.equity)}/><Card label="Balance" value={money(state?.portfolio?.balance)}/><Card label="Positions" value={state?.portfolio?.positions?.length??0}/><Card label="Last cycle" value={status?.last_cycle?new Date(status.last_cycle*1000).toLocaleTimeString():"—"}/></section>
  <div className="columns"><section className="panel"><div className="panelTitle"><h2>Market intelligence</h2><span>{signals.length} markets</span></div><div className="table"><div className="row head"><b>Market</b><b>Price</b><b>Signal</b><b>Confidence</b><b>RSI</b></div>{signals.map(x=><div className="row" key={x.id}><b>{x.symbol}</b><span>{money(x.signal?.price)}</span><span className={`pill ${String(x.signal?.action||"").toLowerCase()}`}>{x.signal?.action||"—"}</span><span>{x.signal?.confidence?`${(x.signal.confidence*100).toFixed(1)}%`:"—"}</span><span>{x.signal?.rsi?Number(x.signal.rsi).toFixed(1):"—"}</span></div>)}</div></section>
  <section className="panel"><div className="panelTitle"><h2>Engine events</h2><span>latest</span></div><div className="events">{events.slice(0,12).map((e,i)=><div className="event" key={i}><span>{new Date(e.ts*1000).toLocaleTimeString()}</span><b>{e.level}</b><p>{e.message}</p></div>)}{!events.length&&<div className="empty">Waiting for the first engine cycle.</div>}</div></section></div>
  <footer>Wallet connection uses MetaMask in your browser. It does not expose your seed phrase or private key to this application. Live execution remains locked unless Perpl account authentication and <code>PERPL_LIVE_TRADING=true</code> are explicitly configured.</footer>
 </main>;
}
function Card({label,value}){return <div className="card"><span>{label}</span><strong>{value}</strong></div>}
function money(v){return v==null?"—":Number(v).toLocaleString("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2})}
