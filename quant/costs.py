"""台股交易成本模型。

預設值依現行法規：
- 手續費：成交金額 0.1425%，買賣各收一次，每筆最低 20 元（可設定券商折扣）
- 證券交易稅：賣出時收，股票 0.3%，ETF 0.1%（當沖減半不適用於本策略）
- 滑價：以單邊成交金額的比例估計；固定值或依流動性分級（越冷門越高）
"""
from __future__ import annotations

from dataclasses import dataclass

# 20 日平均成交金額（元）→ 單邊滑價
SLIPPAGE_TIERS = ((1e9, 0.001), (3e8, 0.002), (1e8, 0.003), (0.0, 0.005))


def tiered_slippage(avg_value: float) -> float:
    for floor, slip in SLIPPAGE_TIERS:
        if avg_value >= floor:
            return slip
    return SLIPPAGE_TIERS[-1][1]


@dataclass(frozen=True)
class TaiwanCosts:
    fee_rate: float = 0.001425
    fee_discount: float = 1.0          # 例如 0.6 代表六折
    min_fee: float = 20.0              # 每筆最低手續費（元）
    tax_stock: float = 0.003
    tax_etf: float = 0.001
    slippage: float = 0.001

    @property
    def buy_rate(self) -> float:
        return self.fee_rate * self.fee_discount + self.slippage

    def sell_rate(self, is_etf: bool = False) -> float:
        tax = self.tax_etf if is_etf else self.tax_stock
        return self.fee_rate * self.fee_discount + tax + self.slippage

    def round_trip(self, is_etf: bool = False) -> float:
        return self.buy_rate + self.sell_rate(is_etf)

    def fee(self, amount: float) -> float:
        """單筆手續費（元），含最低 20 元。"""
        return max(self.min_fee, abs(amount) * self.fee_rate * self.fee_discount) if amount else 0.0

    def order_cost(self, amount: float, side: str, slippage: float | None = None, is_etf: bool = False) -> float:
        """一筆委託的總成本（元）：手續費（含最低）+ 滑價 + 賣出時的證交稅。"""
        amt = abs(amount)
        if not amt:
            return 0.0
        slip = self.slippage if slippage is None else slippage
        tax = (self.tax_etf if is_etf else self.tax_stock) if side == "sell" else 0.0
        return self.fee(amt) + amt * (slip + tax)


def is_etf(stock_id: str) -> bool:
    """台股 ETF 代號以 00 開頭（例如 0050、00878）。"""
    return str(stock_id).startswith("00")
