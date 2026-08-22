"""
Risk Engine — the non-negotiable gatekeeper between strategy signals and
the exchange.

Design principle: this module has veto power over every order. Signal
generation and portfolio construction can be wrong; the risk engine's job
is to make sure "wrong" costs a bounded, pre-agreed amount, never more.

Nothing in this file should require knowledge of *why* a signal fired —
it only cares about position sizes, correlations, volatility, and equity.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto

import numpy as np
import pandas as pd

from src.config import RiskConfig

logger = logging.getLogger("risk_engine")


class KillSwitchReason(Enum):
    NONE = auto()
    MAX_DRAWDOWN = auto()
    DAILY_LOSS_LIMIT = auto()
    WEEKLY_LOSS_LIMIT = auto()
    EXCHANGE_DISCONNECT = auto()
    EXTREME_VOLATILITY = auto()
    ANOMALOUS_API_ERRORS = auto()
    MANUAL = auto()


@dataclass
class RiskEvent:
    timestamp: datetime
    reason: KillSwitchReason
    detail: str


@dataclass
class PortfolioState:
    """Minimal state the risk engine needs on every decision cycle."""
    equity: float
    peak_equity: float
    daily_start_equity: float
    weekly_start_equity: float
    # asset -> current position weight (fraction of equity, signed)
    positions: dict[str, float] = field(default_factory=dict)
    # asset -> realized volatility (annualized)
    asset_vol: dict[str, float] = field(default_factory=dict)
    # correlation matrix of asset returns (recent window)
    correlation_matrix: pd.DataFrame | None = None

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.equity) / self.peak_equity

    @property
    def daily_pnl_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return (self.equity - self.daily_start_equity) / self.daily_start_equity

    @property
    def weekly_pnl_pct(self) -> float:
        if self.weekly_start_equity <= 0:
            return 0.0
        return (self.equity - self.weekly_start_equity) / self.weekly_start_equity


@dataclass
class OrderRequest:
    asset: str
    target_weight: float   # signed target portfolio weight, from portfolio construction
    reference_price: float
    atr: float | None = None  # for stop/take-profit distance


@dataclass
class RiskDecision:
    asset: str
    approved: bool
    adjusted_weight: float
    stop_loss_price: float | None
    take_profit_price: float | None
    rejection_reasons: list[str] = field(default_factory=list)


class RiskEngine:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.trading_enabled = True
        self.kill_switch_reason = KillSwitchReason.NONE
        self.events: list[RiskEvent] = []
        self._api_error_window: list[bool] = []  # rolling recent call outcomes

    # ------------------------------------------------------------------
    # Kill-switch / circuit breaker checks — run BEFORE any sizing logic
    # ------------------------------------------------------------------
    def check_circuit_breakers(self, state: PortfolioState) -> KillSwitchReason:
        """Evaluate portfolio-level breakers. Returns the triggered reason,
        or NONE. Also updates self.trading_enabled as a side effect."""

        if state.drawdown_pct >= self.config.max_drawdown_pct:
            return self._trip(
                KillSwitchReason.MAX_DRAWDOWN,
                f"drawdown {state.drawdown_pct:.2%} >= limit {self.config.max_drawdown_pct:.2%}",
            )

        if -state.daily_pnl_pct >= self.config.daily_loss_limit_pct:
            return self._trip(
                KillSwitchReason.DAILY_LOSS_LIMIT,
                f"daily loss {-state.daily_pnl_pct:.2%} >= limit {self.config.daily_loss_limit_pct:.2%}",
            )

        if -state.weekly_pnl_pct >= self.config.weekly_loss_limit_pct:
            return self._trip(
                KillSwitchReason.WEEKLY_LOSS_LIMIT,
                f"weekly loss {-state.weekly_pnl_pct:.2%} >= limit {self.config.weekly_loss_limit_pct:.2%}",
            )

        return KillSwitchReason.NONE

    def on_exchange_disconnect(self):
        self._trip(KillSwitchReason.EXCHANGE_DISCONNECT, "exchange connectivity lost / heartbeat timeout")

    def on_volatility_spike(self, realized_vol_zscore: float):
        threshold = self.config.kill_switch.get("extreme_vol_zscore", 4.0)
        if realized_vol_zscore >= threshold:
            self._trip(
                KillSwitchReason.EXTREME_VOLATILITY,
                f"realized vol z-score {realized_vol_zscore:.2f} >= {threshold}",
            )

    def record_api_call_outcome(self, success: bool, window: int = 50):
        self._api_error_window.append(success)
        if len(self._api_error_window) > window:
            self._api_error_window.pop(0)
        if len(self._api_error_window) >= 10:
            error_rate = 1 - (sum(self._api_error_window) / len(self._api_error_window))
            threshold = self.config.kill_switch.get("anomalous_api_error_rate", 0.2)
            if error_rate >= threshold:
                self._trip(
                    KillSwitchReason.ANOMALOUS_API_ERRORS,
                    f"API error rate {error_rate:.1%} >= {threshold:.1%}",
                )

    def manual_kill_switch(self, reason_detail: str = "manual trigger"):
        self._trip(KillSwitchReason.MANUAL, reason_detail)

    def reset_kill_switch(self, operator_note: str):
        """Re-enabling trading is a deliberate, logged, human action —
        never automatic."""
        logger.warning(f"Kill switch manually reset. Note: {operator_note}")
        self.trading_enabled = True
        self.kill_switch_reason = KillSwitchReason.NONE

    def _trip(self, reason: KillSwitchReason, detail: str) -> KillSwitchReason:
        if self.trading_enabled:
            logger.critical(f"KILL SWITCH TRIGGERED: {reason.name} — {detail}")
        self.trading_enabled = False
        self.kill_switch_reason = reason
        self.events.append(RiskEvent(datetime.now(timezone.utc), reason, detail))
        return reason

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------
    def size_position(
        self,
        raw_signal_score: float,   # continuous score, roughly in [-1, 1]
        asset_vol_annualized: float,
        win_rate: float | None = None,
        payoff_ratio: float | None = None,
    ) -> float:
        """Convert a continuous signal score into a target portfolio weight."""
        if asset_vol_annualized <= 0:
            return 0.0

        if self.config.sizing_method == "vol_target":
            # Scale so that this position's standalone contribution to
            # portfolio vol ~= vol_target * |signal_score|, capped.
            raw_weight = (self.config.vol_target_annualized / asset_vol_annualized) * raw_signal_score
        elif self.config.sizing_method == "fractional_kelly":
            if win_rate is None or payoff_ratio is None:
                logger.warning("fractional_kelly sizing requested without win_rate/payoff_ratio; falling back to 0")
                return 0.0
            # Kelly fraction f* = W - (1-W)/R, then scaled by kelly_fraction
            kelly_full = win_rate - (1 - win_rate) / max(payoff_ratio, 1e-6)
            kelly_full = max(kelly_full, 0.0)
            raw_weight = kelly_full * self.config.kelly_fraction * math.copysign(1, raw_signal_score)
        else:
            raise ValueError(f"Unknown sizing method {self.config.sizing_method}")

        return float(np.clip(raw_weight, -self.config.max_single_asset_weight, self.config.max_single_asset_weight))

    # ------------------------------------------------------------------
    # Correlation-aware exposure limits
    # ------------------------------------------------------------------
    def apply_correlation_limits(
        self, proposed_weights: dict[str, float], correlation_matrix: pd.DataFrame
    ) -> dict[str, float]:
        """Scale down clusters of correlated positions that together
        exceed max_correlated_cluster_weight."""
        assets = list(proposed_weights.keys())
        if not assets or correlation_matrix is None or correlation_matrix.empty:
            return proposed_weights

        clusters = self._cluster_by_correlation(assets, correlation_matrix)
        adjusted = dict(proposed_weights)

        for cluster in clusters:
            cluster_gross = sum(abs(adjusted[a]) for a in cluster if a in adjusted)
            if cluster_gross > self.config.max_correlated_cluster_weight and cluster_gross > 0:
                scale = self.config.max_correlated_cluster_weight / cluster_gross
                for a in cluster:
                    if a in adjusted:
                        adjusted[a] *= scale
                logger.info(
                    f"Correlation cap applied to cluster {cluster}: "
                    f"gross {cluster_gross:.2%} -> scaled by {scale:.2f}"
                )
        return adjusted

    def _cluster_by_correlation(self, assets: list[str], corr: pd.DataFrame) -> list[list[str]]:
        """Simple union-find style clustering on |correlation| > threshold."""
        parent = {a: a for a in assets}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i, a in enumerate(assets):
            for b in assets[i + 1:]:
                if a in corr.index and b in corr.columns:
                    if abs(corr.loc[a, b]) >= self.config.correlation_threshold:
                        union(a, b)

        clusters: dict[str, list[str]] = {}
        for a in assets:
            clusters.setdefault(find(a), []).append(a)
        return list(clusters.values())

    # ------------------------------------------------------------------
    # Per-trade stop-loss / take-profit
    # ------------------------------------------------------------------
    def compute_stop_take_profit(
        self, reference_price: float, atr: float, direction: int
    ) -> tuple[float, float]:
        """direction: +1 long, -1 short."""
        stop_dist = self.config.stop_loss_atr_multiple * atr
        tp_dist = self.config.take_profit_atr_multiple * atr
        stop_price = reference_price - direction * stop_dist
        tp_price = reference_price + direction * tp_dist
        return stop_price, tp_price

    # ------------------------------------------------------------------
    # Cost / slippage modeling — used identically in backtest and live
    # ------------------------------------------------------------------
    def estimate_round_trip_cost_bps(self, use_taker: bool = True) -> float:
        fee = self.config.taker_fee_bps if use_taker else self.config.maker_fee_bps
        return 2 * fee + self.config.estimated_slippage_bps  # entry + exit

    # ------------------------------------------------------------------
    # Full order review — the single entry point execution should call
    # ------------------------------------------------------------------
    def review_order(
        self,
        request: OrderRequest,
        state: PortfolioState,
        leverage_in_use: float,
    ) -> RiskDecision:
        reasons: list[str] = []

        if not self.trading_enabled:
            return RiskDecision(
                asset=request.asset,
                approved=False,
                adjusted_weight=0.0,
                stop_loss_price=None,
                take_profit_price=None,
                rejection_reasons=[f"kill switch active: {self.kill_switch_reason.name}"],
            )

        breaker = self.check_circuit_breakers(state)
        if breaker != KillSwitchReason.NONE:
            reasons.append(f"circuit breaker: {breaker.name}")

        weight = float(np.clip(
            request.target_weight,
            -self.config.max_single_asset_weight,
            self.config.max_single_asset_weight,
        ))
        if abs(weight) < abs(request.target_weight):
            reasons.append("clamped to max_single_asset_weight")

        if leverage_in_use > self.config.max_leverage:
            reasons.append(f"leverage {leverage_in_use:.2f}x exceeds max {self.config.max_leverage}x")
            weight = 0.0

        stop_price = take_price = None
        if request.atr and weight != 0:
            direction = 1 if weight > 0 else -1
            stop_price, take_price = self.compute_stop_take_profit(
                request.reference_price, request.atr, direction
            )

        approved = len(reasons) == 0 or all("clamped" in r for r in reasons)
        return RiskDecision(
            asset=request.asset,
            approved=approved,
            adjusted_weight=weight if approved else 0.0,
            stop_loss_price=stop_price,
            take_profit_price=take_price,
            rejection_reasons=reasons,
        )
