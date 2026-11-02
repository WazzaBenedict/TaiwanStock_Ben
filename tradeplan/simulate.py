"""把交易計畫規則套到歷史日 K，逐日模擬（不偷看未來）。

成交假設（保守）：
- 第 t 天收盤出現條件 → 第 t+1 ~ t+3 天掛限價買。開盤低於限價以開盤價成交；
  盤中最低價「低於」限價（不是碰到）才以限價成交；一字漲停鎖死不成交。
- 停損與目標同一天都碰到 → 當作先停損。開盤跳空穿過停損/目標 → 以開盤價成交。
- 進場當天只檢查停損，不算目標。
- 一字跌停鎖死當天賣不掉，順延到下一個交易日。
- 保本與移動停利以當天收盤與 ATR 計算，下一個交易日才生效。
- 同一檔一次只持有一筆，不重疊。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .costs import Costs
from .rules import PlanRules, atr14, levels_at


def _locked(o, h, l, c, prev_c, up: bool) -> bool:
    if prev_c is None or not prev_c or h != l:
        return False
    return c >= prev_c * 1.095 if up else c <= prev_c * 0.905


def simulate(df: pd.DataFrame, setup: pd.Series, rules: PlanRules = PlanRules(),
             costs: Costs = Costs(), etf: bool = False) -> list[dict]:
    if df is None or len(df) < 30:
        return []
    df = df.reset_index(drop=True).copy()
    for col in ("開盤價", "最高價", "最低價"):          # 缺值以收盤價補，避免 NaN 比較靜默失效
        df[col] = df[col].fillna(df["收盤價"])
    setup = pd.Series(setup).reset_index(drop=True).fillna(False).astype(bool)
    o = df["開盤價"].astype(float).values
    h = df["最高價"].astype(float).values
    l = df["最低價"].astype(float).values
    c = df["收盤價"].astype(float).values
    dates = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d").values
    atr = atr14(df).values
    ma5 = df["收盤價"].rolling(5).mean().values
    n = len(df)
    ck = (costs, etf)   # 成本依每筆成交價算（1 張，含最低手續費）

    trades: list[dict] = []
    order = None   # {"lv":..., "expire": idx}
    pos = None
    for d in range(1, n):
        prev_c = c[d - 1]
        # ── 持倉：檢查出場 ──
        if pos is not None:
            exit_px = reason = None
            if not _locked(o[d], h[d], l[d], c[d], prev_c, up=False):
                stop = pos["stop"]
                if o[d] <= stop:
                    exit_px, reason = o[d], pos["stop_kind"]
                elif l[d] <= stop:
                    exit_px, reason = stop, pos["stop_kind"]
                elif o[d] >= pos["target"]:
                    exit_px, reason = o[d], "目標"
                elif h[d] >= pos["target"]:
                    exit_px, reason = pos["target"], "目標"
                elif d - pos["i"] + 1 >= rules.max_hold_days:
                    exit_px, reason = c[d], "時間出場"
            if exit_px is not None:
                trades.append(_close(pos, d, exit_px, reason, dates, ck))
                pos = None
            else:
                _update_stop(pos, c[d], atr[d], rules)
            continue
        # ── 有掛單：檢查成交 ──
        if order is not None:
            lv = order["lv"]
            fill = None
            if o[d] <= lv["stop"]:                 # 開盤已低於停損：計畫失效，取消不買
                order = None
            elif not _locked(o[d], h[d], l[d], c[d], prev_c, up=True):
                if o[d] < lv["entry"]:
                    fill = o[d]
                elif l[d] < lv["entry"]:
                    fill = lv["entry"]
            if fill is not None:
                pos = {"i": d, "fill": fill, "stop": lv["stop"], "stop0": lv["stop"],
                       "target": lv["target"], "r": lv["entry"] - lv["stop"], "entry": lv["entry"],
                       "be": False, "hi_close": c[d], "stop_kind": "停損", "setup_date": order["date"]}
                if l[d] <= pos["stop"]:          # 進場當天就跌破停損
                    trades.append(_close(pos, d, min(pos["stop"], fill), "停損", dates, ck))
                    pos = None
                else:
                    _update_stop(pos, c[d], atr[d], rules)
                order = None
                continue
            if order is not None and d >= order["expire"]:
                order = None
        # ── 沒單：第 d 天收盤是否出現條件（明天起掛單）──
        if order is None and pos is None and setup.iloc[d]:
            lv = levels_at(c[d], _nz(ma5[d]), _nz(atr[d]), rules, etf)
            if lv:
                order = {"lv": lv, "expire": d + rules.entry_valid_days, "date": dates[d]}
    return trades


def _update_stop(pos: dict, close: float, atr: float, rules: PlanRules) -> None:
    pos["hi_close"] = max(pos["hi_close"], close)
    if not pos["be"] and close >= pos["entry"] + rules.breakeven_r * pos["r"]:
        pos["be"] = True
    if pos["be"]:
        new = pos["entry"]
        if atr and np.isfinite(atr):
            new = max(new, pos["hi_close"] - rules.trail_atr * atr)
        if new > pos["stop"]:
            pos["stop"] = new
            pos["stop_kind"] = "保本出場" if new <= pos["entry"] + 1e-9 else "移動停利"


def _close(pos, d, px, reason, dates, ck) -> dict:
    costs, etf = ck
    cost_in = pos["fill"] * (1 + costs.buy_rate(float(pos["fill"])))
    proceeds = px * (1 - costs.sell_rate(etf, float(px)))
    risk = max(pos["fill"] - pos["stop0"], 1e-9)
    return {"setup_date": pos["setup_date"], "entry_date": dates[pos["i"]], "exit_date": dates[d],
            "entry": round(float(pos["fill"]), 2), "exit": round(float(px), 2),
            "stop0": round(float(pos["stop0"]), 2), "target": round(float(pos["target"]), 2),
            "days": int(d - pos["i"] + 1), "reason": reason,
            "ret": proceeds / cost_in - 1, "r_mult": (proceeds - cost_in) / risk}


def _nz(x):
    return float(x) if x is not None and np.isfinite(x) else None


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "sample_ok": False}
    rets = np.array([t["ret"] for t in trades])
    rs = np.array([t["r_mult"] for t in trades])
    wins = rets > 0
    gp, gl = rets[wins].sum(), -rets[~wins].sum()
    streak = worst = 0
    for w in wins:
        streak = 0 if w else streak + 1
        worst = max(worst, streak)
    ci = None
    if n >= 10:
        boot = np.random.default_rng(11).choice(rets, size=(2000, n), replace=True).mean(axis=1)
        ci = [round(float(np.percentile(boot, 2.5)) * 100, 2), round(float(np.percentile(boot, 97.5)) * 100, 2)]
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return {
        "n": n, "sample_ok": n >= 30,
        "win_rate": round(float(wins.mean()) * 100, 1),
        "avg_ret_pct": round(float(rets.mean()) * 100, 2),
        "avg_ret_ci95_pct": ci,
        "avg_r": round(float(rs.mean()), 2),
        "profit_factor": round(float(gp / gl), 2) if gl > 0 else None,
        "max_consec_losses": int(worst),
        "avg_days": round(float(np.mean([t["days"] for t in trades])), 1),
        "total_ret_pct": round((float(np.prod(1 + rets)) - 1) * 100, 1),
        "exit_reasons": reasons,
        "first_date": trades[0]["entry_date"], "last_date": trades[-1]["exit_date"],
        "days_held": int(sum(t["days"] for t in trades)),
    }


def random_entry_control(df: pd.DataFrame, n_trades: int, rules: PlanRules = PlanRules(),
                         costs: Costs = Costs(), etf: bool = False, runs: int = 200,
                         seed: int = 7, start: int = 60, rule_avg: float | None = None) -> dict:
    """隨機挑與規則「實際成交筆數」一樣多的進場日、同一段期間（第 start 根起）、同一套出場規則，
    當作「沒有選股能力」的對照組。"""
    if df is None or len(df) < start + 10 or n_trades <= 0:
        return {"runs": 0}
    rng = np.random.default_rng(seed)
    eligible = np.arange(start, len(df) - 1)
    k = min(n_trades, len(eligible))
    means, counts = [], []
    for _ in range(runs):
        mask = np.zeros(len(df), dtype=bool)
        mask[rng.choice(eligible, size=k, replace=False)] = True
        tr = simulate(df, pd.Series(mask), rules, costs, etf)
        if tr:
            means.append(float(np.mean([t["ret"] for t in tr])))
            counts.append(len(tr))
    if not means:
        return {"runs": 0}
    out_p = None
    if rule_avg is not None:   # 經驗 p 值：隨機進場平均 ≥ 規則平均的比例
        out_p = round((1 + sum(m >= rule_avg for m in means)) / (len(means) + 1), 3)
    return {"runs": len(means), "avg_n": round(float(np.mean(counts)), 1), "p_value": out_p,
            "avg_ret_pct": round(float(np.mean(means)) * 100, 2),
            "p10_pct": round(float(np.percentile(means, 10)) * 100, 2),
            "p90_pct": round(float(np.percentile(means, 90)) * 100, 2)}
