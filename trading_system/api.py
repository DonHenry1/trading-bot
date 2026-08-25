"""Monitoring/control API for the adaptive Perpl trading system."""
from __future__ import annotations
import asyncio, os, time
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.config import load_config
from src.perpl import PerplClient
from src.engine import TradingEngine
ROOT=Path(__file__).resolve().parent; CONFIG_PATH=ROOT/"config"/"config.yaml"
app=FastAPI(title="Adaptive Perpl Trading System",version="1.1.1")
origins=[o.strip() for o in os.getenv("CORS_ORIGINS","*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=False,allow_methods=["GET","POST","OPTIONS"],allow_headers=["*"])
client=PerplClient(); engine=TradingEngine(client); started=time.time()
def cfg():
    try:return load_config(CONFIG_PATH)
    except Exception as exc:raise HTTPException(503,detail=f"Configuration unavailable: {exc}") from exc
@app.get("/")
def root():return {"service":"trading-system-api","status":"ok","docs":"/docs","health":"/health"}
@app.get("/health")
def health():return {"status":"ok","service":"trading-system-api","uptime_seconds":round(time.time()-started,1),"bot":engine.status()}
@app.get("/api/status")
def status():return {**engine.status(),"exchange":"Perpl","backend":"online","authenticated":client.authenticated,"credentials_present":bool(client.api_key and client._private),"timestamp":time.time()}
@app.get("/api/readiness")
def readiness():
    market_ok=False; market_reason="not checked"
    try: market_ok=bool(client.context().get("markets")); market_reason="market data available" if market_ok else "no markets returned"
    except Exception as exc: market_reason=str(exc)
    credentials=bool(client.api_key and client._private and client.account_id)
    # The current adapter only marks credentials as configured; it does not claim an authenticated account until a verified authenticated response is observed.
    account_verified=bool(client.authenticated)
    balance_ok=False
    if account_verified:
        try: balance_ok=float(client.account_snapshot().get("balance") or 0)>0
        except Exception: balance_ok=False
    wallet_address=getattr(client,"wallet_address",os.getenv("PERPL_WALLET_ADDRESS",""))
    gates={"wallet_public_address":bool(wallet_address),"perpl_credentials_configured":credentials,"perpl_authentication":account_verified,"market_data":market_ok,"account_balance":balance_ok,"paper_execution":True,"risk_controls":not engine.risk.kill_switch,"live_execution":False}
    return {"ready_for_live":all(gates.values()) and os.getenv("PERPL_LIVE_TRADING","false").lower()=="true","gates":gates,"market_reason":market_reason,"live_trading_env":os.getenv("PERPL_LIVE_TRADING","false").lower()=="true","message":"Live execution stays locked until every gate is independently verified."}
@app.get("/api/config")
def config():
    c=cfg();return {"exchange":{"name":"Perpl","testnet":False,"market_types":["perpetual"]},"risk":{"max_drawdown_pct":c.risk.max_drawdown_pct,"daily_loss_limit_pct":c.risk.daily_loss_limit_pct,"weekly_loss_limit_pct":c.risk.weekly_loss_limit_pct,"max_leverage":c.risk.max_leverage},"strategies":c.strategies}
@app.get("/api/market")
async def market():
    try:return await asyncio.to_thread(client.context)
    except Exception as exc:raise HTTPException(502,detail=str(exc)) from exc
@app.get("/api/portfolio")
def portfolio():
    a=client.account_snapshot();return {"equity":a.get("equity"),"balance":a.get("balance"),"account_id":a.get("account_id"),"wallet_address":a.get("wallet_address",getattr(client,"wallet_address",None)),"positions":a.get("positions",[]),"orders":a.get("orders",[]),"events":list(engine.events),"timestamp":time.time()}
@app.get("/api/positions")
def positions():return {"positions":client.account_snapshot().get("positions",[]),"timestamp":time.time()}
@app.get("/api/events")
def events():return {"events":list(engine.events),"timestamp":time.time()}
@app.get("/api/equity")
def equity():return {"series":list(engine.equity_series),"timestamp":time.time()}
@app.get("/api/signals")
def signals():return {"markets":engine.latest.get("markets",[]),"timestamp":time.time()}
@app.post("/api/bot/start")
async def start_bot():
    if engine.cfg.live:
        r=readiness()
        if not r["ready_for_live"]: raise HTTPException(409,detail={"message":"Live trading readiness gates have not passed","readiness":r})
    await engine.start();return engine.status()
@app.post("/api/bot/stop")
async def stop_bot():await engine.stop();return engine.status()
@app.post("/api/bot/kill")
async def kill_bot():engine.risk.kill_switch=True;await engine.stop();engine.log("CRITICAL","manual kill switch activated");return engine.status()
@app.get("/api/account-history")
def account_history():return {"events":client.history("account-history"),"timestamp":time.time()}
@app.get("/api/fills")
def fills():return {"fills":client.history("fills"),"timestamp":time.time()}
@app.get("/api/orders")
def orders():return {"orders":client.history("order-history"),"timestamp":time.time()}
@app.get("/api/wallet")
def wallet():return JSONResponse({"mode":"wallet-controlled","wallet_address":getattr(client,"wallet_address",os.getenv("PERPL_WALLET_ADDRESS","")) or None,"deposit":{"available":True,"method":"Use the Perpl wallet interface"},"withdrawal":{"available":True,"method":"Use the Perpl wallet interface","bot_initiated":False},"private_keys_required_by_bot":False,"message":"The bot never initiates withdrawals or stores your seed phrase/private wallet key. Deposits and withdrawals remain wallet-controlled."})
if __name__=="__main__":
    import uvicorn;uvicorn.run("api:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")))
