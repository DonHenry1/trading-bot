"""Perpl market-data and execution boundary.

Live execution stays disabled until credentials are supplied and the account is
explicitly verified by the backend. No withdrawal/private-key operation exists.
"""
from __future__ import annotations
import os, time
from typing import Any
import requests

class PerplError(RuntimeError): pass

class PerplClient:
    def __init__(self):
        self.base=os.getenv("PERPL_API_URL","https://app.perpl.xyz/api").rstrip("/")
        self.account_id=os.getenv("PERPL_ACCOUNT_ID","").strip()
        self.wallet_address=os.getenv("PERPL_WALLET_ADDRESS","").strip()
        self.api_key=os.getenv("PERPL_API_KEY","").strip()
        self.authenticated=False
        self.session=requests.Session(); self.session.headers.update({"User-Agent":"AdaptiveTradingSystem/1.2"})
        self.latest_wallet={}; self.latest_positions=[]; self.latest_orders=[]

    def _get(self,path,timeout=15):
        try:
            r=self.session.get(self.base+path,timeout=timeout)
            if r.status_code>=400: raise PerplError(f"Perpl HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
        except requests.RequestException as exc: raise PerplError(f"Perpl request failed: {exc}") from exc

    def context(self): return self._get("/v1/pub/context")

    def candles(self,market_id,resolution="15m",limit=120):
        seconds={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}.get(str(resolution),900)
        limit=max(2,min(int(limit),1024)); end=int(time.time()*1000); start=end-seconds*1000*limit
        data=self._get(f"/v1/market-data/{market_id}/candles/{seconds}/{start}-{end}")
        return data.get("d",[])

    def funding(self,market_id,hours=24):
        end=int(time.time()*1000); start=end-hours*3600*1000
        data=self._get(f"/v1/market-data/{market_id}/funding/{start}-{end}")
        events=data.get("d",[])
        if not events:return 0.0
        e=events[-1]
        for key in ("r","rate","f"):
            try:
                if key in e:return float(e[key])
            except (TypeError,ValueError):pass
        return 0.0

    def verify_connection(self):
        if not self.api_key or not self.account_id:
            self.authenticated=False; return {"ok":False,"reason":"PERPL_API_KEY and PERPL_ACCOUNT_ID are required"}
        # Do not invent authentication headers/endpoints. A real Perpl credential
        # adapter must be supplied from Perpl's current official API specification.
        self.authenticated=False
        return {"ok":False,"reason":"Perpl authenticated trading is locked until the official account/session authentication contract is configured"}

    def account_snapshot(self):
        return {"equity":0,"balance":0,"account_id":self.account_id,"wallet_address":self.wallet_address,"positions":self.latest_positions,"orders":self.latest_orders,"authenticated":self.authenticated}

    async def place_market_order(self,*args,**kwargs):
        raise PerplError("LIVE ORDER BLOCKED: authenticated Perpl session adapter has not been verified")

    def history(self,*args,**kwargs): return []
