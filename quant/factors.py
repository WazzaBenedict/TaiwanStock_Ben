"""選股因子。

每個因子都是 `f(panel, as_of) -> pd.Series(index=stock_id)`，
只能使用 `as_of`（含）以前「當時已公開」的資料，這是避免偷看未來的關鍵。

panel 是 dict：
- "close", "open"：還原（含息）價格 DataFrame，index=交易日，columns=stock_id —— 只用來算報酬類因子
- "volume_value"：未還原成交金額 DataFrame —— 只用來算流動性
- "revenue"（可選）：DataFrame，index=營收所屬月份的月初日期，columns=stock_id
- "inst_net"（可選）：DataFrame，三大法人買賣超金額（股數 × 未還原價），index=交易日
- "app_score" / "app_signal"（可選）：App 技術面評分與訊號，index=打分日

as_of 當天沒有價格（停牌、已下市）的股票一律不給分，避免用過期價格打分。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 月營收依規定於次月 10 日前公告；保守起見，視為次月 11 日起才可使用
REVENUE_PUBLISH_DAY = 11


def _history(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    return df.loc[:as_of]


def _traded_on(close: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """as_of 當天有收盤價的股票（布林）。"""
    if close.empty or close.index[-1] != as_of:
        return pd.Series(False, index=close.columns)
    return close.iloc[-1].notna()


def momentum_12_1(panel: dict, as_of: pd.Timestamp, lookback: int = 252, skip: int = 21) -> pd.Series:
    """過去 12 個月報酬，扣掉最近 1 個月（避開短期反轉）。用還原價。"""
    close = _history(panel["close"], as_of)
    if len(close) <= lookback:
        return pd.Series(dtype=float)
    past = close.iloc[-lookback - 1]
    recent = close.iloc[-skip - 1]
    out = (recent / past - 1).replace([np.inf, -np.inf], np.nan)
    return out.where(_traded_on(close, as_of))


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
    return (-vol).where(_traded_on(close, as_of))


def revenue_yoy(panel: dict, as_of: pd.Timestamp, months: int = 3, max_stale_months: int = 2) -> pd.Series:
    """最近 N 個已公告月份的營收年增率（合計後比較），只用當時已公告的月份。

    依「月份標籤」對齊去年同月（不是往前數 12 列），缺任何一個月就不給分；
    最新已公告月份若超過 max_stale_months 個月沒更新（停止申報、下市）也不給分。
    """
    rev = panel.get("revenue")
    if rev is None or rev.empty:
        return pd.Series(dtype=float)
    # 營收所屬月份 m 在 (m+1 月的 REVENUE_PUBLISH_DAY) 才公開
    publish_dates = rev.index + pd.offsets.MonthBegin(1) + pd.Timedelta(days=REVENUE_PUBLISH_DAY - 1)
    known = rev[publish_dates <= as_of]
    if known.empty:
        return pd.Series(dtype=float)
    latest = known.index[-1]
    cur_labels = pd.date_range(end=latest, periods=months, freq="MS")
    prev_labels = cur_labels - pd.DateOffset(years=1)
    cur = known.reindex(cur_labels).sum(min_count=months)
    prev = known.reindex(prev_labels).sum(min_count=months)
    out = cur / prev - 1
    out[prev <= 0] = np.nan
    # 個股層級的新鮮度：該股最後一筆有值的月份不能太舊
    last_seen = known.apply(lambda s: s.last_valid_index())
    cutoff = pd.Timestamp(as_of).to_period("M").to_timestamp() - pd.DateOffset(months=max_stale_months + 1)
    stale = last_seen.isna() | (pd.to_datetime(last_seen) < cutoff)
    out[stale.reindex(out.index, fill_value=True)] = np.nan
    return out.replace([np.inf, -np.inf], np.nan)


def institutional_flow(panel: dict, as_of: pd.Timestamp, window: int = 20, min_coverage: float = 0.75) -> pd.Series:
    """近 N 個交易日三大法人買賣超金額 / 同期成交金額。

    以價格表的交易日為準對齊兩邊的日期；as_of 當天必須有法人資料，且視窗內至少 75% 的日子有資料。
    """
    inst = panel.get("inst_net")
    if inst is None or inst.empty:
        return pd.Series(dtype=float)
    dates = _history(panel["close"], as_of).index[-window:]
    if len(dates) < window or dates[-1] != as_of:
        return pd.Series(dtype=float)
    net = inst.reindex(index=dates)
    val = panel["volume_value"].reindex(index=dates, columns=net.columns)
    both = net.notna() & val.notna()
    net_sum = net.where(both).sum(min_count=1)
    val_sum = val.where(both).sum(min_count=1)
    out = net_sum / val_sum
    ok = (both.sum() >= window * min_coverage) & net.iloc[-1].notna() & (val_sum > 0)
    return out.where(ok)


def app_score(panel: dict, as_of: pd.Timestamp) -> pd.Series:
    """App 現有的技術面評分（只取 BUY 訊號的股票），由 quant.signal_validation 事先算好。"""
    sc, sig = panel.get("app_score"), panel.get("app_signal")
    if sc is None or as_of not in sc.index:
        return pd.Series(dtype=float)
    return sc.loc[as_of].where(sig.loc[as_of] == "BUY")


FACTORS = {
    "momentum_12_1": momentum_12_1,
    "momentum_6_1": momentum_6_1,
    "low_vol": low_volatility,
    "revenue_yoy": revenue_yoy,
    "inst_flow": institutional_flow,
    "app_score": app_score,
}


# 只對部分股票給分的因子（例如只取 BUY 訊號），不套用覆蓋率門檻
SUBSET_FACTORS = {"app_score"}


def zscore(s: pd.Series) -> pd.Series:
    """橫斷面標準化，並截尾 ±3 避免極端值主導。"""
    s = s.astype(float)
    sd = s.std()
    if not np.isfinite(sd) or sd == 0:
        return s * 0
    return ((s - s.mean()) / sd).clip(-3, 3)


def rank_normalize(s: pd.Series) -> pd.Series:
    """橫斷面百分位排名，置中到 [-0.5, 0.5]；對極端值不敏感，不同因子可直接相加。"""
    s = s.astype(float).dropna()
    if s.empty:
        return s
    return (s.rank(method="average") - 0.5) / len(s) - 0.5


def composite_score(panel: dict, as_of: pd.Timestamp, weights: dict[str, float],
                    universe: pd.Index | None = None, min_coverage: float = 0.5,
                    info: dict | None = None, raw_fn=None) -> pd.Series:
    """多因子加權分數。

    - 在 universe（可交易候選池）內做百分位排名後加權
    - 某個因子在候選池的覆蓋率低於 min_coverage（例如資料源整段缺漏），當期直接略過該因子並記錄，
      不會因為一個因子全空就讓候選清單變空
    - 其餘有權重的因子缺值的股票不列入候選，剔除數量記錄在 info
    - raw_fn(name, as_of) 可替換因子原始值的來源（回測引擎用來快取）
    """
    info = info if info is not None else {}
    used, skipped, parts = [], [], []
    for name, w in weights.items():
        if not w:
            continue
        raw = raw_fn(name, as_of) if raw_fn else FACTORS[name](panel, as_of)
        if universe is not None:
            raw = raw.reindex(universe)
        n = len(universe) if universe is not None else len(raw)
        # app_score 只有 BUY 訊號的股票有值，本來就是子集合，不做覆蓋率檢查
        need = 1 if name in SUBSET_FACTORS else n * min_coverage
        if n == 0 or raw.notna().sum() < need:
            skipped.append(name)
            continue
        used.append(name)
        parts.append(rank_normalize(raw).reindex(raw.index) * w)
    info.update({"factors_used": used, "factors_skipped": skipped})
    if not parts:
        info["dropped_missing"] = 0
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1)
    out = df.sum(axis=1, min_count=df.shape[1])
    info["dropped_missing"] = int(out.isna().sum())
    return out.dropna()
