"""
Basic correctness tests for the risk engine. Run with: pytest tests/ -v

These are not exhaustive — they check the non-negotiable behaviors from
the spec: drawdown circuit breaker, single-asset cap, kill switch veto,
and correlation-cluster scaling.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from src.config import load_config
from src.risk.risk_engine import (
    KillSwitchReason, OrderRequest, PortfolioState, RiskEngine,
)

CONFIG = load_config()


def make_engine():
    return RiskEngine(CONFIG.risk)


def make_state(equity=100_000, peak=100_000, day_start=100_000, week_start=100_000, corr=None):
    return PortfolioState(
        equity=equity, peak_equity=peak,
        daily_start_equity=day_start, weekly_start_equity=week_start,
        correlation_matrix=corr,
    )


def test_max_drawdown_trips_kill_switch():
    engine = make_engine()
    limit = CONFIG.risk.max_drawdown_pct
    state = make_state(equity=100_000 * (1 - limit - 0.01), peak=100_000)
    reason = engine.check_circuit_breakers(state)
    assert reason == KillSwitchReason.MAX_DRAWDOWN
    assert engine.trading_enabled is False


def test_within_limits_does_not_trip():
    engine = make_engine()
    state = make_state(equity=98_000, peak=100_000)  # -2%, well inside default 15% limit
    reason = engine.check_circuit_breakers(state)
    assert reason == KillSwitchReason.NONE
    assert engine.trading_enabled is True


def test_single_asset_weight_is_capped():
    engine = make_engine()
    # Absurdly large raw signal score should still clamp to config max
    weight = engine.size_position(raw_signal_score=1.0, asset_vol_annualized=0.05)
    assert abs(weight) <= CONFIG.risk.max_single_asset_weight + 1e-9


def test_kill_switch_blocks_all_orders_regardless_of_signal():
    engine = make_engine()
    engine.manual_kill_switch("test")
    state = make_state()
    request = OrderRequest(asset="BTC/USDT", target_weight=0.2, reference_price=50_000, atr=500)
    decision = engine.review_order(request, state, leverage_in_use=1.0)
    assert decision.approved is False
    assert decision.adjusted_weight == 0.0


def test_correlation_cluster_scaling():
    engine = make_engine()
    assets = ["BTC/USDT", "ETH/USDT"]
    corr = pd.DataFrame([[1.0, 0.9], [0.9, 1.0]], index=assets, columns=assets)
    proposed = {"BTC/USDT": 0.25, "ETH/USDT": 0.25}  # gross 0.50 > default 0.45 cap
    adjusted = engine.apply_correlation_limits(proposed, corr)
    gross_after = sum(abs(v) for v in adjusted.values())
    assert gross_after <= CONFIG.risk.max_correlated_cluster_weight + 1e-6


def test_stop_loss_below_entry_for_long():
    engine = make_engine()
    stop, tp = engine.compute_stop_take_profit(reference_price=100.0, atr=2.0, direction=1)
    assert stop < 100.0 < tp


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
