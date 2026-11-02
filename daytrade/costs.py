"""Taiwan cash-equity day-trade costs (現股當沖).

Fees and tax come from the app-wide broker model in twcosts.py (元大證券 電子下單):
- Commission 0.1425% x discount (default 0.6) each side, floored to NT$, minimum NT$20 per
  board-lot order and NT$1 per odd-lot order.
- Day-trade sell tax 0.15% (reduced rate, extended to 2027-12-31).
- Slippage is modelled in ticks using the TWSE tick-size table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:
    from twcosts import BrokerFees, DEFAULT_DISCOUNT
except ImportError:  # running from inside daytrade/
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from twcosts import BrokerFees, DEFAULT_DISCOUNT

_B = BrokerFees()


def tick_size(price: float) -> float:
    """TWSE / TPEx stock tick size for a given price."""
    if price < 10:
        return 0.01
    if price < 50:
        return 0.05
    if price < 100:
        return 0.1
    if price < 500:
        return 0.5
    if price < 1000:
        return 1.0
    return 5.0


def round_to_tick(price: float, direction: str = "nearest") -> float:
    t = tick_size(price)
    q = price / t
    if direction == "down":
        n = math.floor(q + 1e-9)
    elif direction == "up":
        n = math.ceil(q - 1e-9)
    else:
        n = round(q)
    return round(n * t, 2)


@dataclass(frozen=True)
class DayTradeCosts:
    fee_rate: float = _B.fee_rate
    fee_discount: float = DEFAULT_DISCOUNT   # 元大電子下單 6 折; 1.0 = no discount
    min_fee: float = _B.min_fee              # per board-lot order
    tax_rate: float = _B.tax_daytrade        # day-trade sell tax
    slip_ticks: int = 1                      # ticks lost on each market fill (entry, stop, close-out)
    min_fee_odd: float = _B.min_fee_odd      # per odd-lot order
    broker: str = _B.name

    @property
    def fees(self) -> BrokerFees:
        return BrokerFees(fee_rate=self.fee_rate, fee_discount=self.fee_discount, min_fee=self.min_fee,
                          min_fee_odd=self.min_fee_odd, tax_daytrade=self.tax_rate)

    def fee(self, notional: float, odd_lot: bool = False) -> float:
        return self.fees.fee_notional(notional, odd_lot)

    def net_pnl(self, buy_price: float, sell_price: float, shares: int) -> float:
        """Net NT$ P&L of a buy-then-sell round trip, after fees and tax (floored to NT$)."""
        f = self.fees
        sell = sell_price * shares
        return (sell - buy_price * shares - f.fee(buy_price, shares) - f.fee(sell_price, shares)
                - math.floor(sell * self.tax_rate))

    def slip(self, price: float, side: str) -> float:
        """Price after losing `slip_ticks` ticks: side='buy' pays up, 'sell' gets less."""
        p = price
        for _ in range(self.slip_ticks):
            t = tick_size(p if side == "buy" else max(p - 1e-9, 0.01))
            p = p + t if side == "buy" else p - t
        return round(p, 2)
