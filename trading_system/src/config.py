"""
Typed configuration loader.

All modules import config THROUGH this loader — never parse config.yaml
directly elsewhere. This keeps risk parameters in one validated place and
makes it obvious in code review when a risk number is being read.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


@dataclass(frozen=True)
class ExchangeConfig:
    name: str
    market_types: list[str]
    testnet: bool
    api_key_env: str
    api_secret_env: str
    rate_limit_ms: int
    ws_heartbeat_timeout_s: int

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)

    @property
    def api_secret(self) -> str | None:
        return os.environ.get(self.api_secret_env)


@dataclass(frozen=True)
class RiskConfig:
    max_drawdown_pct: float
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    sizing_method: str
    vol_target_annualized: float
    kelly_fraction: float
    max_leverage: float
    max_single_asset_weight: float
    max_correlated_cluster_weight: float
    correlation_threshold: float
    stop_loss_atr_multiple: float
    take_profit_atr_multiple: float
    max_slippage_bps: float
    taker_fee_bps: float
    maker_fee_bps: float
    estimated_slippage_bps: float
    perp_funding_lookback_periods: int
    kill_switch: dict[str, Any]

    def __post_init__(self):
        # Hard sanity checks — refuse to load an unsafe config rather than
        # silently trading with a typo'd risk number.
        assert 0 < self.max_drawdown_pct <= 0.5, "max_drawdown_pct out of sane range"
        assert 0 < self.kelly_fraction <= 0.5, "kelly_fraction must stay fractional (<=0.5)"
        assert 0 < self.max_leverage <= 5.0, "max_leverage exceeds hard ceiling of 5x"
        assert 0 < self.max_single_asset_weight <= 1.0
        assert self.sizing_method in ("vol_target", "fractional_kelly")


@dataclass(frozen=True)
class UniverseConfig:
    spot: list[str]
    perp: list[str]
    min_avg_daily_volume_usdt: float


@dataclass(frozen=True)
class BacktestConfig:
    start_date: str
    end_date: str
    initial_capital_usdt: float
    bar_interval: str
    walk_forward: dict[str, int]


@dataclass(frozen=True)
class MonitoringConfig:
    telegram_bot_token_env: str
    telegram_chat_id_env: str
    daily_report_time_utc: str
    alert_on: dict[str, bool]


@dataclass(frozen=True)
class SystemConfig:
    exchange: ExchangeConfig
    universe: UniverseConfig
    risk: RiskConfig
    strategies: dict[str, Any]
    backtest: BacktestConfig
    monitoring: MonitoringConfig
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SystemConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found at {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    return SystemConfig(
        exchange=ExchangeConfig(**raw["exchange"]),
        universe=UniverseConfig(**raw["universe"]),
        risk=RiskConfig(**raw["risk"]),
        strategies=raw["strategies"],
        backtest=BacktestConfig(**raw["backtest"]),
        monitoring=MonitoringConfig(**raw["monitoring"]),
        raw=raw,
    )


if __name__ == "__main__":
    cfg = load_config()
    print(f"Loaded config for exchange={cfg.exchange.name} testnet={cfg.exchange.testnet}")
    print(f"Max drawdown circuit breaker: {cfg.risk.max_drawdown_pct:.0%}")
    print(f"Max leverage: {cfg.risk.max_leverage}x, Kelly fraction: {cfg.risk.kelly_fraction}")
