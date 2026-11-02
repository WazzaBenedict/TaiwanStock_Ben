"""Taiwan cash-equity day-trade costs (現股當沖).

Kept separate from quant/costs.py on the claude/backtest-engine branch until that
lands; switch to importing TaiwanCosts from there once it is merged.

Figures (as of 2026-11, check with your broker):
- Commission 0.1425% of notional each side, times the broker discount, minimum NT$20 per order.
- Securities transaction tax on the sell side: 0.15% for same-day round trips
  (half the normal 0.3%; the reduced rate is a temporary measure, verify it still applies).
- Slippage is modelled in ticks using the TWSE tick-size table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


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
    fee_rate: float = 0.001425
    fee_discount: float = 0.6       # e.g. 0.6 = 6折; 1.0 = no discount
    min_fee: float = 20.0
    tax_rate: float = 0.0015        # day-trade sell tax
    slip_ticks: int = 1             # ticks lost on each market fill (entry, stop, close-out)

    def fee(self, notional: float) -> float:
        return max(self.min_fee, notional * self.fee_rate * self.fee_discount)

    def net_pnl(self, buy_price: float, sell_price: float, shares: int) -> float:
        """Net NT$ P&L of a buy-then-sell round trip, after fees and tax."""
        buy = buy_price * shares
        sell = sell_price * shares
        return sell - buy - self.fee(buy) - self.fee(sell) - sell * self.tax_rate

    def slip(self, price: float, side: str) -> float:
        """Price after losing `slip_ticks` ticks: side='buy' pays up, 'sell' gets less."""
        p = price
        for _ in range(self.slip_ticks):
            t = tick_size(p if side == "buy" else max(p - 1e-9, 0.01))
            p = p + t if side == "buy" else p - t
        return round(p, 2)
