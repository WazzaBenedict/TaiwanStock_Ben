"""月調整多因子回測引擎。

流程（每個月）：
1. 月底最後一個交易日 d 收盤後打分，只用 d（含）以前的資料（factors 模組保證）
2. 下一個交易日開盤價成交，等權持有分數最高的 top_n 檔
3. 每日以收盤價計算持倉市值
4. 每筆委託扣手續費（每筆最低 20 元，以 capital 換算）、賣出證交稅、滑價（依流動性分級或固定）
5. 股票資料中斷且之後再也沒有資料（下市），以最後收盤價扣賣出成本後轉為現金
6. 同期間買進持有 0050（含息、扣買進成本）當基準

panel 需要：close, open（還原價）, volume_value（未還原成交金額）, benchmark_close / benchmark_open，
可選 revenue, inst_net, app_score / app_signal。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import TaiwanCosts, tiered_slippage
from .factors import FACTORS, composite_score


@dataclass
class BacktestConfig:
    weights: dict[str, float]
    top_n: int = 20
    universe_size: int = 300          # 依 20 日平均成交金額取前 N 檔當候選池
    min_avg_value: float = 5e7        # 20 日平均成交金額至少 5,000 萬元
    liquidity_window: int = 20
    capital: float = 1_000_000.0      # 初始資金（元），用來換算每筆最低手續費
    slippage: float | str = "tiered"  # "tiered" 依流動性分級，或固定單邊比例（例如 0.003）
    exclude: tuple[str, ...] = ()     # 排除的股票（例如測試「不含台積電」）
    start: str | None = None          # 第一個打分日（含）
    end: str | None = None            # 最後一個交易日（含）
    costs: TaiwanCosts = field(default_factory=TaiwanCosts)


def month_end_dates(index: pd.DatetimeIndex, start=None, end=None) -> list[pd.Timestamp]:
    s = index.to_series()
    ends = s.groupby(index.to_period("M")).max()
    if start:
        ends = ends[ends >= pd.Timestamp(start)]
    if end:
        ends = ends[ends <= pd.Timestamp(end)]
    return list(ends)


def avg_traded_value(panel: dict, as_of: pd.Timestamp, window: int) -> tuple[pd.Series, pd.Series]:
    val = panel["volume_value"].loc[:as_of].iloc[-window:]
    return val.mean(), val.count()


def eligible_universe(panel: dict, as_of: pd.Timestamp, cfg: BacktestConfig) -> pd.Index:
    """as_of 當天有成交、流動性達標的股票，依平均成交金額取前 universe_size 檔。"""
    close = panel["close"].loc[:as_of]
    if close.empty or close.index[-1] != as_of:
        return pd.Index([])
    traded = close.iloc[-1].notna()
    avg, cnt = avg_traded_value(panel, as_of, cfg.liquidity_window)
    ok = traded & (cnt >= cfg.liquidity_window * 0.7) & (avg >= cfg.min_avg_value)
    if cfg.exclude:
        ok &= ~ok.index.isin(cfg.exclude)
    return avg[ok].sort_values(ascending=False).index[: cfg.universe_size]


class FactorCache:
    """同一個 panel 上重複跑多組參數時，快取每個因子在每個打分日的原始值。"""

    def __init__(self, panel: dict):
        self.panel = panel
        self._raw: dict[tuple[str, pd.Timestamp], pd.Series] = {}

    def raw(self, name: str, as_of: pd.Timestamp) -> pd.Series:
        key = (name, as_of)
        if key not in self._raw:
            self._raw[key] = FACTORS[name](self.panel, as_of)
        return self._raw[key]


def select_picks(panel: dict, as_of: pd.Timestamp, cfg: BacktestConfig,
                 cache: FactorCache | None = None, info: dict | None = None) -> pd.Series:
    """回傳 as_of 的入選股票與分數（由高到低）。"""
    cache = cache or FactorCache(panel)
    info = info if info is not None else {}
    uni = eligible_universe(panel, as_of, cfg)
    info["universe"] = len(uni)
    if len(uni) == 0:
        return pd.Series(dtype=float)
    score = composite_score(panel, as_of, cfg.weights, universe=uni, info=info, raw_fn=cache.raw)
    return score.sort_values(ascending=False).iloc[: cfg.top_n]


def run_backtest(panel: dict, cfg: BacktestConfig, cache: FactorCache | None = None) -> dict:
    cache = cache or FactorCache(panel)
    close, open_ = panel["close"], panel["open"]
    cal = close.index
    signal_dates = month_end_dates(cal, cfg.start, cfg.end)
    # 最後一個月底若沒有下一個交易日可成交就不算
    signal_dates = [d for d in signal_dates if cal.get_loc(d) + 1 < len(cal)]
    if not signal_dates:
        raise ValueError("no rebalance dates in range")
    exec_map = {cal[cal.get_loc(d) + 1]: d for d in signal_dates}
    first_exec = min(exec_map)
    end = pd.Timestamp(cfg.end) if cfg.end else cal[-1]
    days = cal[(cal >= first_exec) & (cal <= end)]

    last_valid = close.apply(lambda s: s.last_valid_index())
    costs, K = cfg.costs, cfg.capital
    pos: dict[str, float] = {}         # 持股市值（初始資金 = 1.0；以 last_px 計價）
    last_px: dict[str, float] = {}
    cash = 1.0
    equity, rebalances = [], []
    total_cost = 0.0

    def slip_for(avg: pd.Series, sid: str) -> float:
        if cfg.slippage == "tiered":
            v = avg.get(sid)
            return tiered_slippage(float(v) if pd.notna(v) else 0.0)
        return float(cfg.slippage)

    def order_cost(amount: float, side: str, slip: float) -> float:
        # amount 以初始資金為單位，換成元算最低手續費後再換回來
        return costs.order_cost(amount * K, side, slip) / K

    for t in days:
        c_row, o_row = close.loc[t], open_.loc[t]
        if t in exec_map:
            sig = exec_map[t]
            # 1) 前一日收盤 → 今日開盤
            for sid in list(pos):
                o = o_row.get(sid)
                if pd.notna(o) and last_px.get(sid):
                    pos[sid] *= o / last_px[sid]
                    last_px[sid] = o
            info: dict = {}
            picks = select_picks(panel, sig, cfg, cache, info)
            avg, _ = avg_traded_value(panel, sig, cfg.liquidity_window)
            tradable = [s for s in picks.index if pd.notna(o_row.get(s)) and o_row.get(s) > 0]
            frozen = {s: v for s, v in pos.items() if not (pd.notna(o_row.get(s)) and o_row.get(s) > 0)}
            V = cash + sum(pos.values())
            V_free = V - sum(frozen.values())
            target = {s: V_free / len(tradable) for s in tradable} if tradable else {}
            cost, traded = 0.0, 0.0
            for s in set(pos) | set(target):
                if s in frozen:
                    continue
                diff = target.get(s, 0.0) - pos.get(s, 0.0)
                if abs(diff) < 1e-12:
                    continue
                traded += abs(diff)
                cost += order_cost(diff, "buy" if diff > 0 else "sell", slip_for(avg, s))
            scale = (V_free - cost) / V_free if V_free > 0 else 0.0
            new_pos = {s: v * scale for s, v in target.items()}
            for s in tradable:
                last_px[s] = o_row[s]
            pos = {**frozen, **new_pos}
            cash = 0.0 if target else V_free
            total_cost += cost
            rebalances.append({"signal_date": sig, "trade_date": t, "picks": list(picks.index),
                               "scores": picks.round(4).to_dict(), "turnover": traded / V if V else 0.0,
                               "cost": cost / V if V else 0.0, **info})
        # 2) 收盤計價、處理下市
        for sid in list(pos):
            c = c_row.get(sid)
            if pd.notna(c) and last_px.get(sid):
                pos[sid] *= c / last_px[sid]
                last_px[sid] = c
            elif last_valid.get(sid) is not None and t > last_valid[sid]:
                v = pos.pop(sid)
                last_px.pop(sid, None)
                fee = order_cost(v, "sell", 0.005)
                cash += v - fee
                total_cost += fee
        equity.append(cash + sum(pos.values()))

    eq = pd.Series(equity, index=days, name="strategy")
    b_open = panel["benchmark_open"].loc[first_exec]
    b_buy = costs.order_cost(K, "buy", 0.001) / K
    bench = panel["benchmark_close"].reindex(days).ffill() / b_open * (1 - b_buy)
    bench.name = "benchmark"
    return {"equity": eq, "benchmark": bench, "rebalances": rebalances,
            "total_cost": total_cost, "config": cfg}
