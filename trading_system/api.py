"""Read-only HTTP API for the trading system dashboard.

This API intentionally exposes monitoring/configuration data only. It does
not place orders. Live execution remains behind the existing execution/risk
layer and must be enabled separately after paper validation.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.config import load_config

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "config.yaml"

app = FastAPI(title="Adaptive Trading System API", version="0.1.0")

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

_started_at = time.time()


def _config():
    try:
        return load_config(CONFIG_PATH)
    except Exception as exc:  # configuration errors should be visible to the UI
        raise HTTPException(status_code=503, detail=f"Configuration unavailable: {exc}") from exc


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "trading-system-api",
        "uptime_seconds": round(time.time() - _started_at, 1),
    }


@app.get("/api/config")
def config() -> dict[str, Any]:
    cfg = _config()
    return {
        "exchange": {
            "name": cfg.exchange.name,
            "testnet": cfg.exchange.testnet,
            "market_types": cfg.exchange.market_types,
        },
        "risk": {
            "max_drawdown_pct": cfg.risk.max_drawdown_pct,
            "daily_loss_limit_pct": cfg.risk.daily_loss_limit_pct,
            "weekly_loss_limit_pct": cfg.risk.weekly_loss_limit_pct,
            "max_leverage": cfg.risk.max_leverage,
        },
        "strategies": cfg.strategies,
        "universe": {
            "spot": cfg.universe.spot,
            "perp": cfg.universe.perp,
        },
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    cfg = _config()
    return {
        "mode": "PAPER" if cfg.exchange.testnet else "LIVE",
        "exchange": cfg.exchange.name,
        "testnet": cfg.exchange.testnet,
        "kill_switch": False,
        "backend": "online",
        "timestamp": time.time(),
    }


@app.get("/api/portfolio")
def portfolio() -> dict[str, Any]:
    # The Phase-1 engine has no persistent portfolio store yet. Return a
    # stable empty state instead of inventing trading data.
    return {
        "equity": None,
        "peak_equity": None,
        "drawdown": None,
        "daily_pnl_pct": None,
        "weekly_pnl_pct": None,
        "gross_exposure": None,
        "positions": [],
        "events": [],
        "timestamp": time.time(),
    }


@app.get("/api/positions")
def positions() -> dict[str, Any]:
    return {"positions": [], "timestamp": time.time()}


@app.get("/api/events")
def events() -> dict[str, Any]:
    return {"events": [], "timestamp": time.time()}


@app.get("/api/equity")
def equity() -> dict[str, Any]:
    return {"series": [], "timestamp": time.time()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
