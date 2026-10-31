"""台股交易成本模型。

預設值依現行法規：
- 手續費：成交金額 0.1425%，買賣各收一次（可設定券商折扣）
- 證券交易稅：賣出時收，股票 0.3%，ETF 0.1%（當沖減半不適用於本策略）
- 滑價：以單邊成交金額的比例估計，預設 0.1%
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaiwanCosts:
    fee_rate: float = 0.001425
    fee_discount: float = 1.0          # 例如 0.6 代表六折
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


def is_etf(stock_id: str) -> bool:
    """台股 ETF 代號以 00 開頭（例如 0050、00878）。"""
    return str(stock_id).startswith("00")
