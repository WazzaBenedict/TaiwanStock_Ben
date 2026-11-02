"""0050 曝險調整（overlay）回測：每日收盤算目標曝險，隔日開盤成交。

標的：
- 0050（元大台灣50，含息還原價）
- 00631L（元大台灣50正2，2014-10-31 上市）；上市前用 0050 日報酬合成（見 synth_leveraged）
- 現金：年化 cash_rate（預設 0%，對擇時策略保守）

曝險 e ∈ [0, 2]：
- e ≤ 1：0050 權重 e，其餘現金
- e > 1：0050 權重 2−e、00631L 權重 e−1（全額投入，不融資）

成本：手續費 0.1425%（買賣各一次）、ETF 賣出證交稅 0.1%、單邊滑價（0050 0.05%、00631L 0.1%）。
目標曝險與目前曝險差距小於 band 時不調整（降低週轉）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import data as qdata

FEE = 0.001425
TAX_ETF = 0.001


@dataclass
class OverlayCosts:
    fee: float = FEE
    tax: float = TAX_ETF
    slip_core: float = 0.0005
    slip_lev: float = 0.001
    mult: float = 1.0           # 成本敏感度（例如 2.0 = 成本加倍）

    def buy(self, lev: bool) -> float:
        return (self.fee + (self.slip_lev if lev else self.slip_core)) * self.mult

    def sell(self, lev: bool) -> float:
        return (self.fee + self.tax + (self.slip_lev if lev else self.slip_core)) * self.mult


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_etf(stock_id: str, start: str = "2000-01-01", end: str | None = None) -> pd.DataFrame:
    """ETF 還原日線（open, close）。Yahoo 優先；抓不到用 FinMind 未還原價 + 除息還原。"""
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")
    df = qdata.load_price_yahoo(stock_id, start, end)
    if df is not None and len(df) > 250:
        return df[["open", "close"]].astype(float)
    raw = qdata.load_price_finmind(stock_id, start, end)
    if raw.empty:
        raise RuntimeError(f"no data for {stock_id}")
    div = qdata.finmind("TaiwanStockDividendResult", stock_id, start, end)
    close, open_ = raw["close"].astype(float), raw["open"].astype(float)
    factor = pd.Series(1.0, index=close.index)
    if not div.empty:
        div["date"] = pd.to_datetime(div["date"])
        for _, r in div.iterrows():
            d = r["date"]
            prev = close.loc[:d - pd.Timedelta(days=1)]
            if prev.empty:
                continue
            ref = float(r.get("after_price") or 0) or (prev.iloc[-1] - float(r.get("stock_and_cache_dividend") or 0))
            ratio = ref / prev.iloc[-1] if prev.iloc[-1] > 0 and ref > 0 else 1.0
            factor.loc[:prev.index[-1]] *= ratio
    return pd.DataFrame({"open": open_ * factor, "close": close * factor})


def synth_leveraged(core: pd.DataFrame, cash_rate: float, expense: float = 0.01,
                    spread: float = 0.005) -> pd.DataFrame:
    """以 0050 合成每日兩倍槓桿：r_L = 2·r − (cash_rate + spread + expense)/252。

    融資成本以「現金利率 + 利差」計（期貨隱含成本約等於無風險利率），內扣費用 1%/年。
    開盤價以同日 0050 開盤/前收比例 ×2 推算。
    """
    c = core["close"]
    r = c.pct_change().fillna(0.0)
    daily_cost = (cash_rate + spread + expense) / 252
    lev_close = (1 + 2 * r - daily_cost).cumprod() * 100
    gap = (core["open"] / c.shift(1) - 1).fillna(0.0)
    lev_open = lev_close.shift(1).fillna(100) * (1 + 2 * gap)
    return pd.DataFrame({"open": lev_open, "close": lev_close})


def splice_leveraged(core: pd.DataFrame, actual: pd.DataFrame | None, cash_rate: float) -> pd.DataFrame:
    """00631L 上市前用合成序列，上市後接真實價格（在接點等比例縮放）。"""
    syn = synth_leveraged(core, cash_rate)
    if actual is None or actual.empty:
        return syn
    actual = actual.reindex(core.index).dropna()
    first = actual.index[0]
    scale = syn.loc[first, "close"] / actual.loc[first, "close"]
    out = syn.copy()
    out.loc[first:, ["open", "close"]] = actual.loc[first:, ["open", "close"]].values * scale
    return out


# ── 回測 ─────────────────────────────────────────────────────────────────────
def weights_for(e: float) -> tuple[float, float]:
    """曝險 → (0050 權重, 00631L 權重)。"""
    e = float(np.clip(e, 0.0, 2.0))
    if e <= 1.0:
        return e, 0.0
    return 2.0 - e, e - 1.0


def run_overlay(core: pd.DataFrame, lev: pd.DataFrame, target: pd.Series, *, cash_rate: float = 0.0,
                band: float = 0.1, costs: OverlayCosts | None = None, start=None, end=None,
                cash_rates: pd.Series | None = None, trade_days: pd.DatetimeIndex | None = None) -> dict:
    """target：每日收盤算出的目標曝險（index 與 core 相同），t 日訊號於 t+1 開盤成交。

    每日淨值：前一日收盤持倉 × (今日開盤/昨收)，開盤調整後 × (今日收盤/今日開盤)。
    """
    costs = costs or OverlayCosts()
    idx = core.index
    if start:
        idx = idx[idx >= pd.Timestamp(start)]
    if end:
        idx = idx[idx <= pd.Timestamp(end)]
    tgt = target.reindex(core.index).ffill().shift(1)       # 前一日收盤訊號 → 今日開盤成交
    cash_daily_s = (cash_rates.reindex(core.index).ffill().bfill() / 252) if cash_rates is not None else None
    w_c, w_l, w_cash = 0.0, 0.0, 1.0                         # 以淨值比例表示
    nav = 1.0
    navs, exps, trades = [], [], 0
    turnover = 0.0
    prev_day = None
    for d in idx:
        if prev_day is not None:
            # 隔夜：昨收 → 今開
            gc = core.at[d, "open"] / core.at[prev_day, "close"]
            gl = lev.at[d, "open"] / lev.at[prev_day, "close"]
            cd = cash_daily_s.at[d] if cash_daily_s is not None else cash_rate / 252
            vc, vl, vk = w_c * gc, w_l * gl, w_cash * (1 + cd)
            nav_open = nav * (vc + vl + vk)
            tot = vc + vl + vk
            w_c, w_l, w_cash = vc / tot, vl / tot, vk / tot
        else:
            nav_open = nav
        # 開盤調整
        e_now = w_c + 2 * w_l
        t = tgt.get(d, np.nan)
        allowed = trade_days is None or d in trade_days or prev_day is None
        if pd.notna(t) and allowed and (prev_day is None or abs(t - e_now) >= band - 1e-12 or (t == 0 and e_now > 0)):
            nc, nl = weights_for(t)
            dc, dl = nc - w_c, nl - w_l
            cost = (max(dc, 0) * costs.buy(False) + max(-dc, 0) * costs.sell(False)
                    + max(dl, 0) * costs.buy(True) + max(-dl, 0) * costs.sell(True))
            if abs(dc) + abs(dl) > 1e-9:
                trades += 1
                turnover += (abs(dc) + abs(dl)) / 2
            nav_open *= (1 - cost)
            w_c, w_l = nc, nl
            w_cash = 1 - nc - nl
        # 盤中：今開 → 今收
        ic = core.at[d, "close"] / core.at[d, "open"]
        il = lev.at[d, "close"] / lev.at[d, "open"]
        vc, vl, vk = w_c * ic, w_l * il, w_cash
        nav = nav_open * (vc + vl + vk)
        tot = vc + vl + vk
        w_c, w_l, w_cash = vc / tot, vl / tot, vk / tot
        navs.append(nav)
        exps.append(w_c + 2 * w_l)
        prev_day = d
    eq = pd.Series(navs, index=idx)
    years = (idx[-1] - idx[0]).days / 365.25
    return {"equity": eq, "exposure": pd.Series(exps, index=idx), "trades": trades,
            "turnover_per_year": turnover / years if years > 0 else np.nan}


def buy_hold(core: pd.DataFrame, start=None, end=None, costs: OverlayCosts | None = None) -> pd.Series:
    """0050 買進持有（含息，扣一次買進成本）。"""
    costs = costs or OverlayCosts()
    c = core["close"]
    if start:
        c = c[c.index >= pd.Timestamp(start)]
    if end:
        c = c[c.index <= pd.Timestamp(end)]
    eq = c / c.iloc[0] * (1 - costs.buy(False))
    return eq
