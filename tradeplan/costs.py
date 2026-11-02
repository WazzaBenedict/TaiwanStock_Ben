"""台股交易成本（比例）。與 PR #3 的 quant/costs.py 同一套數字，第 2 期合併時統一。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Costs:
    fee_rate: float = 0.001425   # 手續費，買賣各一次
    fee_discount: float = 1.0    # 券商折扣，0.6 = 六折
    tax_stock: float = 0.003     # 證交稅（賣出）
    tax_etf: float = 0.001
    slippage: float = 0.001      # 單邊滑價

    def buy_rate(self) -> float:
        return self.fee_rate * self.fee_discount + self.slippage

    def sell_rate(self, etf: bool | str = False) -> float:
        return self.fee_rate * self.fee_discount + self.tax(etf) + self.slippage

    def tax(self, etf: bool | str = False) -> float:
        """etf 可傳 True / False / "bond"（債券 ETF 免證交稅）。"""
        if etf == "bond":
            return 0.0
        return self.tax_etf if etf else self.tax_stock


def is_etf(stock_id: str) -> bool | str:
    """00 開頭為 ETF；結尾 B 為債券 ETF（目前免證交稅）。"""
    sid = str(stock_id).upper()
    if not sid.startswith("00"):
        return False
    return "bond" if sid.endswith("B") else True
