"""選股因子。

每個因子都是 `f(panel, as_of) -> pd.Series(index=stock_id)`，
只能使用 `as_of`（含）以前「當時已公開」的資料，這是避免偷看未來的關鍵。

panel 是 dict：
- "close", "open", "volume_value"：DataFrame，index=交易日，columns=stock_id
- "revenue"（可選）：DataFrame，index=營收所屬月份的月初日期，columns=stock_id
- "inst_net"（可選）：DataFrame，三大法人買賣超金額，index=交易日
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 月營收依規定於次月 10 日前公告；保守起見，視為次月 11 日起才可使用
REVENUE_PUBLISH_DAY = 11


def _history(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    return df.loc[:as_of]


def momentum_12_1(panel: dict, as_of: pd.Timestamp, lookback: int = 252, skip: int = 21) -> pd.Series:
    """過去 12 個月報酬，扣掉最近 1 個月（避開短期反轉）。"""
    close = _history(panel["close"], as_of)
    if len(close) <= lookback:
        return pd.Series(dtype=float)
    past = close.iloc[-lookback - 1]
    recent = close.iloc[-skip - 1]
    return (recent / past - 1).replace([np.inf, -np.inf], np.nan)


def momentum_6_1(panel: dict, as_of: pd.Timestamp) -> pd.Series:
    return momentum_12_1(panel, as_of, lookback=126, skip=21)


def low_volatility(panel: dict, as_of: pd.Timestamp, window: int = 120) -> pd.Series:
    """波動越低分數越高（取負號）。"""
    close = _history(panel["close"], as_of)
    if len(close) <= window:
        return pd.Series(dtype=float)
    rets = close.iloc[-window - 1:].pct_change(fill_method=None).iloc[1:]
    vol = rets.std()
    vol[rets.count() < window * 0.8] = np.nan
    return -vol


def revenue_yoy(panel: dict, as_of: pd.Timestamp, months: int = 3) -> pd.Series:
    """最近 N 個已公告月份的營收年增率（加總後比較），只用當時已公告的月份。"""
    rev = panel.get("revenue")
    if rev is None or rev.empty:
        return pd.Series(dtype=float)
    # 營收所屬月份 m 在 (m+1 月的 REVENUE_PUBLISH_DAY) 才公開
    publish_dates = rev.index + pd.offsets.MonthBegin(1) + pd.Timedelta(days=REVENUE_PUBLISH_DAY - 1)
    known = rev[publish_dates <= as_of]
    if len(known) < 12 + months:
        return pd.Series(dtype=float)
    cur = known.iloc[-months:].sum(min_count=months)
    prev = known.iloc[-12 - months:-12].sum(min_count=months)
    out = cur / prev - 1
    out[prev <= 0] = np.nan
    return out.replace([np.inf, -np.inf], np.nan)


def institutional_flow(panel: dict, as_of: pd.Timestamp, window: int = 20) -> pd.Series:
    """近 N 日三大法人買賣超金額 / 同期成交金額。"""
    inst = panel.get("inst_net")
    if inst is None or inst.empty:
        return pd.Series(dtype=float)
    net = _history(inst, as_of).iloc[-window:].sum(min_count=1)
    val = _history(panel["volume_value"], as_of).iloc[-window:].sum(min_count=1)
    out = net / val.reindex(net.index)
    out[val.reindex(net.index) <= 0] = np.nan
    return out


FACTORS = {
    "momentum_12_1": momentum_12_1,
    "momentum_6_1": momentum_6_1,
    "low_vol": low_volatility,
    "revenue_yoy": revenue_yoy,
    "inst_flow": institutional_flow,
}


def zscore(s: pd.Series) -> pd.Series:
    """橫斷面標準化，並截尾 ±3 避免極端值主導。"""
    s = s.astype(float)
    sd = s.std()
    if not np.isfinite(sd) or sd == 0:
        return s * 0
    return ((s - s.mean()) / sd).clip(-3, 3)


def composite_score(panel: dict, as_of: pd.Timestamp, weights: dict[str, float]) -> pd.Series:
    """多因子加權分數；任何一個有權重的因子缺值就不列入候選。"""
    parts = []
    for name, w in weights.items():
        if w == 0:
            continue
        raw = FACTORS[name](panel, as_of)
        parts.append(zscore(raw) * w)
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1)
    return df.sum(axis=1, min_count=df.shape[1])
