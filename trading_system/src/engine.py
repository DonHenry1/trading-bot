"""Adaptive strategy, portfolio state and hard risk controls."""
from __future__ import annotations
import asyncio, math, os, statistics, time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any
from .perpl import PerplClient

@dataclass
class BotConfig:
    live: bool=os.getenv("PERPL_LIVE_TRADING","false").lower()=="true"
    poll_seconds: float=float(os.getenv("BOT_POLL_SECONDS","20"))
    risk_per_trade: float=float(os.getenv("RISK_PER_TRADE_PCT","0.005"))
    max_drawdown: float=float(os.getenv("MAX_DRAWDOWN_PCT","0.10"))
    max_daily_loss: float=float(os.getenv("MAX_DAILY_LOSS_PCT","0.03"))
    max_leverage: int=int(os.getenv("MAX_LEVERAGE","5"))
    min_confidence: float=float(os.getenv("MIN_SIGNAL_CONFIDENCE","0.68"))
    max_spread_bps: float=float(os.getenv("MAX_SPREAD_BPS","12"))

class RiskGate:
    def __init__(self,cfg:BotConfig): self.cfg=cfg; self.peak_equity=None; self.day_start_equity=None; self.day=time.strftime("%Y-%m-%d"); self.kill_switch=False
    def check(self,equity,confidence,spread_bps,leverage):
        today=time.strftime("%Y-%m-%d")
        if today!=self.day:self.day=today;self.day_start_equity=equity;self.kill_switch=False
        if self.peak_equity is None:self.peak_equity=equity
        if self.day_start_equity is None:self.day_start_equity=equity
        self.peak_equity=max(self.peak_equity,equity);dd=(self.peak_equity-equity)/max(self.peak_equity,1e-9);daily=(self.day_start_equity-equity)/max(self.day_start_equity,1e-9)
        if dd>=self.cfg.max_drawdown:self.kill_switch=True;return False,"max drawdown circuit breaker"
        if daily>=self.cfg.max_daily_loss:self.kill_switch=True;return False,"daily loss circuit breaker"
        if self.kill_switch:return False,"kill switch active"
        if confidence<self.cfg.min_confidence:return False,"confidence below threshold"
        if spread_bps>self.cfg.max_spread_bps:return False,"spread too wide"
        if leverage>self.cfg.max_leverage:return False,"leverage exceeds limit"
        return True,"approved"

class AdaptiveStrategy:
    def score(self,candles,market):
        closes=[float(x["c"]) for x in candles]
        if len(closes)<50:return {"action":"HOLD","confidence":0.0,"reason":"warming up"}
        def ema(vals,n):
            k=2/(n+1);out=vals[0]
            for v in vals:out=v*k+out*(1-k)
            return out
        e20,e50=ema(closes,20),ema(closes,50);diffs=[b-a for a,b in zip(closes[-15:-1],closes[-14:])];g=[max(d,0) for d in diffs];l=[max(-d,0) for d in diffs];rs=statistics.fmean(g)/max(statistics.fmean(l),1e-12);rsi=100-100/(1+rs)
        returns=[math.log(b/a) for a,b in zip(closes[-31:-1],closes[-30:]) if a>0 and b>0];vol=statistics.pstdev(returns)*math.sqrt(365*24*4) if len(returns)>2 else 0.0
        bid,ask=float(market.get("bid") or 0),float(market.get("ask") or 0);price=float(market.get("mid") or market.get("mark") or closes[-1]);spread=((ask-bid)/price*10000) if bid>0 and ask>0 and price>0 else 999.0
        trend=1 if e20>e50 else -1;momentum=1 if rsi>55 else -1 if rsi<45 else 0;funding=float(market.get("funding_rate") or 0);fb=-1 if funding>0.0005 else 1 if funding<-0.0005 else 0;score=.55*trend+.30*momentum+.15*fb;confidence=min(.99,.50+abs(score)*.48);action="LONG" if score>.42 else "SHORT" if score<-.42 else "HOLD"
        return {"action":action,"confidence":confidence,"score":score,"rsi":rsi,"ema20":e20,"ema50":e50,"volatility":vol,"spread_bps":spread,"funding_rate":funding,"price":price}

class TradingEngine:
    def __init__(self,client:PerplClient,cfg=None):
        self.client=client;self.cfg=cfg or BotConfig();self.risk=RiskGate(self.cfg);self.strategy=AdaptiveStrategy();self.running=False;self.started_at=None;self.last_cycle=0;self.last_error=None;self.latest={};self._task=None;self.events=deque(maxlen=300);self.equity_series=deque(maxlen=500)
    def log(self,level,message,**data):self.events.appendleft({"ts":time.time(),"level":level,"message":message,**data})
    async def start(self):
        if self.running:return
        self.running=True;self.started_at=time.time();self.log("INFO","bot started",mode="LIVE" if self.cfg.live else "PAPER");self._task=asyncio.create_task(self._loop())
    async def stop(self):
        self.running=False
        if self._task:
            self._task.cancel()
            try:await self._task
            except asyncio.CancelledError:pass
        self.log("INFO","bot stopped")
    async def _loop(self):
        while self.running:
            try:await self.cycle();self.last_error=None
            except Exception as exc:self.last_error=str(exc);self.log("ERROR","cycle failed",error=str(exc))
            await asyncio.sleep(self.cfg.poll_seconds)
    async def cycle(self):
        ctx=await asyncio.to_thread(self.client.context);selected=[m for m in ctx.get("markets",[]) if str(m.get("symbol","")).upper() in {"BTC","ETH","SOL","MON"}];snapshots=[]
        for m in selected[:4]:
            try:
                state=m.get("state") or {};candles=await asyncio.to_thread(self.client.candles,int(m["id"]),"15m",120);funding=await asyncio.to_thread(self.client.funding,int(m["id"]),24);signal=self.strategy.score(candles,{"bid":state.get("bid"),"ask":state.get("ask"),"mid":state.get("mid"),"mark":state.get("mrk"),"funding_rate":funding});snapshots.append({"id":m["id"],"symbol":m.get("symbol"),"signal":signal,"state":state})
            except Exception as exc:self.log("WARN","market analysis failed",market=m.get("symbol"),error=str(exc))
        account=self.client.account_snapshot();equity=float(account.get("equity") or 0)
        if equity>0:self.equity_series.append({"ts":time.time(),"equity":equity})
        for item in snapshots:
            s=item["signal"]
            if s.get("action")=="HOLD" or equity<=0:continue
            ok,reason=self.risk.check(equity,float(s["confidence"]),float(s.get("spread_bps",999)),self.cfg.max_leverage);self.log("INFO" if ok else "RISK",f"{item['symbol']} {s['action']}",confidence=s["confidence"],decision=reason)
            if ok and self.cfg.live:
                size=self._size(equity,s);await self.client.place_market_order(int(item["id"]),s["action"],size,self.cfg.max_leverage);self.log("TRADE","live order submitted",symbol=item["symbol"],side=s["action"],size=size)
        self.latest={"markets":snapshots,"account":account,"context":ctx,"ts":time.time()};self.last_cycle=time.time()
    def _size(self,equity,signal):
        price=max(float(signal.get("price") or 0),1e-9);risk_usd=equity*self.cfg.risk_per_trade;stop=min(max(float(signal.get("volatility") or .02)*.25,.006),.05);return max(.000001,risk_usd/(price*stop))
    def status(self):return {"running":self.running,"mode":"LIVE" if self.cfg.live else "PAPER","last_cycle":self.last_cycle,"last_error":self.last_error,"kill_switch":self.risk.kill_switch,"started_at":self.started_at,"config":asdict(self.cfg)}
