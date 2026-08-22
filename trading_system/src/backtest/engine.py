"""
Backtest engine.

Key design decision: this engine calls the SAME RiskEngine and
PortfolioConstructor classes used in paper/live trading. A strategy that
looks good in a backtest with a different sizing/risk path than
production is not actually validated — this avoids that gap by
construction.

This is bar-based (not full order-book event-driven) for Phase 1 -
sufficient for hourly-bar strategy validation. Fees, funding, and
slippage are modeled explicitly per the cost config, applied on every
simulated fill.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.config import SystemConfig
from src.portfolio.portfolio_construction import PortfolioConstructor
from src.risk.risk_engine import PortfolioState, RiskEngine

logger = logging.getLogger("backtest_engine")


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    daily_returns: pd.Series
    max_drawdown: float
    sharpe: float
    sortino: float
    total_return: float
    kill_switch_events: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Total return: {self.total_return:.2%}\n"
            f"Max drawdown: {self.max_drawdown:.2%}\n"
            f"Sharpe (annualized): {self.sharpe:.2f}\n"
            f"Sortino (annualized): {self.sortino:.2f}\n"
            f"Kill-switch events: {len(self.kill_switch_events)}\n"
            f"Total trades: {len(self.trades)}"
        )


class BacktestEngine:
    def __init__(self, config: SystemConfig, signals: dict, bars_per_year: int = 24 * 365):
        self.config = config
        self.signals = signals  # {strategy_name: Signal instance}
        self.bars_per_year = bars_per_year
        self.risk_engine = RiskEngine(config.risk)
        self.portfolio = PortfolioConstructor(self.risk_engine, config.strategies["blend_weights"])

    def run(self, price_data: dict[str, pd.DataFrame]) -> BacktestResult:
        """
        price_data: {asset: OHLCV DataFrame}, all aligned to the same
        timestamp index (caller's responsibility to align/forward-fill).
        """
        assets = list(price_data.keys())
        timestamps = price_data[assets[0]].index

        # Precompute signal scores per strategy per asset (vectorized once,
        # not recomputed every bar — much faster, and mirrors research workflow)
        signal_scores: dict[str, dict[str, pd.Series]] = {}
        for strat_name, signal in self.signals.items():
            signal_scores[strat_name] = {
                asset: signal.compute(price_data[asset]) for asset in assets
            }

        # Precompute realized vol (annualized) and ATR per asset
        asset_vol_series = {
            asset: price_data[asset]["close"].pct_change().rolling(24).std() * np.sqrt(self.bars_per_year)
            for asset in assets
        }
        atr_series = {
            asset: _atr(price_data[asset], period=14) for asset in assets
        }

        equity = self.config.backtest.initial_capital_usdt
        peak_equity = equity
        equity_curve = []
        trades = []
        current_positions: dict[str, float] = {a: 0.0 for a in assets}  # units held
        cost_bps = self.risk_engine.estimate_round_trip_cost_bps() / 2  # per-side

        day_anchor_equity = equity
        week_anchor_equity = equity
        last_day = None
        last_week = None

        for i, ts in enumerate(timestamps):
            if i < 200:  # warmup for rolling windows
                equity_curve.append(equity)
                continue

            day = ts.date()
            week = ts.isocalendar()[1]
            if day != last_day:
                day_anchor_equity = equity
                last_day = day
            if week != last_week:
                week_anchor_equity = equity
                last_week = week

            reference_prices = {a: price_data[a]["close"].iloc[i] for a in assets}
            asset_vol = {a: asset_vol_series[a].iloc[i] for a in assets}
            atr_by_asset = {a: atr_series[a].iloc[i] for a in assets}

            blended = self.portfolio.blend_signals({
                strat: {a: signal_scores[strat][a].iloc[i] for a in assets}
                for strat in signal_scores
            })

            corr_matrix = _rolling_correlation(price_data, assets, i, window=72)
            gross_notional = sum(
                abs(current_positions[a]) * reference_prices[a] for a in assets
            )
            current_leverage = gross_notional / equity if equity > 0 else 0.0

            state = PortfolioState(
                equity=equity,
                peak_equity=peak_equity,
                daily_start_equity=day_anchor_equity,
                weekly_start_equity=week_anchor_equity,
                positions={a: (current_positions[a] * reference_prices[a]) / equity if equity > 0 else 0.0
                           for a in assets},
                asset_vol=asset_vol,
                correlation_matrix=corr_matrix,
            )

            decisions = self.portfolio.build_target_weights(
                blended, asset_vol, reference_prices, atr_by_asset, state, current_leverage
            )

            # Simulate fills toward approved target weights
            pnl_this_bar = 0.0
            for asset in assets:
                price_prev = price_data[asset]["close"].iloc[i - 1]
                price_now = reference_prices[asset]
                # mark-to-market existing position first
                pnl_this_bar += current_positions[asset] * (price_now - price_prev)

                decision = decisions.get(asset)
                if decision is None or not decision.approved:
                    continue

                target_units = (decision.adjusted_weight * equity) / price_now if price_now > 0 else 0.0
                delta_units = target_units - current_positions[asset]
                if abs(delta_units) * price_now < 1.0:  # ignore dust trades
                    continue

                trade_notional = abs(delta_units) * price_now
                cost = trade_notional * (cost_bps / 10_000)
                equity -= cost
                trades.append({
                    "timestamp": ts, "asset": asset, "delta_units": delta_units,
                    "price": price_now, "cost": cost,
                    "stop_loss": decision.stop_loss_price, "take_profit": decision.take_profit_price,
                })
                current_positions[asset] = target_units

            equity += pnl_this_bar
            peak_equity = max(peak_equity, equity)
            equity_curve.append(equity)

        equity_curve = pd.Series(equity_curve, index=timestamps)
        daily_returns = equity_curve.resample("1D").last().pct_change().dropna()

        return BacktestResult(
            equity_curve=equity_curve,
            trades=pd.DataFrame(trades),
            daily_returns=daily_returns,
            max_drawdown=_max_drawdown(equity_curve),
            sharpe=_sharpe(daily_returns),
            sortino=_sortino(daily_returns),
            total_return=(equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1,
            kill_switch_events=self.risk_engine.events,
        )


# --------------------------------------------------------------------------
# Metrics helpers
# --------------------------------------------------------------------------
def _atr(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _rolling_correlation(price_data: dict[str, pd.DataFrame], assets: list[str], i: int, window: int) -> pd.DataFrame:
    if i < window:
        return pd.DataFrame()
    rets = pd.DataFrame({
        a: price_data[a]["close"].iloc[i - window:i].pct_change() for a in assets
    })
    return rets.corr()


def _max_drawdown(equity_curve: pd.Series) -> float:
    peak = equity_curve.cummax()
    dd = (peak - equity_curve) / peak
    return float(dd.max())


def _sharpe(daily_returns: pd.Series, rf: float = 0.0, periods_per_year: int = 365) -> float:
    if daily_returns.std() == 0 or len(daily_returns) < 2:
        return 0.0
    excess = daily_returns - rf / periods_per_year
    return float(np.sqrt(periods_per_year) * excess.mean() / excess.std())


def _sortino(daily_returns: pd.Series, rf: float = 0.0, periods_per_year: int = 365) -> float:
    downside = daily_returns[daily_returns < 0]
    if downside.std() == 0 or len(downside) < 2:
        return 0.0
    excess = daily_returns - rf / periods_per_year
    return float(np.sqrt(periods_per_year) * excess.mean() / downside.std())
