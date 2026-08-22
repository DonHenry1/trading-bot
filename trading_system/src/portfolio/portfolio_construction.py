"""
Portfolio construction: blends per-strategy signal scores into per-asset
target weights, then hands every proposed position to the RiskEngine for
review. This module NEVER sends anything directly to execution — the
risk engine's decision is final.
"""
from __future__ import annotations

import logging

import pandas as pd

from src.risk.risk_engine import OrderRequest, PortfolioState, RiskDecision, RiskEngine

logger = logging.getLogger("portfolio_construction")


class PortfolioConstructor:
    def __init__(self, risk_engine: RiskEngine, blend_weights: dict[str, float]):
        self.risk_engine = risk_engine
        self.blend_weights = blend_weights

    def blend_signals(self, signal_scores: dict[str, dict[str, float]]) -> dict[str, float]:
        """
        signal_scores: {strategy_name: {asset: score}}
        Returns: {asset: blended_score} weighted by config blend_weights.
        """
        assets = set()
        for scores in signal_scores.values():
            assets.update(scores.keys())

        blended: dict[str, float] = {}
        for asset in assets:
            total_weight = 0.0
            weighted_sum = 0.0
            for strategy, scores in signal_scores.items():
                if asset not in scores:
                    continue
                w = self.blend_weights.get(strategy, 0.0)
                weighted_sum += w * scores[asset]
                total_weight += w
            blended[asset] = weighted_sum / total_weight if total_weight > 0 else 0.0
        return blended

    def build_target_weights(
        self,
        blended_scores: dict[str, float],
        asset_vol: dict[str, float],
        reference_prices: dict[str, float],
        atr_by_asset: dict[str, float],
        state: PortfolioState,
        current_leverage: float,
    ) -> dict[str, RiskDecision]:
        """Runs every candidate position through the risk engine and
        returns the final, approved decisions keyed by asset."""

        raw_weights = {
            asset: self.risk_engine.size_position(score, asset_vol.get(asset, float("nan")))
            for asset, score in blended_scores.items()
            if asset in asset_vol and asset_vol[asset] > 0
        }

        capped_weights = self.risk_engine.apply_correlation_limits(
            raw_weights, state.correlation_matrix
        )

        decisions: dict[str, RiskDecision] = {}
        for asset, weight in capped_weights.items():
            request = OrderRequest(
                asset=asset,
                target_weight=weight,
                reference_price=reference_prices.get(asset, 0.0),
                atr=atr_by_asset.get(asset),
            )
            decision = self.risk_engine.review_order(request, state, current_leverage)
            decisions[asset] = decision
            if not decision.approved:
                logger.info(f"Order for {asset} rejected: {decision.rejection_reasons}")

        return decisions
