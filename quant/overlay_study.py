"""第二輪研究：0050 曝險調整策略能否同時在報酬與 Sharpe 贏 0050。

規格見 quant/overlay_spec.json（先登錄、後跑資料）。執行：

    python -m quant.overlay_study            # 下載 0050 / 00631L，產生 reports/overlay_report.md
    python -m quant.overlay_study --demo     # 用隨機資料測流程（不寫報告）
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import cagr, deflated_sharpe, max_drawdown, sharpe, volatility
from .overlay import OverlayCosts, buy_hold, run_overlay, splice_leveraged, synth_leveraged

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "quant" / "overlay_spec.json").read_text(encoding="utf-8"))
SEG = SPEC["segments"]
FULL_START = SEG["full"][0]
PRIOR_TRIALS = 55

# 台銀一年期定存（固定）年利率，逐年近似值（央行利率決策後的大致水準），只用於合成槓桿的融資成本與現金敏感度。
TW_DEPOSIT_RATE = {
    2003: 0.014, 2004: 0.015, 2005: 0.019, 2006: 0.022, 2007: 0.026, 2008: 0.024, 2009: 0.009,
    2010: 0.010, 2011: 0.013, 2012: 0.0136, 2013: 0.0136, 2014: 0.0136, 2015: 0.013, 2016: 0.011,
    2017: 0.0104, 2018: 0.0104, 2019: 0.0104, 2020: 0.0079, 2021: 0.0078, 2022: 0.012,
    2023: 0.016, 2024: 0.017, 2025: 0.017, 2026: 0.017,
}


def rate_series(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series([TW_DEPOSIT_RATE.get(d.year, 0.017) for d in index], index=index)


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_data() -> dict:
    from . import data as qdata
    from .overlay import load_etf

    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    yh = qdata.load_price_yahoo("0050", "2003-01-01", end)[["open", "close"]].astype(float).dropna()
    core, source = yh, "Yahoo"
    if yh.empty or yh.index[0] > pd.Timestamp("2004-01-31"):
        # Yahoo 前段缺：用 FinMind 未還原價 + 除權息還原補到 Yahoo 起點前
        fm = load_etf_finmind("0050", "2003-01-01", end)
        if not yh.empty:
            first = yh.index[0]
            scale = yh.loc[first, "close"] / fm.loc[first, "close"]
            core = pd.concat([fm.loc[:first - pd.Timedelta(days=1)] * scale, yh]).sort_index()
            source = f"FinMind（還原）至 {first.date()}，之後 Yahoo"
        else:
            core, source = fm, "FinMind（還原）"
    core = core[~core.index.duplicated()]
    from .overlay import clean_etf
    notes = []
    core = clean_etf(core, log=notes.append)
    try:
        lev_actual = qdata.load_price_yahoo("00631L", "2014-10-01", end)[["open", "close"]].astype(float).dropna()
        lev_actual = clean_etf(lev_actual, log=lambda m: notes.append("00631L " + m))
    except Exception:  # noqa: BLE001
        lev_actual = pd.DataFrame()
    return {"core": core, "lev_actual": lev_actual, "core_source": source, "clean_notes": notes}


def load_etf_finmind(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """FinMind 未還原價 + TaiwanStockDividendResult 還原；另處理 1 拆 N 分割（單日價格比 < 0.6）。"""
    from . import data as qdata
    raw = qdata.load_price_finmind(stock_id, start, end)
    close, open_ = raw["close"].astype(float), raw["open"].astype(float)
    factor = pd.Series(1.0, index=close.index)
    div = qdata.finmind("TaiwanStockDividendResult", stock_id, start, end)
    if not div.empty:
        div["date"] = pd.to_datetime(div["date"])
        for _, r in div.iterrows():
            prev = close.loc[:r["date"] - pd.Timedelta(days=1)]
            if prev.empty:
                continue
            ref = float(r.get("after_price") or 0)
            if ref <= 0:
                ref = prev.iloc[-1] - float(r.get("stock_and_cache_dividend") or 0)
            if 0 < ref < prev.iloc[-1]:
                factor.loc[:prev.index[-1]] *= ref / prev.iloc[-1]
    ratio = close / close.shift(1)
    for d in ratio[ratio < 0.6].index:            # 分割
        factor.loc[:close.index[close.index.get_loc(d) - 1]] *= float(ratio.loc[d])
    return pd.DataFrame({"open": open_ * factor, "close": close * factor})


def demo_data(seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2003-01-02", "2026-10-30")
    vol = np.exp(np.cumsum(rng.normal(0, 0.05, len(idx))) * 0.1) * 0.012
    r = rng.normal(0.0004, 1, len(idx)) * vol
    close = 50 * np.cumprod(1 + r)
    open_ = close / (1 + r) * (1 + r * rng.uniform(0, 0.5, len(idx)))
    core = pd.DataFrame({"open": open_, "close": close}, index=idx)
    return {"core": core, "lev_actual": pd.DataFrame(), "core_source": "demo"}


# ── 訊號 ─────────────────────────────────────────────────────────────────────
def month_end_mask(index: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(index, index=index)
    last = s.groupby(index.to_period("M")).transform("max")
    return pd.Series(index == last.values, index=index)


def monthly_hold(values: pd.Series, mask: pd.Series) -> pd.Series:
    """只在月底更新、其餘日沿用。"""
    return values.where(mask).ffill()


def sig_faber(core, months=10, on=1.0, **_):
    c = core["close"]
    me = month_end_mask(c.index)
    mc = c[me]
    ma = mc.rolling(months).mean()
    sig = (mc > ma).astype(float).where(ma.notna()) * on
    return sig.reindex(c.index).ffill()


def sig_ma_daily(core, ma=200, on=1.5, **_):
    c = core["close"]
    m = c.rolling(ma).mean()
    return ((c > m).astype(float) * on).where(m.notna())


def sig_abs_mom(core, months=12, on=1.5, **_):
    c = core["close"]
    me = month_end_mask(c.index)
    mc = c[me]
    ret = mc / mc.shift(months) - 1
    rf = rate_series(mc.index) * months / 12
    sig = (ret > rf).astype(float).where(ret.notna()) * on
    return sig.reindex(c.index).ffill()


def realized_var(core, window):
    r = core["close"].pct_change()
    return r.rolling(window).var() * 252


def sig_volman(core, window=21, cap=1.5, c=None, **_):
    var = realized_var(core, window)
    me = month_end_mask(core.index)
    w = (c / var).clip(upper=cap)
    return monthly_hold(w, me)


def sig_trend_vol(core, ma=200, window=20, cap=1.5, sigma_star=None, **_):
    c = core["close"]
    m = c.rolling(ma).mean()
    trend = (c > m).astype(float).where(m.notna())
    sig = np.sqrt(realized_var(core, window))
    me = month_end_mask(c.index)
    scale = monthly_hold((sigma_star / sig).clip(upper=cap), me)
    return trend * scale


SIGNALS = {"T1": sig_faber, "T2": sig_faber, "T3": sig_ma_daily, "T4": sig_abs_mom, "T5": sig_volman, "T6": sig_trend_vol}


# ── 評估 ─────────────────────────────────────────────────────────────────────
class Study:
    def __init__(self, d: dict, cost_mult: float = 1.0, cash: str = "zero"):
        self.core = d["core"]
        rates = rate_series(self.core.index)
        self.rates = rates
        self.lev = splice_leveraged_rates(self.core, d.get("lev_actual"), rates)
        self.cost_mult = cost_mult
        self.cash = cash
        self.last = self.core.index[-1]

    def costs(self, mult=None):
        c = OverlayCosts(mult=self.cost_mult if mult is None else mult)
        return c

    def run(self, target, start=FULL_START, end=None, mult=None, cash=None, trade_days=None, band=0.1):
        cash = cash or self.cash
        cr = self.rates if cash == "deposit" else None
        return run_overlay(self.core, self.lev_for_period(), target, costs=self.costs(mult), start=start, end=end,
                           cash_rates=cr, trade_days=trade_days, band=band)

    def lev_for_period(self):
        return self.lev

    def bench(self, start=FULL_START, end=None, mult=None):
        return buy_hold(self.core, start, end, self.costs(mult))


def splice_leveraged_rates(core, actual, rates):
    """與 overlay.splice_leveraged 相同，但融資成本用逐年利率。"""
    c = core["close"]
    r = c.pct_change().fillna(0.0)
    daily_cost = (rates + 0.005 + 0.01) / 252
    lev_close = (1 + 2 * r - daily_cost).cumprod() * 100
    gap = (core["open"] / c.shift(1) - 1).fillna(0.0)
    lev_open = lev_close.shift(1).fillna(100) * (1 + 2 * gap)
    syn = pd.DataFrame({"open": lev_open, "close": lev_close})
    if actual is None or len(actual) == 0:
        return syn
    actual = actual.reindex(core.index)
    first = actual["close"].first_valid_index()
    actual = actual.loc[first:].ffill()      # 0050 有交易但 00631L 缺資料的日子沿用前值
    scale = syn.loc[first, "close"] / actual.loc[first, "close"]
    out = syn.copy()
    out.loc[first:, ["open", "close"]] = actual.loc[first:, ["open", "close"]].values * scale
    return out


def stats(eq: pd.Series) -> dict:
    eq = eq / eq.iloc[0]
    return {"cagr": cagr(eq), "vol": volatility(eq), "sharpe": sharpe(eq), "mdd": max_drawdown(eq)}


def beats(s: dict, b: dict) -> bool:
    return s["cagr"] > b["cagr"] and s["sharpe"] > b["sharpe"]


def seg_bounds(name, last):
    a, b = SEG[name]
    return a, (last if b == "latest" else b)


def block_bootstrap_p(r1: pd.Series, r2: pd.Series, block=20, n=2000, seed=7) -> float:
    """H0: Sharpe(r1) ≤ Sharpe(r2)。圓形區塊 bootstrap，回傳單尾 p（以中心化的差異分佈計）。"""
    df = pd.concat([r1, r2], axis=1).dropna().values
    T = len(df)
    rng = np.random.default_rng(seed)

    def sr(x):
        s = x.std(axis=0, ddof=1)
        return x.mean(axis=0) / s * np.sqrt(252)

    obs = sr(df)
    d_obs = obs[0] - obs[1]
    nb = int(np.ceil(T / block))
    diffs = np.empty(n)
    for i in range(n):
        starts = rng.integers(0, T, nb)
        ix = (starts[:, None] + np.arange(block)[None, :]).ravel()[:T] % T
        s = sr(df[ix])
        diffs[i] = s[0] - s[1]
    centered = diffs - diffs.mean()
    return float((centered >= d_obs).mean())


def calibrate_volman(st: Study, window, cap=1.5):
    """二分搜尋 c，使樣本內策略波動 = 樣本內 0050 波動。"""
    is_a, is_b = SEG["in_sample_for_selection"]
    target_vol = stats(st.bench(is_a, is_b))["vol"]
    lo, hi = 1e-4, 1.0
    for _ in range(40):
        mid = np.sqrt(lo * hi)
        v = stats(st.run(sig_volman(st.core, window, cap, c=mid), is_a, is_b)["equity"])["vol"]
        if v < target_vol:
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


def build_target(st: Study, cid: str, params: dict) -> tuple[pd.Series, dict]:
    spec = next(c for c in SPEC["candidates"] if c["id"] == cid)
    kw = dict(params)
    extra = {}
    if "on" in spec:
        kw["on"] = spec["on"]
    if "cap" in spec:
        kw["cap"] = spec["cap"]
    if cid == "T5":
        kw["c"] = calibrate_volman(st, kw["window"], kw["cap"])
        extra["c"] = kw["c"]
    if cid == "T6":
        is_a, is_b = SEG["in_sample_for_selection"]
        kw["sigma_star"] = stats(st.bench(is_a, is_b))["vol"]
        extra["sigma_star"] = kw["sigma_star"]
    return SIGNALS[cid](st.core, **kw), extra


def neighbors(params: dict) -> list[dict]:
    keys = list(params)
    opts = []
    for k in keys:
        v = params[k]
        lo, hi = int(round(v * 0.75)), int(round(v * 1.25))
        opts.append(sorted({lo, v, hi}))
    out = []
    for combo in itertools.product(*opts):
        p = dict(zip(keys, combo))
        if p != params:
            out.append(p)
    return out


def evaluate(st: Study, cid: str, params: dict, full=True) -> dict:
    target, extra = build_target(st, cid, params)
    res = st.run(target)
    eq = res["equity"]
    out = {"id": cid, "params": params, **extra, "trades_per_year": res["trades"] / ((eq.index[-1] - eq.index[0]).days / 365.25),
           "avg_exposure": float(res["exposure"].mean()), "turnover_per_year": res["turnover_per_year"],
           "full": stats(eq), "target": target, "result": res}
    for s in ("A", "B", "C"):
        a, b = seg_bounds(s, st.last)
        out[s] = stats(eq.loc[a:b])
    a, b = SEG["in_sample_for_selection"]
    out["IS"] = stats(eq.loc[a:b])
    return out


def yearly(eq: pd.Series) -> pd.Series:
    y = eq.resample("YE").last()
    first = pd.Series([eq.iloc[0]], index=[eq.index[0] - pd.Timedelta(days=1)])
    return pd.concat([first, y]).pct_change().dropna()


def main(demo=False):
    d = demo_data() if demo else load_data()
    st = Study(d)
    core = st.core
    log = []
    bench_eq = st.bench()
    B = {"full": stats(bench_eq)}
    for s in ("A", "B", "C"):
        a, b = seg_bounds(s, st.last)
        B[s] = stats(bench_eq.loc[a:b])
    a, b = SEG["in_sample_for_selection"]
    B["IS"] = stats(bench_eq.loc[a:b])

    # 合成槓桿校驗
    track = None
    la = d.get("lev_actual")
    if la is not None and len(la) > 250:
        syn = synth_leveraged(core, 0.0)
        syn = splice_leveraged_rates(core, None, st.rates)
        common = la.index.intersection(syn.index)
        ra, rs = la["close"].loc[common].pct_change().dropna(), syn["close"].loc[common].pct_change().dropna()
        yrs = (common[-1] - common[0]).days / 365.25
        track = {"years": yrs, "actual_cagr": cagr(la["close"].loc[common]), "synthetic_cagr": cagr(syn["close"].loc[common]),
                 "tracking_error": float((ra - rs).std() * np.sqrt(252)),
                 "big_jumps": int((ra.abs() > 0.25).sum())}
        track["annual_diff"] = track["actual_cagr"] - track["synthetic_cagr"]

    results = {}
    for c in SPEC["candidates"]:
        results[c["id"]] = evaluate(st, c["id"], c["params"])
        r = results[c["id"]]
        log.append({"trial": PRIOR_TRIALS + len(log) + 1, "id": c["id"], "params": json.dumps(c["params"]),
                    "is_cagr": r["IS"]["cagr"], "is_sharpe": r["IS"]["sharpe"],
                    "full_cagr": r["full"]["cagr"], "full_sharpe": r["full"]["sharpe"]})

    # 挑選（只看樣本內）
    eligible = [k for k, r in results.items() if beats(r["IS"], B["IS"])]
    chosen = max(eligible, key=lambda k: (results[k]["IS"]["sharpe"], -results[k]["trades_per_year"])) if eligible else None

    # 每日超額報酬、DSR
    bret = bench_eq.pct_change().dropna()
    ex_sr = {k: (r["result"]["equity"].pct_change().dropna() - bret).dropna() for k, r in results.items()}
    sr_var = float(np.var([s.mean() / s.std() for s in ex_sr.values()], ddof=1))

    gates = {}
    detail = {}
    for k, r in results.items():
        g = {}
        g["G1"] = beats(r["full"], B["full"])
        segwins = {s: beats(r[s], B[s]) for s in ("A", "B", "C")}
        g["G2"] = sum(segwins.values()) >= 2 and segwins["C"]
        res2 = st.run(r["target"], mult=2.0)
        b2 = stats(st.bench(mult=2.0))
        s2 = stats(res2["equity"])
        g["G3"] = beats(s2, b2)
        nb = neighbors(r["params"])
        nb_wins = []
        for p in nb:
            rr = evaluate(st, k, p)
            nb_wins.append(beats(rr["full"], B["full"]))
        g["G4"] = (np.mean(nb_wins) >= 0.7) if nb_wins else False
        g["G5"] = (r["full"]["mdd"] >= B["full"]["mdd"] - 0.05) and (r["full"]["vol"] <= 1.1 * B["full"]["vol"])
        me_days = core.index[month_end_mask(core.index).values]
        trade_days = pd.DatetimeIndex([core.index[i + 1] for i in range(len(core.index) - 1) if core.index[i] in set(me_days)])
        static_t = pd.Series(r["avg_exposure"], index=core.index)
        static = stats(st.run(static_t, trade_days=trade_days, band=0.02)["equity"])
        g["G6"] = r["full"]["sharpe"] > static["sharpe"]
        sret = r["result"]["equity"].pct_change().dropna()
        p = block_bootstrap_p(sret, bret)
        g["G7"] = p <= 0.20
        dsr6 = deflated_sharpe(ex_sr[k], 6, sr_var)["dsr"]
        dsr61 = deflated_sharpe(ex_sr[k], PRIOR_TRIALS + 6, sr_var)["dsr"]
        # 警示
        eq = r["result"]["equity"]
        roll_wins = []
        for y0 in range(eq.index[0].year + 1, st.last.year - 4):
            a0, b0 = f"{y0}-01-01", f"{y0 + 4}-12-31"
            roll_wins.append(beats(stats(eq.loc[a0:b0]), stats(bench_eq.loc[a0:b0])))
        ys, yb = yearly(eq), yearly(bench_eq)
        best = (ys - yb).idxmax()
        ex_eq = (1 + ys.drop(best)).cumprod()
        ex_b = (1 + yb.drop(best)).cumprod()
        no_best = (ex_eq.iloc[-1] > ex_b.iloc[-1])
        shift = []
        for m in (-6, 6):
            st0 = (pd.Timestamp(FULL_START) + pd.DateOffset(months=m)).strftime("%Y-%m-%d")
            shift.append(beats(stats(eq.loc[st0:]), stats(bench_eq.loc[st0:])))
        dep = stats(st.run(r["target"], cash="deposit")["equity"])
        gates[k] = g
        detail[k] = {"segments": segwins, "cost2": s2, "bench_cost2": b2, "neighbors": len(nb),
                     "neighbor_win_rate": float(np.mean(nb_wins)) if nb_wins else None, "static": static,
                     "p_boot": p, "dsr_6": dsr6, "dsr_61": dsr61,
                     "rolling5y_win_rate": float(np.mean(roll_wins)) if roll_wins else None,
                     "wins_without_best_year": bool(no_best), "best_year": int(best.year),
                     "start_shift_ok": all(shift), "deposit_cash": dep,
                     "yearly": ys, "bench_yearly": yb}

    passed = chosen is not None and all(gates[chosen].values())
    out = {"bench": B, "results": {k: {kk: vv for kk, vv in r.items() if kk not in ("target", "result")} for k, r in results.items()},
           "eligible_in_sample": eligible, "chosen": chosen, "gates": gates, "passed": passed, "track": track,
           "core_source": d["core_source"], "clean_notes": d.get("clean_notes", []), "data_start": str(core.index[0].date()), "data_end": str(core.index[-1].date())}
    if demo:
        print(json.dumps({"chosen": chosen, "eligible": eligible, "gates": gates, "passed": passed}, default=str, indent=1))
        return out
    write_outputs(out, detail, log, results, st)
    return out


# ── 報告 ─────────────────────────────────────────────────────────────────────
def pct(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.1f}%"


def f2(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.2f}"


def write_outputs(out, detail, log, results, st):
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    # 試驗紀錄
    tl = rep / "trials_log.csv"
    df = pd.DataFrame(log)
    df["round"] = "overlay-2026-11-02"
    if tl.exists():
        old = pd.read_csv(tl)
        old = old[old.get("round", pd.Series(dtype=str)).astype(str) != "overlay-2026-11-02"] if "round" in old else old
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(tl, index=False)

    # 目前（最新一天）的目標曝險，供 App 顯示
    cur = {}
    for k, r in results.items():
        t = r["target"].dropna()
        cur[k] = {"date": str(t.index[-1].date()), "target_exposure": float(t.iloc[-1])}
    out["current_targets"] = cur
    (rep / "overlay_results.json").write_text(json.dumps(
        {**{k: v for k, v in out.items()}, "detail": {k: {kk: vv for kk, vv in d.items() if kk not in ("yearly", "bench_yearly")}
                                                         for k, d in detail.items()}},
        default=lambda o: o.item() if hasattr(o, "item") else str(o), ensure_ascii=False, indent=1), encoding="utf-8")

    B = out["bench"]
    L = []
    L.append("# 第二輪：0050 曝險調整策略能否同時贏 0050（報酬 + Sharpe）\n")
    L.append(f"資料：0050 {out['data_start']} ～ {out['data_end']}（{out['core_source']}）；規格 `quant/overlay_spec.json` 先登錄後跑。\n")
    L.append("> ⚠️ 研究紀錄，非投資建議。回測不保證未來獲利；下單由使用者本人決定。\n")
    if out.get("clean_notes"):
        L.append("資料清理（ETF 單日漲跌 > 15% 視為資料斷點）：" + "；".join(out["clean_notes"]) + "\n")
    ch = out["chosen"]
    if out["passed"]:
        L.append(f"**結論：{ch} 通過全部 7 道硬門檻 → 判定「回測通過、前瞻驗證中」。**\n")
    elif ch:
        failed = [g for g, v in out["gates"][ch].items() if not v]
        L.append(f"**結論：樣本內選出 {ch}，但未通過硬門檻 {', '.join(failed)} → 本輪判定失敗，不上線。**\n")
    else:
        L.append("**結論：沒有任何候選在樣本內同時贏 0050 → 本輪判定失敗，不上線。**\n")
    L.append("## 全期與分段（全部扣成本，現金 0%）\n")
    L.append("| 策略 | 全期年化 | 全期 Sharpe | 全期 MDD | 波動 | A 段 年化/Sharpe | B 段 | C 段（樣本外） | 平均曝險 | 年交易次數 |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    def row(name, r):
        return (f"| {name} | {pct(r['full']['cagr'])} | {f2(r['full']['sharpe'])} | {pct(r['full']['mdd'])} | {pct(r['full']['vol'])} | "
                f"{pct(r['A']['cagr'])} / {f2(r['A']['sharpe'])} | {pct(r['B']['cagr'])} / {f2(r['B']['sharpe'])} | "
                f"{pct(r['C']['cagr'])} / {f2(r['C']['sharpe'])} |")
    for c in SPEC["candidates"]:
        r = out["results"][c["id"]]
        L.append(row(f"{c['id']} {c['name']}", r) + f" {r['avg_exposure']:.2f} | {r['trades_per_year']:.1f} |")
    L.append(row("0050 買進持有", B) + " 1.00 | 0 |")
    L.append("")
    L.append(f"樣本內（2003-07～2014-10）同時贏 0050 的候選：{', '.join(out['eligible_in_sample']) or '無'}；依規則選出：**{ch or '無'}**。\n")
    L.append("## 硬門檻（每個候選都列出，但只有選出者算數）\n")
    L.append("| 策略 | G1 全期 | G2 分段 | G3 成本×2 | G4 參數鄰近 | G5 回撤/波動 | G6 贏靜態混合 | G7 bootstrap p≤0.2 |")
    L.append("|---|---|---|---|---|---|---|---|")
    ok = lambda v: "✅" if v else "❌"
    for k, g in out["gates"].items():
        dd = detail[k]
        L.append(f"| {k} | {ok(g['G1'])} | {ok(g['G2'])} ({''.join(s for s, v in dd['segments'].items() if v) or '-'}) | {ok(g['G3'])} | "
                 f"{ok(g['G4'])} ({pct(dd['neighbor_win_rate'])}) | {ok(g['G5'])} | {ok(g['G6'])} (靜態 {f2(dd['static']['sharpe'])}) | "
                 f"{ok(g['G7'])} (p={f2(dd['p_boot'])}) |")
    L.append("")
    L.append("## 警示指標（揭露，不否決）\n")
    L.append("| 策略 | DSR N=6 | DSR N=61 | 滾動 5 年勝率 | 去掉最好一年仍贏 | 起點 ±6 月穩定 | 現金計定存：年化/Sharpe |")
    L.append("|---|---:|---:|---:|---|---|---:|")
    for k, dd in detail.items():
        L.append(f"| {k} | {f2(dd['dsr_6'])} | {f2(dd['dsr_61'])} | {pct(dd['rolling5y_win_rate'])} | "
                 f"{ok(dd['wins_without_best_year'])}（最好 {dd['best_year']}） | {ok(dd['start_shift_ok'])} | "
                 f"{pct(dd['deposit_cash']['cagr'])} / {f2(dd['deposit_cash']['sharpe'])} |")
    L.append("")
    if out["track"]:
        t = out["track"]
        L.append("## 合成 00631L 校驗\n")
        L.append(f"重疊 {t['years']:.1f} 年：實際年化 {pct(t['actual_cagr'])}、合成 {pct(t['synthetic_cagr'])}，"
                 f"差 {pct(t['annual_diff'])}／年；追蹤誤差 {pct(t['tracking_error'])}；單日 >25% 跳動 {t['big_jumps']} 次（分割未還原的跡象）。\n")
    if ch:
        dd = detail[ch]
        L.append(f"## {ch} 逐年報酬\n")
        L.append("| 年 | 策略 | 0050 | 差 |")
        L.append("|---|---:|---:|---:|")
        for y in dd["yearly"].index:
            a = dd["yearly"].loc[y]
            b = dd["bench_yearly"].get(y, np.nan)
            L.append(f"| {y.year} | {pct(a)} | {pct(b)} | {pct(a - b)} |")
        L.append("")
    L.append("## 目前目標曝險（最新收盤）\n")
    for k, v in cur.items():
        L.append(f"- {k}：{v['target_exposure']:.2f}（{v['date']}）")
    L.append("\n---\n_由 `python -m quant.overlay_study` 產生。研究紀錄，非投資建議。_")
    (rep / "overlay_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    main(demo=a.demo)
