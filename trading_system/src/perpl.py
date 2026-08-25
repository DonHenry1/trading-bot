"""Perpl REST + authenticated WebSocket adapter."""
from __future__ import annotations

import base64, hashlib, json, os, secrets, time
from typing import Any
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

class PerplError(RuntimeError): pass

class PerplClient:
    def __init__(self) -> None:
        self.base=os.getenv("PERPL_API_URL","https://app.perpl.xyz/api").rstrip("/")
        self.ws_url=os.getenv("PERPL_WS_URL","wss://app.perpl.xyz").rstrip("/")
        self.chain_id=int(os.getenv("PERPL_CHAIN_ID","143")); self.api_key=os.getenv("PERPL_API_KEY","").strip()
        secret=os.getenv("PERPL_API_KEY_SECRET","").strip().replace("0x","")
        self._private=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret)) if len(secret)==64 else None
        self.account_id=int(os.getenv("PERPL_ACCOUNT_ID","0")); self.authenticated=bool(self.api_key and self._private and self.account_id)
        self.session=requests.Session(); self.session.headers.update({"User-Agent":"AdaptiveTradingSystem/1.0"})
        self.latest_wallet={}; self.latest_positions=[]; self.latest_orders=[]

    def _headers(self, method:str, target:str, body:bytes=b"")->dict[str,str]:
        if not self.api_key or not self._private: raise PerplError("Perpl API credentials are not configured")
        timestamp=str(int(time.time()*1000)); nonce=base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")
        canonical="\n".join([str(self.chain_id),method.upper(),target,timestamp,nonce,hashlib.sha256(body).hexdigest()]).encode()
        signature=self._private.sign(canonical)
        return {"X-API-Key":self.api_key,"X-API-Timestamp":timestamp,"X-API-Nonce":nonce,"X-API-Signature":base64.urlsafe_b64encode(signature).decode().rstrip("=")}

    def _get(self,target:str,auth=False)->dict[str,Any]:
        headers=self._headers("GET",target) if auth else {}
        for attempt in range(4):
            try:
                r=self.session.get(self.base+target,headers=headers,timeout=15)
                if r.status_code==429: time.sleep(2**attempt); continue
                if r.status_code>=400: raise PerplError(f"Perpl HTTP {r.status_code}: {r.text[:300]}")
                return r.json()
            except (requests.RequestException,ValueError) as exc:
                if attempt==3: raise PerplError(f"Perpl request failed: {exc}") from exc
                time.sleep(2**attempt)
        raise PerplError("Perpl request failed")

    def context(self)->dict[str,Any]: return self._get("/v1/pub/context")

    def candles(self,market_id:int,resolution:str|int="15m",limit:int=120)->list[dict[str,float]]:
        seconds={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400}.get(str(resolution),int(resolution))
        limit=max(2,min(int(limit),1024)); end=int(time.time()*1000); start=end-seconds*1000*limit
        data=self._get(f"/v1/market-data/{market_id}/candles/{seconds}/{start}-{end}")
        return [{"t":float(c["t"]),"o":float(c["o"]),"h":float(c["h"]),"l":float(c["l"]),"c":float(c["c"]),"v":float(c.get("v",0)),"n":float(c.get("n",0))} for c in data.get("d",[])]

    def funding(self,market_id:int,hours:int=24)->float:
        end=int(time.time()*1000); start=end-hours*3600*1000; data=self._get(f"/v1/market-data/{market_id}/funding/{start}-{end}")
        events=data.get("d",[])
        if not events:return 0.0
        e=events[-1]
        for key in ("r","rate","f"):
            if key in e:
                try:return float(e[key])
                except (TypeError,ValueError):pass
        return 0.0

    def history(self,endpoint:str,count:int=100)->list[dict[str,Any]]:
        if not self.authenticated:return []
        page=None; out=[]
        for _ in range(10):
            target=f"/v1/trading/{endpoint}?count={min(count,100)}"+(f"&page={page}" if page else "")
            data=self._get(target,auth=True); out.extend(data.get("d",[])); page=data.get("np")
            if not page:break
        return out

    def account_snapshot(self)->dict[str,Any]:
        if not self.authenticated:return {"equity":0,"balance":0,"positions":[],"orders":[]}
        balance=float(self.latest_wallet.get("b",self.latest_wallet.get("balance",0)) or 0)
        return {"equity":balance,"balance":balance,"account_id":self.account_id,"positions":self.latest_positions,"orders":self.latest_orders}

    async def place_market_order(self,market_id:int,action:str,size:float,leverage:int)->dict[str,Any]:
        if not self.authenticated: raise PerplError("authenticated Perpl credentials and PERPL_ACCOUNT_ID are required")
        import websockets
        ts=str(int(time.time()*1000)); nonce=base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")
        canonical=f"{self.chain_id}\ntrading-ws-signin\n{ts}\n{nonce}".encode(); sig=base64.urlsafe_b64encode(self._private.sign(canonical)).decode().rstrip("=")
        async with websockets.connect(self.ws_url+"/ws/v1/trading",ping_interval=20,close_timeout=5) as ws:
            await ws.send(json.dumps({"mt":29,"chain_id":self.chain_id,"api_key":self.api_key,"timestamp":ts,"nonce":nonce,"signature":sig}))
            rq=int(time.time()*1000); order_type=1 if action=="LONG" else 2
            frame={"mt":22,"sn":1,"rq":rq,"mkt":int(market_id),"acc":self.account_id,"t":order_type,"p":0,"s":max(1,int(size*100000)),"fl":4,"lv":int(leverage*100),"lb":0,"ms":50}
            await ws.send(json.dumps(frame))
            for _ in range(12):
                msg=json.loads(await ws.recv())
                if msg.get("mt")==3 and msg.get("status",{}).get("code")!=0: raise PerplError(msg["status"].get("error","order rejected"))
                if msg.get("mt") in (24,25): return msg
            return {"accepted":True,"request_id":rq}
