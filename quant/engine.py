"""月調整多因子回測引擎。

流程（每個月）：
1. 月底最後一個交易日 d 收盤後打分，只用 d（含）以前的資料（factors 模組保證）
2. 下一個交易日開盤價成交，等權持有分數最高的 top_n 檔
3. 每日以收盤價計算持倉市值
4. 換股時依成交金額扣手續費、證交稅、滑價（costs.TaiwanCosts）
5. 股票資料中斷且之後再也沒有資料（下市），以最後收盤價扣賣出成本後轉為現金
6. 同期間買進持有 0050（含息、扣買進成本）當基準

panel 需要：close, open, volume_value（DataFrame, index=交易日, columns=stock_id），
benchmark_close / benchmark_open（Series），可選 revenue, inst_net。
close/open 建議使用還原（含息）價格；volume_value 用未還原成交金額。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .costs import TaiwanCosts
from .factors import FACTORS, zscore


@dataclass
class BacktestConfig:
    weights: dict[str, float]
    top_n: int = 20
    universe_size: int = 300          # 依 60 日平均成交金額取前 N 檔當候選池
    min_avg_value: float = 2e7        # 60 日平均成交金額至少 2000 萬元
    liquidity_window: int = 60
    start: str | None = None          # 第一個打分日（含）
    end: str | None = None            # 最後一個交易日（含）
    costs: TaiwanCosts = field(default_factory=TaiwanCosts)


def month_end_dates(index: pd.DatetimeIndex, start=None, end=None) -> list[pd.Timestamp]:
    s = index.to_series()
    ends = s.groupby(index.to_period("M")).max()
    ends = ends[(ends >= pd.Timestamp(start)) if start else slice(None)]
    if end:
        ends = ends[ends <= pd.Timestamp(end)]
    return list(ends)


def eligible_universe(panel: dict, as_of: pd.Timestamp, cfg: BacktestConfig) -> pd.Index:
    """as_of 當天有成交、流動性達標的股票，依平均成交金額取前 universe_size 檔。"""
    close = panel["close"].loc[:as_of]
    if close.empty or close.index[-1] != as_of:
        return pd.Index([])
    traded = close.iloc[-1].notna()
    val = panel["volume_value"].loc[:as_of].iloc[-cfg.liquidity_window:]
    avg = val.mean()
    ok = traded & (val.count() >= cfg.liquidity_window * 0.7) & (avg >= cfg.min_avg_value)
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


def score_universe(cache: FactorCache, as_of: pd.Timestamp, universe: pd.Index,
                   weights: dict[str, float]) -> pd.Series:
    """在候選池內做 z-score 後加權；任何一個有權重的因子缺值就剔除。"""
    parts = []
    for name, w in weights.items():
        if not w:
            continue
        raw = cache.raw(name, as_of).reindex(universe)
        parts.append(zscore(raw.dropna()).reindex(universe) * w)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1)
    return df.sum(axis=1, min_count=df.shape[1]).dropna()


def select_picks(panel: dict, as_of: pd.Timestamp, cfg: BacktestConfig,
                 cache: FactorCache | None = None) -> pd.Series:
    """回傳 as_of 的入選股票與分數（由高到低）。"""
    cache = cache or FactorCache(panel)
    uni = eligible_universe(panel, as_of, cfg)
    if len(uni) == 0:
        return pd.Series(dtype=float)
    score = score_universe(cache, as_of, uni, cfg.weights)
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
    costs = cfg.costs
    pos: dict[str, float] = {}         # 持股市值（以 last_px 計價）
    last_px: dict[str, float] = {}
    cash = 1.0
    equity, rebalances = [], []
    total_cost = 0.0

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
            picks = select_picks(panel, sig, cfg, cache)
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
                traded += abs(diff)
                cost += diff * costs.buy_rate if diff > 0 else -diff * costs.sell_rate(False)
            scale = (V_free - cost) / V_free if V_free > 0 else 0.0
            new_pos = {s: v * scale for s, v in target.items()}
            for s in tradable:
                last_px[s] = o_row[s]
            pos = {**frozen, **new_pos}
            cash = 0.0 if target else V_free
            total_cost += cost
            rebalances.append({"signal_date": sig, "trade_date": t, "picks": list(picks.index),
                               "scores": picks.round(3).to_dict(), "turnover": traded / V if V else 0.0,
                               "cost": cost / V if V else 0.0})
        # 2) 收盤計價、處理下市
        for sid in list(pos):
            c = c_row.get(sid)
            if pd.notna(c) and last_px.get(sid):
                pos[sid] *= c / last_px[sid]
                last_px[sid] = c
            elif last_valid.get(sid) is not None and t > last_valid[sid]:
                v = pos.pop(sid)
                last_px.pop(sid, None)
                fee = v * costs.sell_rate(False)
                cash += v - fee
                total_cost += fee
        equity.append(cash + sum(pos.values()))

    eq = pd.Series(equity, index=days, name="strategy")
    b_open = panel["benchmark_open"].loc[first_exec]
    bench = panel["benchmark_close"].reindex(days).ffill() / b_open * (1 - costs.buy_rate)
    bench.name = "benchmark"
    return {"equity": eq, "benchmark": bench, "rebalances": rebalances,
            "total_cost": total_cost, "config": cfg}
