"""全 App 共用的台股交易成本模型：元大證券電子下單（V13.2.0 起唯一的一套數字）。

交易計畫卡、⚡ 當沖、台股時光機、個股回測、勝率統計都從這裡拿手續費與證交稅。

元大證券（查證日 2026-11-02，實際以你的帳戶對帳單為準）：
- 手續費牌價 0.1425%，買、賣各收一次；電子下單（投資先生 App / 網路下單）6 折 = 0.0855%。
- 整股每筆最低 20 元；盤中／盤後零股電子下單每筆最低 1 元。
- 手續費、證交稅都是「無條件捨去到元」。
- 折扣依帳戶而定（大戶可議價），所以折扣是使用者設定，預設 0.6。
  也可用環境變數 BROKER_FEE_DISCOUNT 改伺服器預設。

證券交易稅（賣出時收）：
- 一般股票 0.3%；ETF 0.1%；債券 ETF 目前免徵。
- 現股當沖 0.15%（減半優惠，《證券交易稅條例》延長至 2027-12-31）。

滑價不是券商收費，由各模組自己估（交易計畫用比例、當沖用跳動檔數）。
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass

LOT = 1000  # 一張 = 1000 股


def _env_discount() -> float:
    try:
        v = float(os.getenv("BROKER_FEE_DISCOUNT", "0.6"))
        return v if 0 < v <= 1 else 0.6
    except ValueError:
        return 0.6


DEFAULT_DISCOUNT = _env_discount()

SOURCES = [
    {"title": "元大證券 電子下單手續費 6 折、整股低消 20 元、零股低消 1 元（第三方整理）",
     "url": "https://cevisub.com/stock-pro/yuanta-securities-2026-fees-comparison-negotiation/"},
    {"title": "2026 證券戶推薦：20 家券商手續費比較", "url": "https://www.money101.com.tw/blog/%E6%96%B0%E6%89%8B%E9%96%8B%E6%88%B6%E9%81%B8%E5%93%AA%E5%AE%B6%E5%93%AA%E5%AE%B6%E5%88%B8%E5%95%86%E6%89%8B%E7%BA%8C%E8%B2%BB%E6%9C%80%E4%BE%BF%E5%AE%9C-%E4%B8%8B%E5%96%AE%E8%BB%9F%E9%AB%94"},
    {"title": "現股當沖證交稅減半延長至 2027-12-31（立法院三讀）", "url": "https://www.ctee.com.tw/news/20250101700052-430104"},
]


@dataclass(frozen=True)
class BrokerFees:
    name: str = "元大證券 電子下單"
    fee_rate: float = 0.001425       # 牌價
    fee_discount: float = DEFAULT_DISCOUNT
    min_fee: float = 20.0            # 整股每筆低消
    min_fee_odd: float = 1.0         # 零股每筆低消
    tax_stock: float = 0.003
    tax_etf: float = 0.001
    tax_daytrade: float = 0.0015

    @property
    def eff_fee_rate(self) -> float:
        return self.fee_rate * self.fee_discount

    def _one(self, notional: float, minimum: float) -> float:
        if notional <= 0:
            return 0.0
        return float(max(minimum, math.floor(notional * self.eff_fee_rate)))

    def fee(self, price: float, shares: int) -> float:
        """單邊手續費（元）。整張與零股分開下單，各自套低消。"""
        shares = int(shares)
        lots, odd = divmod(shares, LOT)
        return self._one(price * lots * LOT, self.min_fee) + self._one(price * odd, self.min_fee_odd)

    def fee_notional(self, notional: float, odd_lot: bool = False) -> float:
        return self._one(notional, self.min_fee_odd if odd_lot else self.min_fee)

    def tax_rate(self, etf: bool | str = False, daytrade: bool = False) -> float:
        """etf 可傳 True / False / "bond"。當沖只適用一般股票（ETF 本來就 0.1%）。"""
        if etf == "bond":
            return 0.0
        if etf:
            return self.tax_etf
        return self.tax_daytrade if daytrade else self.tax_stock

    def tax(self, price: float, shares: int, etf: bool | str = False, daytrade: bool = False) -> float:
        return float(math.floor(price * shares * self.tax_rate(etf, daytrade)))

    def round_trip(self, buy: float, sell: float, shares: int, etf: bool | str = False,
                   daytrade: bool = False) -> dict:
        fb, fs = self.fee(buy, shares), self.fee(sell, shares)
        tx = self.tax(sell, shares, etf, daytrade)
        gross = (sell - buy) * shares
        return {"buy_fee": fb, "sell_fee": fs, "tax": tx, "total_cost": fb + fs + tx,
                "gross_pnl": round(gross, 2), "net_pnl": round(gross - fb - fs - tx, 2)}

    def describe(self) -> dict:
        d = asdict(self)
        d.update(eff_fee_rate_pct=round(self.eff_fee_rate * 100, 4), sources=SOURCES, as_of="2026-11-02",
                 note="手續費、證交稅無條件捨去到元；整股低消 20 元、零股低消 1 元；折扣依帳戶而定，可在設定修改。")
        return d


def broker(fee_discount: float | None = None) -> BrokerFees:
    if fee_discount is None or not (0 < fee_discount <= 1):
        return BrokerFees()
    return BrokerFees(fee_discount=float(fee_discount))


def is_etf(stock_id: str) -> bool | str:
    """00 開頭為 ETF；結尾 B 為債券 ETF（目前免證交稅）。"""
    sid = str(stock_id).upper()
    if not sid.startswith("00"):
        return False
    return "bond" if sid.endswith("B") else True


def net_return(buy: float, sell: float, etf: bool | str = False, fees: BrokerFees | None = None,
               shares: int = LOT, slippage: float = 0.0) -> float:
    """以 `shares` 股（預設 1 張）買在 buy、賣在 sell 的扣成本報酬率（小數）。"""
    fees = fees or BrokerFees()
    if buy <= 0:
        return 0.0
    b = buy * (1 + slippage)
    s = sell * (1 - slippage)
    cost_in = b * shares + fees.fee(b, shares)
    proceeds = s * shares - fees.fee(s, shares) - fees.tax(s, shares, etf)
    return proceeds / cost_in - 1
