"""交易計畫規則（參數事前凍結，2026-11-02 登錄；不可依回測結果調參）。

規則（以第 t 天收盤後的資料計算，第 t+1 天起才有效）：
- 進場：限價買進 = min(收盤, max(MA5, 收盤×0.97))，向下取到合法跳動單位；有效 3 個交易日。
- 停損：進場 − 2×ATR14；單筆風險上限 8%（超過則改為進場×0.92）。
- 目標：進場 + 2R（R = 進場 − 停損）。
- 保本：收盤 ≥ 進場 + 1R 後，下一個交易日起停損上移到進場價。
- 移動停利：保本後，停損 = max(停損, 前一日為止最高收盤 − 2.5×前一日 ATR)。
- 時間出場：持有第 20 個交易日收盤仍未出場就賣出。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PlanRules:
    entry_pullback_cap: float = 0.03   # 限價最多低於收盤 3%
    entry_valid_days: int = 3
    stop_atr: float = 2.0
    max_risk_pct: float = 0.08
    target_r: float = 2.0
    breakeven_r: float = 1.0
    trail_atr: float = 2.5
    max_hold_days: int = 20

    def as_dict(self) -> dict:
        return asdict(self)


# ── 台股升降單位 ────────────────────────────────────────────────────────────
_STOCK_TICKS = ((10, 0.01), (50, 0.05), (100, 0.1), (500, 0.5), (1000, 1.0), (math.inf, 5.0))
_ETF_TICKS = ((50, 0.01), (math.inf, 0.05))


def tick_size(price: float, etf: bool = False) -> float:
    for limit, tick in (_ETF_TICKS if etf else _STOCK_TICKS):
        if price < limit:
            return tick
    return 5.0


def round_tick(price: float, etf: bool = False, direction: str = "down") -> float:
    """取到合法價位。direction: down / up / nearest。"""
    if price is None or not np.isfinite(price) or price <= 0:
        return float("nan")
    t = tick_size(price, etf)
    q = price / t
    q = math.floor(q + 1e-9) if direction == "down" else math.ceil(q - 1e-9) if direction == "up" else round(q)
    out = q * t
    # 跨過級距邊界時（例如 50.02 → 50.0）再以新級距校正一次
    t2 = tick_size(out, etf)
    if t2 != t:
        q2 = out / t2
        out = (math.floor(q2 + 1e-9) if direction != "up" else math.ceil(q2 - 1e-9)) * t2
    return round(out, 2)


def atr14(df: pd.DataFrame) -> pd.Series:
    hi, lo, c = df["最高價"], df["最低價"], df["收盤價"]
    pc = c.shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()


def levels_at(close: float, ma5: float | None, atr: float | None,
              rules: PlanRules = PlanRules(), etf: bool = False) -> dict | None:
    """由第 t 天收盤資料算出進場 / 停損 / 目標（皆為合法跳動價位）。"""
    if not close or not np.isfinite(close) or atr is None or not np.isfinite(atr) or atr <= 0:
        return None
    raw_entry = close
    if ma5 is not None and np.isfinite(ma5):
        raw_entry = min(close, max(ma5, close * (1 - rules.entry_pullback_cap)))
    entry = round_tick(raw_entry, etf, "down")
    stop = entry - rules.stop_atr * atr
    if (entry - stop) / entry > rules.max_risk_pct:
        stop = entry * (1 - rules.max_risk_pct)
    stop = round_tick(stop, etf, "down")
    if not (0 < stop < entry):
        return None
    r = entry - stop
    target = round_tick(entry + rules.target_r * r, etf, "down")
    if target <= entry:
        return None
    return {"entry": entry, "stop": stop, "target": target, "r": round(r, 4),
            "breakeven_trigger": round(entry + rules.breakeven_r * r, 2),
            "risk_pct": round(r / entry * 100, 2)}


def make_plan(df: pd.DataFrame, rules: PlanRules = PlanRules(), etf: bool = False) -> dict | None:
    """用最後一根 K 棒（今天收盤）產生明天起生效的交易計畫。"""
    if df is None or len(df) < 20:
        return None
    a = atr14(df)
    ma5 = df["收盤價"].rolling(5).mean()
    i = len(df) - 1
    lv = levels_at(float(df["收盤價"].iloc[i]), _f(ma5.iloc[i]), _f(a.iloc[i]), rules, etf)
    if lv is None:
        return None
    lv["atr"] = round(float(a.iloc[i]), 4)
    lv["as_of"] = pd.Timestamp(df["日期"].iloc[i]).strftime("%Y-%m-%d")
    lv["close"] = float(df["收盤價"].iloc[i])
    lv["valid_days"] = rules.entry_valid_days
    lv["max_hold_days"] = rules.max_hold_days
    lv["trail_atr"] = rules.trail_atr
    return lv


def position_size(capital: float, risk_pct: float, entry: float, stop: float,
                  costs=None, etf: bool | str = False, min_fee: float | None = None) -> dict:
    """依「單筆最多虧總資金的 risk_pct」算股數（整張 + 零股），停損虧損含元大手續費、證交稅與滑價。"""
    from .costs import Costs
    costs = costs or Costs()
    b = costs.broker
    if not capital or capital <= 0 or not entry or entry <= stop:
        return {"shares": 0, "lots": 0, "odd_shares": 0, "amount": 0, "risk_amount": 0}
    budget = capital * risk_pct

    def loss(n: int) -> float:   # 買在 entry、停損賣在 stop 的總虧損（元）
        buy = entry * (1 + costs.slippage)
        sell = stop * (1 - costs.slippage)
        return (buy - sell) * n + b.fee(buy, n) + b.fee(sell, n) + b.tax(sell, n, etf)

    def cash(n: int) -> float:
        buy = entry * (1 + costs.slippage)
        return buy * n + b.fee(buy, n)

    per_share = entry * (1 + costs.buy_rate()) - stop * (1 - costs.sell_rate(etf))
    shares = min(int(budget // per_share), int(capital // (entry * (1 + costs.buy_rate()))))
    while shares > 0 and (loss(shares) > budget or cash(shares) > capital):
        shares -= 1
    amount = shares * entry
    fee = b.fee(entry, shares) if shares else 0
    out = {"shares": shares, "lots": shares // 1000, "odd_shares": shares % 1000,
           "amount": round(amount), "risk_amount": round(loss(shares)) if shares else 0,
           "buy_fee": round(fee), "broker": b.name, "fee_discount": b.fee_discount}
    if shares and fee / max(amount, 1) > b.eff_fee_rate * 1.5:
        out["min_fee_warning"] = f"金額小，最低手續費 {fee:.0f} 元約占 {fee / amount * 100:.2f}%"
    return out


def _f(x) -> float | None:
    try:
        x = float(x)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None
