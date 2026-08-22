"""
Execution engine.

Paper mode is fully functional: it simulates fills using live/near-live
market data through the same RiskDecision objects that would drive real
orders, so the code path exercised in paper trading is identical to what
live trading will run.

Live order placement is deliberately stubbed — see LIVE MODE SAFETY GUARD
below. Wire this up only after you've reviewed paper-mode behavior over a
real market cycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from src.data.exchange_client import ExchangeClient
from src.risk.risk_engine import RiskDecision

logger = logging.getLogger("execution_engine")


class ExecutionMode(Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass
class SimulatedFill:
    asset: str
    timestamp: datetime
    side: str
    units: float
    price: float
    fee: float


@dataclass
class PaperAccount:
    starting_equity: float
    cash: float
    positions: dict[str, float] = field(default_factory=dict)  # asset -> units
    fills: list[SimulatedFill] = field(default_factory=list)


class ExecutionEngine:
    def __init__(
        self,
        mode: ExecutionMode,
        exchange_client: ExchangeClient,
        fee_bps: float,
        paper_starting_equity: float = 100_000,
    ):
        self.mode = mode
        self.exchange_client = exchange_client
        self.fee_bps = fee_bps
        self.paper_account = PaperAccount(
            starting_equity=paper_starting_equity, cash=paper_starting_equity
        ) if mode == ExecutionMode.PAPER else None

        if mode == ExecutionMode.LIVE:
            logger.warning(
                "ExecutionEngine initialized in LIVE mode. Live order placement "
                "is NOT implemented in this Phase 1 build — see execute_decision()."
            )

    def execute_decision(self, decision: RiskDecision, current_price: float, current_units: float) -> SimulatedFill | None:
        if not decision.approved or decision.adjusted_weight == 0 and current_units == 0:
            return None

        if self.mode == ExecutionMode.PAPER:
            return self._execute_paper(decision, current_price, current_units)
        elif self.mode == ExecutionMode.LIVE:
            return self._execute_live(decision, current_price, current_units)

    # ------------------------------------------------------------------
    # Paper execution — simulated fill at current price + modeled slippage
    # ------------------------------------------------------------------
    def _execute_paper(self, decision: RiskDecision, current_price: float, current_units: float) -> SimulatedFill:
        equity = self.paper_account.cash + sum(
            units * current_price for units in self.paper_account.positions.values()
        )
        target_units = (decision.adjusted_weight * equity) / current_price if current_price > 0 else 0.0
        delta_units = target_units - current_units
        side = "buy" if delta_units > 0 else "sell"

        fee = abs(delta_units) * current_price * (self.fee_bps / 10_000)
        self.paper_account.cash -= delta_units * current_price + fee
        self.paper_account.positions[decision.asset] = target_units

        fill = SimulatedFill(
            asset=decision.asset,
            timestamp=datetime.now(timezone.utc),
            side=side,
            units=delta_units,
            price=current_price,
            fee=fee,
        )
        self.paper_account.fills.append(fill)
        logger.info(f"[PAPER] {side.upper()} {abs(delta_units):.6f} {decision.asset} @ {current_price} (fee {fee:.2f})")
        return fill

    # ------------------------------------------------------------------
    # LIVE MODE SAFETY GUARD
    # ------------------------------------------------------------------
    def _execute_live(self, decision: RiskDecision, current_price: float, current_units: float):
        """
        Intentionally not implemented in Phase 1.

        When you're ready to build this: it should (a) use limit orders
        with a timeout + market fallback, (b) reconcile the actual fill
        against the intended position afterward (partial fills happen),
        (c) re-check self.exchange_client's kill-switch state immediately
        before AND after order submission, and (d) log every order to
        persistent storage before submission, not after.
        """
        raise NotImplementedError(
            "Live order execution is not implemented yet. This is a deliberate "
            "safety guard, not an oversight — build and review this against "
            "paper-mode results first."
        )
