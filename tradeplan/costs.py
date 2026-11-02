"""交易計畫用的成本：手續費與證交稅來自全 App 共用的元大證券模型（twcosts.py），再加單邊滑價。

回測假設每筆買賣 1 張（lot_shares），所以低價股會吃到整股最低手續費 20 元。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from twcosts import LOT, BrokerFees, is_etf  # noqa: F401  (is_etf 由此 re-export)


@dataclass(frozen=True)
class Costs:
    broker: BrokerFees = field(default_factory=BrokerFees)
    slippage: float = 0.001      # 單邊滑價
    lot_shares: int = LOT        # 回測每筆股數（算最低手續費用）

    @property
    def fee_rate(self) -> float:
        return self.broker.fee_rate

    @property
    def fee_discount(self) -> float:
        return self.broker.fee_discount

    def _fee_rate_at(self, price: float | None) -> float:
        if not price or price <= 0:
            return self.broker.eff_fee_rate
        return self.broker.fee(price, self.lot_shares) / (price * self.lot_shares)

    def buy_rate(self, price: float | None = None) -> float:
        return self._fee_rate_at(price) + self.slippage

    def sell_rate(self, etf: bool | str = False, price: float | None = None) -> float:
        return self._fee_rate_at(price) + self.tax(etf) + self.slippage

    def tax(self, etf: bool | str = False) -> float:
        """etf 可傳 True / False / "bond"（債券 ETF 免證交稅）。"""
        return self.broker.tax_rate(etf)
