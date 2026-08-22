"""
Exchange data client.

Wraps ccxt for REST access to spot + perpetual futures markets, with a
heartbeat mechanism that feeds the RiskEngine's kill-switch on
disconnect. WebSocket streaming is stubbed (Phase 2 — ccxt.pro or a
native SDK) since REST polling is sufficient for hourly-bar strategies
but not for order-flow/microstructure signals.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd

from src.config import ExchangeConfig
from src.risk.risk_engine import RiskEngine

logger = logging.getLogger("exchange_client")


class ExchangeClient:
    def __init__(self, config: ExchangeConfig, risk_engine: RiskEngine | None = None):
        self.config = config
        self.risk_engine = risk_engine
        self._last_heartbeat = time.time()

        exchange_cls = getattr(ccxt, config.name)
        self.exchange = exchange_cls({
            "apiKey": config.api_key,
            "secret": config.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future" if "swap" in config.market_types else "spot"},
        })
        if config.testnet:
            self._set_sandbox_mode()

    def _set_sandbox_mode(self):
        try:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"{self.config.name}: sandbox/testnet mode enabled")
        except Exception as e:
            logger.warning(f"Could not enable sandbox mode for {self.config.name}: {e}")

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 500) -> pd.DataFrame:
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            self._record_success()
        except Exception as e:
            self._record_failure(e)
            raise

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        self._heartbeat()
        return df

    def fetch_ticker(self, symbol: str) -> dict:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            self._record_success()
            self._heartbeat()
            return ticker
        except Exception as e:
            self._record_failure(e)
            raise

    def fetch_funding_rate(self, symbol: str) -> float | None:
        """Only meaningful for perpetual swap symbols."""
        try:
            fr = self.exchange.fetch_funding_rate(symbol)
            self._record_success()
            return fr.get("fundingRate")
        except Exception as e:
            logger.warning(f"fetch_funding_rate failed for {symbol}: {e}")
            self._record_failure(e)
            return None

    # ------------------------------------------------------------------
    # Connectivity / heartbeat -> feeds risk engine kill switch
    # ------------------------------------------------------------------
    def _heartbeat(self):
        self._last_heartbeat = time.time()

    def check_heartbeat(self):
        elapsed = time.time() - self._last_heartbeat
        if elapsed > self.config.ws_heartbeat_timeout_s and self.risk_engine:
            self.risk_engine.on_exchange_disconnect()

    def _record_success(self):
        if self.risk_engine:
            self.risk_engine.record_api_call_outcome(True)

    def _record_failure(self, error: Exception):
        logger.error(f"Exchange API call failed: {error}")
        if self.risk_engine:
            self.risk_engine.record_api_call_outcome(False)

    # ------------------------------------------------------------------
    # Account / position state (read-only here — order placement lives in
    # execution_engine.py, which is the only module allowed to write)
    # ------------------------------------------------------------------
    def fetch_balance(self) -> dict:
        try:
            bal = self.exchange.fetch_balance()
            self._record_success()
            return bal
        except Exception as e:
            self._record_failure(e)
            raise

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict]:
        try:
            positions = self.exchange.fetch_positions(symbols) if symbols else self.exchange.fetch_positions()
            self._record_success()
            return positions
        except Exception as e:
            self._record_failure(e)
            raise
