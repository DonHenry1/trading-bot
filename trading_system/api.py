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
app=FastAPI(title="Adaptive Perpl Trading System",version="1.2.0")
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
def status():return {**engine.status(),"exchange":"Perpl","backend":"online","authenticated":client.authenticated,"credentials_present":bool(client.api_key and client.account_id),"timestamp":time.time()}
@app.get("/api/readiness")
def readiness():
    market_ok=False; market_reason="not checked"
    try: market_ok=bool(client.context().get("markets")); market_reason="market data available" if market_ok else "no markets returned"
    except Exception as exc: market_reason=str(exc)
    gates={"wallet_public_address":bool(client.wallet_address),"perpl_credentials_configured":bool(client.api_key and client.account_id),"perpl_authentication":False,"market_data":market_ok,"account_balance":False,"paper_execution":True,"risk_controls":not engine.risk.kill_switch,"live_execution":False}
    return {"ready_for_live":False,"gates":gates,"market_reason":market_reason,"live_trading_env":False,"message":"Live execution is hard-locked until an official, verified Perpl authenticated-session adapter is configured and independently tested."}
@app.get("/api/config")
def config():
    c=cfg();return {"exchange":{"name":"Perpl","testnet":False,"market_types":["perpetual"]},"risk":{"max_drawdown_pct":c.risk.max_drawdown_pct,"daily_loss_limit_pct":c.risk.daily_loss_limit_pct,"weekly_loss_limit_pct":c.risk.weekly_loss_limit_pct,"max_leverage":c.risk.max_leverage},"strategies":c.strategies}
@app.get("/api/market")
async def market():
    try:return await asyncio.to_thread(client.context)
    except Exception as exc:raise HTTPException(502,detail=str(exc)) from exc
@app.get("/api/portfolio")
def portfolio():
    a=client.account_snapshot();return {"equity":a.get("equity"),"balance":a.get("balance"),"account_id":a.get("account_id"),"wallet_address":a.get("wallet_address"),"positions":a.get("positions",[]),"orders":a.get("orders",[]),"events":list(engine.events),"timestamp":time.time()}
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
    if engine.cfg.live:raise HTTPException(503,detail="Live trading is disabled until the verified Perpl authentication adapter is installed and tested")
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
def wallet():return JSONResponse({"mode":"wallet-controlled","wallet_address":client.wallet_address or None,"deposit":{"available":True,"method":"Use the official Perpl wallet interface"},"withdrawal":{"available":True,"method":"Use the official Perpl wallet interface","bot_initiated":False},"private_keys_required_by_bot":False,"message":"The bot never initiates withdrawals or stores your seed phrase/private wallet key."})
if __name__=="__main__":
    import uvicorn;uvicorn.run("api:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")))
