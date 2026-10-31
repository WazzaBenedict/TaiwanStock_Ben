"""驗證 App 現有的技術面評分（build_tw_ai_signal 的 confidence / signal）在全市場是否有預測力。

做法：
- 股票池：與回測相同（含下市股），每個打分日只看流動性前 300 檔
- 每週最後一個交易日收盤，用 App 原本的函式重算評分（不含即時報價、總經調整 = 0、不含歷史勝率 +5 分）
- 下一個交易日開盤買、持有 horizon 日收盤賣，計算毛報酬與扣成本淨報酬
- 每個打分日計算評分與未來報酬的 Spearman 等級相關（rank IC），再看跨期平均與 t 值
- 依訊號（BUY/WATCH/AVOID）與評分五分位，比較相對當週候選池平均的超額報酬

用法：python -m quant.signal_validation   → reports/signal_validation.md
"""
from __future__ import annotations

import pickle
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .costs import TaiwanCosts
from .engine import BacktestConfig, eligible_universe

ROOT = Path(__file__).resolve().parent.parent
START, END = "2015-01-01", "2026-10-31"


def _app():
    sys.path.insert(0, str(ROOT))
    import app  # noqa: E402  App 的評分函式
    return app


def sample_dates(cal: pd.DatetimeIndex, freq: str, horizon: int) -> list[pd.Timestamp]:
    s = cal.to_series()
    ends = s.groupby(cal.to_period(freq)).max()
    last_ok = cal[-horizon - 1]
    return [d for d in ends if pd.Timestamp(START) <= d <= last_ok]


def collect(panel: dict, frames: dict[str, pd.DataFrame], dates: list[pd.Timestamp], horizon: int,
            log=print) -> pd.DataFrame:
    app = _app()
    costs = TaiwanCosts()
    cfg = BacktestConfig(weights={})
    rows = []
    prepared = {}
    for sid, df in frames.items():
        if len(df) < 80:
            continue
        d = app.compute_all_indicators(df.copy())
        d["vol_ratio"] = d["成交股數"] / d["成交股數"].rolling(20).mean()
        d["chg_pct"] = d["收盤價"].pct_change() * 100
        prepared[sid] = (d, pd.Index(d["日期"]))
    for k, t in enumerate(dates):
        uni = eligible_universe(panel, t, cfg)
        for sid in uni:
            if sid not in prepared:
                continue
            d, idx = prepared[sid]
            if t not in idx:
                continue
            pos = idx.get_loc(t)
            if pos + horizon >= len(d) or pos < 60:
                continue
            row = d.iloc[pos]
            if pd.isna(row.get("MA60")):
                continue
            ai = app.build_tw_ai_signal(row, float(row["收盤價"]), {"winrate": 0}, {},
                                        float(row["chg_pct"]) if pd.notna(row["chg_pct"]) else 0.0,
                                        float(row["vol_ratio"]) if pd.notna(row["vol_ratio"]) else 1.0,
                                        d.iloc[pos - 59: pos + 1])
            ep = d.iloc[pos + 1]["開盤價"]
            xp = d.iloc[pos + horizon]["收盤價"]
            if not (pd.notna(ep) and ep > 0 and pd.notna(xp)):
                continue
            g = xp / ep - 1
            if abs(g) > 1.0:   # 減資或資料錯誤
                continue
            rows.append({"date": t, "stock_id": sid, "confidence": ai.get("confidence") or 0,
                         "technical_score": ai.get("technical_score"), "signal": ai.get("signal"),
                         "gross": g, "net": xp * (1 - costs.sell_rate(False)) / (ep * (1 + costs.buy_rate)) - 1})
        if k % 50 == 0:
            log(f"{horizon}d: {k}/{len(dates)} dates, {len(rows)} obs")
    return pd.DataFrame(rows)


def summarize(obs: pd.DataFrame, bench: pd.DataFrame) -> dict:
    obs = obs.copy()
    obs["excess"] = obs["gross"] - obs.groupby("date")["gross"].transform("mean")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ic = obs.groupby("date").apply(lambda g: g["confidence"].corr(g["gross"], method="spearman")
                                       if g["confidence"].nunique() > 1 else np.nan).dropna()
    by_sig = obs.groupby("signal").agg(n=("gross", "size"), gross=("gross", "mean"), net=("net", "mean"),
                                       excess=("excess", "mean"), win_net=("net", lambda x: (x > 0).mean()))
    # 每個打分日內依評分分五組（等級分組，避免同分全部擠在同一組）
    obs["quintile"] = obs.groupby("date")["confidence"].transform(
        lambda x: pd.qcut(x.rank(method="first"), 5, labels=False) + 1)
    by_q = obs.groupby("quintile").agg(n=("gross", "size"), conf=("confidence", "mean"), gross=("gross", "mean"),
                                       excess=("excess", "mean"))
    q_spread = obs[obs.quintile == 5].groupby("date")["gross"].mean() - obs[obs.quintile == 1].groupby("date")["gross"].mean()
    buy = obs[obs.signal == "BUY"].merge(bench, on="date", how="left")
    return {"ic_mean": ic.mean(), "ic_t": ic.mean() / ic.std() * np.sqrt(len(ic)), "ic_pos": (ic > 0).mean(),
            "n_dates": len(ic), "n_obs": len(obs), "by_signal": by_sig, "by_quintile": by_q,
            "q_spread": q_spread.mean(), "q_spread_t": q_spread.mean() / q_spread.std() * np.sqrt(len(q_spread)),
            "buy_net": buy["net"].mean() if len(buy) else np.nan,
            "buy_vs_0050": (buy["net"] - buy["bench_net"]).mean() if len(buy) else np.nan,
            "buy_beat_0050": (buy["net"] > buy["bench_net"]).mean() if len(buy) else np.nan, "n_buy": len(buy)}


def bench_returns(panel: dict, dates, horizon: int) -> pd.DataFrame:
    c, o = panel["benchmark_close"], panel["benchmark_open"]
    cal = c.index
    costs = TaiwanCosts()
    out = []
    for t in dates:
        pos = cal.get_loc(t)
        ep, xp = o.iloc[pos + 1], c.iloc[pos + horizon]
        out.append({"date": t, "bench_net": xp * (1 - costs.sell_rate(True)) / (ep * (1 + costs.buy_rate)) - 1})
    return pd.DataFrame(out)


def pct(x, d=2):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.{d}f}%"


def render(results: dict) -> str:
    lines = ["# App 技術面評分的全市場驗證", "",
             f"產生時間：{datetime.now():%Y-%m-%d %H:%M}　期間：{START[:4]} 年起至資料截止", "",
             "> 驗證的是 App 現有 `build_tw_ai_signal` 算出的「信心」分數與 BUY/WATCH/AVOID 訊號。"
             "樣本為每期流動性前 300 檔上市股（含後來下市的股票），隔日開盤進場。", ""]
    for name, r in results.items():
        bs, bq = r["by_signal"], r["by_quintile"]
        lines += [f"## 持有 {name}", "",
                  f"- 觀察數 {r['n_obs']:,}，打分日 {r['n_dates']} 個",
                  f"- 評分與未來報酬的等級相關（rank IC）平均 **{r['ic_mean']:.3f}**，t 值 {r['ic_t']:.2f}，"
                  f"IC 為正的期數 {pct(r['ic_pos'], 0)}",
                  f"- 最高五分之一 − 最低五分之一 平均報酬差 {pct(r['q_spread'])}（t 值 {r['q_spread_t']:.2f}）",
                  f"- BUY 訊號 {r['n_buy']:,} 筆：扣成本後平均 {pct(r['buy_net'])}，"
                  f"同期 0050 扣成本後平均差 {pct(r['buy_vs_0050'])}，贏 0050 的比例 {pct(r['buy_beat_0050'], 0)}",
                  "", "| 訊號 | 筆數 | 平均毛報酬 | 平均淨報酬（扣成本） | 相對同期候選池 | 淨報酬為正比例 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for sig, x in bs.iterrows():
            lines.append(f"| {sig} | {int(x.n):,} | {pct(x.gross)} | {pct(x.net)} | {pct(x.excess)} | {pct(x.win_net, 0)} |")
        lines += ["", "| 評分五分位 | 筆數 | 平均評分 | 平均毛報酬 | 相對同期候選池 |", "|---|---:|---:|---:|---:|"]
        for q, x in bq.iterrows():
            lines.append(f"| Q{int(q)}{'（最高）' if q == 5 else '（最低）' if q == 1 else ''} | {int(x.n):,} | {x.conf:.1f} | "
                         f"{pct(x.gross)} | {pct(x.excess)} |")
        lines.append("")
    lines += ["## 怎麼解讀", "",
              "- rank IC 接近 0（|t| < 2）代表評分高低和之後漲跌沒有可靠關係。",
              "- 「相對同期候選池」是扣掉同一週所有候選股平均報酬後的差，排除大盤漲跌的影響。",
              "- BUY 的淨報酬若低於 0050，代表照訊號短線進出不如直接持有 0050。",
              "- 本驗證不含即時報價、總經調整與歷史勝率加分，這三項在 App 中最多改變約 ±10 分。", ""]
    return "\n".join(lines)


def main():
    panel = pickle.load(open(data.CACHE_DIR / "panel_base_clean.pkl", "rb"))
    uni = data.build_universe("2013-06-01")
    frames = {}
    for r in uni.itertuples():
        f = data._cache_path("ohlcv", f"{r.stock_id}_2013-06-01_2026-10-31.pkl")
        if f.exists():
            df = pd.read_pickle(f)
            if not df.empty:
                frames[r.stock_id] = df
    cal = panel["close"].index
    results = {}
    for name, freq, h in [("5 個交易日（App 回測預設，每週打分）", "W", 5), ("20 個交易日（每月打分）", "M", 20)]:
        dates = sample_dates(cal, freq, h)
        obs = collect(panel, frames, dates, h)
        obs.to_pickle(data.CACHE_DIR / f"signal_obs_{h}.pkl")
        results[name] = summarize(obs, bench_returns(panel, dates, h))
    out = ROOT / "reports" / "signal_validation.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(results), encoding="utf-8")
    for k, r in results.items():
        print(k, "IC", round(r["ic_mean"], 4), "t", round(r["ic_t"], 2), "buy_vs_0050", r["buy_vs_0050"])


if __name__ == "__main__":
    main()
