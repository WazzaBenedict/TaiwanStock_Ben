"""每日選股 + 進出場規則（波段）回測引擎。

時序（每個交易日 d）：
1. d+1 開盤：先賣後買（訊號都是 d 收盤後算的）。
   - 賣：開盤價成交；開盤跌停（以前收比較，2015-06-01 前 ±7%、之後 ±10%）賣不掉 → 順延。
   - 買：開盤 > d 收盤 × (1 + max_chase) 不買（不追高）；開盤漲停買不到。
   - 空槽（沒有持股的資金）放 0050（idle="0050"）或現金（idle="cash"）。
2. d 收盤：更新持股市值、最高收盤。
3. d 收盤後：出場檢查（停損 / 吊燈移動停利 / 時間 / 自訂出場），再選股排出明日買進順位。
4. 停損、吊燈都用還原價（同一序列），避免除息造成假停損。只有 open/close：停損以收盤觸發、
   隔日開盤出場（跳空穿越就是開盤價），不假設盤中能成交在停損價。

App 顯示（today_signals）：明日進場上限價、初始停損價、吊燈出場價（隨最高收盤上移）、時間停損日。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .costs import TaiwanCosts, tiered_slippage

ETF_FEE = 0.001425
ETF_TAX = 0.001
ETF_SLIP = 0.0005


@dataclass
class SwingConfig:
    name: str
    score_fn: Callable | None                  # (ctx, d) -> pd.Series：有分數 = 合格，越高越好
    max_positions: int = 10
    max_chase: float = 0.02                    # 開盤 > 今日收盤 × 1.02 不買；S5 用 0.0
    stop_atr: float | None = 2.0               # 初始停損 = 進場價 − stop_atr × ATRc
    trail_atr: float | None = 3.0              # 吊燈 = 最高收盤 − trail_atr × ATRc
    max_hold: int | None = None                # 持有滿 N 日出場
    time_stop_if_loss: int | None = None       # 持有滿 N 日且虧損才出場（S1）
    exit_fn: Callable | None = None            # (ctx, d, sid, pos) -> 出場理由 or None
    regime: bool = True                        # 0050 < 200 日均線時不開新倉（不強制出場）
    idle: str = "0050"                         # 空槽資金放 0050 或 "cash"
    min_avg_value: float = 1e8
    capital: float = 1_000_000.0
    cost_mult: float = 1.0
    start: str | None = None
    end: str | None = None
    random_seed: int | None = None             # 隨機對照：從同一合格池（同樣的候選數）隨機排序
    blocked: dict = field(default_factory=dict)  # {(sid, 進場日): 出場日}：H4「錯過最好的交易」，槽位空著放 0050
    distress_haircut: float = 0.5              # 下市前 20 日跌 > 50% 的下市股，出場價再打折（破產/全額交割的保守處理）
    costs: TaiwanCosts = field(default_factory=TaiwanCosts)


def limit_pct(d: pd.Timestamp) -> float:
    return 0.10 if d >= pd.Timestamp("2015-06-01") else 0.07


class Context:
    """預先算好的共用序列（一次計算，多個系統共用）。"""

    def __init__(self, panel: dict):
        self.panel = panel
        self.close = panel["close"]
        self.open = panel["open"]
        self.value = panel["volume_value"]
        self.cal = self.close.index
        self.atr = self.close.diff().abs().rolling(20, min_periods=15).mean()     # ATRc（收盤版 ATR）
        self.avg_value20 = self.value.rolling(20, min_periods=14).mean()
        from .overlay import clean_etf
        bdf = clean_etf(pd.DataFrame({"open": panel["benchmark_open"], "close": panel["benchmark_close"]}).dropna())
        self.bench_notes = bdf.attrs.get("clean_notes", [])
        bdf = bdf.reindex(self.cal).ffill()
        b, bo = bdf["close"], bdf["open"]
        self.bclose, self.bopen = b, bo
        self.regime_on = (b > b.rolling(200).mean()).fillna(False)
        self.last_valid = self.close.apply(lambda s: s.last_valid_index())
        self._cache: dict = {}

    def cached(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def open_limit(self, sid: str, d, prev) -> tuple[bool, bool]:
        """(開盤漲停, 開盤跌停)。漲跌幅比率在同一還原係數下與未還原價相同；除權息日略有誤差，容忍 0.5%。"""
        pc = self.close.at[prev, sid]
        po = self.open.at[d, sid]
        if pd.isna(pc) or pd.isna(po) or pc <= 0:
            return False, False
        chg = po / pc - 1
        lim = limit_pct(d)
        return chg >= lim - 0.005, chg <= -lim + 0.005


def _slip(ctx, sid, d) -> float:
    v = ctx.avg_value20.at[d, sid] if sid in ctx.avg_value20.columns else np.nan
    return tiered_slippage(float(v) if pd.notna(v) else 0.0)


def run_swing(ctx: Context, cfg: SwingConfig) -> dict:
    close, open_, cal = ctx.close, ctx.open, ctx.cal
    days = cal
    if cfg.start:
        days = days[days >= pd.Timestamp(cfg.start)]
    if cfg.end:
        days = days[days <= pd.Timestamp(cfg.end)]
    costs, K, m = cfg.costs, cfg.capital, cfg.cost_mult
    rng = np.random.default_rng(cfg.random_seed) if cfg.random_seed is not None else None
    use_etf = cfg.idle == "0050"
    etf_buy = (ETF_FEE + ETF_SLIP) * m
    etf_sell = (ETF_FEE + ETF_TAX + ETF_SLIP) * m

    cash, etf = 1.0, 0.0                 # 以 NAV 單位表示的現金與 0050 部位
    pos: dict[str, dict] = {}
    to_sell: dict[str, str] = {}
    to_buy: list[str] = []
    eq, trades = [], []
    phantom: list = []
    skip_chase = skip_limit = 0
    tot_cost = 0.0
    prev = None

    def distressed(sid):
        lv = ctx.last_valid.get(sid)
        if lv is None:
            return False
        s_ = close[sid].loc[:lv].dropna()
        return len(s_) > 20 and s_.iloc[-1] / s_.iloc[-21] < 0.5

    def stock_cost(amount, side, sid, d):
        return costs.order_cost(amount * K, side, slippage=_slip(ctx, sid, d)) / K * m

    for n, d in enumerate(days):
        i = cal.get_loc(d)
        prev = cal[i - 1] if i > 0 else None
        # 隔夜：昨收 → 今開
        if prev is not None:
            if use_etf and etf > 0:
                etf *= ctx.bopen.at[d] / ctx.bclose.at[prev]
            for sid, p in pos.items():
                o = open_.at[d, sid]
                if pd.notna(o) and p["last"] > 0:
                    p["val"] *= o / p["last"]
                    p["last"] = o
        if n == 0 and use_etf:
            c0 = etf_buy * cash
            etf, cash = cash - c0, 0.0
            tot_cost += c0
        # 賣
        for sid, why in list(to_sell.items()):
            p = pos.get(sid)
            if p is None:
                to_sell.pop(sid)
                continue
            o = open_.at[d, sid]
            if pd.isna(o):
                lv = ctx.last_valid.get(sid)
                if lv is None or d <= lv:
                    continue           # 暫停交易，順延
                why = "delist"
            elif prev is not None and ctx.open_limit(sid, d, prev)[1]:
                continue
            c = stock_cost(p["val"], "sell", sid, d) + (p["val"] * 0.005 * m if why == "delist" else 0.0)
            if why == "delist" and distressed(sid):
                c += (p["val"] - c) * cfg.distress_haircut
            cash += p["val"] - c
            tot_cost += c
            trades.append({"sid": sid, "entry_day": p["entry_day"], "exit_day": d, "days": p["held"],
                           "ret": (p["val"] - c) / p["basis"] - 1, "reason": why})
            pos.pop(sid)
            to_sell.pop(sid)
        # 買
        phantom[:] = [(s_, e) for s_, e in phantom if d < e]
        nav = cash + etf + sum(p["val"] for p in pos.values())
        free = cfg.max_positions - len(pos) - len(phantom)
        for sid, cap_px in to_buy:
            if free <= 0:
                break
            o = open_.at[d, sid]
            if pd.isna(o) or sid in pos or any(s_ == sid and d < e for s_, e in phantom):
                continue
            if (sid, d) in cfg.blocked and o <= cap_px and not ctx.open_limit(sid, d, prev)[0]:
                phantom.append((sid, cfg.blocked[(sid, d)]))   # 假裝錯過：槽位被佔、資金留在 0050
                free -= 1
                continue
            if o > cap_px:
                skip_chase += 1
                continue
            if ctx.open_limit(sid, d, prev)[0]:
                skip_limit += 1
                continue
            alloc = nav / cfg.max_positions
            if cash < alloc and use_etf:          # 從 0050 調資金
                need = min(alloc - cash, etf)
                c = need * etf_sell
                etf -= need
                cash += need - c
                tot_cost += c
            alloc = min(alloc, cash)
            if alloc < nav * 0.01:
                break
            c = stock_cost(alloc, "buy", sid, d)
            cash -= alloc
            tot_cost += c
            a = ctx.atr.at[prev, sid]
            a = float(a) if pd.notna(a) and a > 0 else o * 0.02
            pos[sid] = {"val": alloc - c, "basis": alloc, "last": o, "entry": o, "entry_day": d, "peak": o,
                        "atr": a, "held": 0}
            free -= 1
        to_buy = []
        # 剩餘現金回到 0050
        if use_etf and cash > 1e-9:
            c = cash * etf_buy
            etf += cash - c
            tot_cost += c
            cash = 0.0
        # 盤中：今開 → 今收
        if use_etf and etf > 0:
            etf *= ctx.bclose.at[d] / ctx.bopen.at[d]
        for sid, p in pos.items():
            c_ = close.at[d, sid]
            if pd.notna(c_) and p["last"] > 0:
                p["val"] *= c_ / p["last"]
                p["last"] = c_
                p["peak"] = max(p["peak"], c_)
            p["held"] += 1
        eq.append(cash + etf + sum(p["val"] for p in pos.values()))
        if i + 1 >= len(cal):
            continue
        # 收盤後：出場檢查
        for sid, p in pos.items():
            if sid in to_sell:
                continue
            c_ = close.at[d, sid]
            why = None
            lv = ctx.last_valid.get(sid)
            if lv is not None and d >= lv:
                why = "delist"
            elif pd.notna(c_):
                if cfg.stop_atr is not None and c_ <= p["entry"] - cfg.stop_atr * p["atr"]:
                    why = "stop"
                elif cfg.trail_atr is not None and c_ <= p["peak"] - cfg.trail_atr * p["atr"]:
                    why = "trail"
                elif cfg.max_hold is not None and p["held"] >= cfg.max_hold:
                    why = "time"
                elif cfg.time_stop_if_loss is not None and p["held"] >= cfg.time_stop_if_loss and c_ < p["entry"]:
                    why = "time_loss"
                elif cfg.exit_fn is not None:
                    why = cfg.exit_fn(ctx, d, sid, p)
            if why:
                to_sell[sid] = why
        # 收盤後：選股
        free = cfg.max_positions - len(pos) + len(to_sell) - len(phantom)
        if free > 0 and (not cfg.regime or bool(ctx.regime_on.at[d])):
            score = cfg.score_fn(ctx, d) if cfg.score_fn is not None else pd.Series(dtype=float)
            liq = ctx.avg_value20.loc[d]
            ok = liq[liq >= cfg.min_avg_value].index.difference(list(pos))
            if rng is not None:
                k = int(score.reindex(ok).notna().sum())
                pool = ok[close.loc[d].reindex(ok).notna().values]
                if k and len(pool):
                    pick = rng.choice(len(pool), size=min(k, len(pool)), replace=False)
                    score = pd.Series(rng.random(len(pick)), index=pool[pick])
                else:
                    score = pd.Series(dtype=float)
            else:
                score = score.reindex(ok).dropna()
            if len(score):
                score = score.sort_index().sort_values(ascending=False, kind="mergesort")
                to_buy = [(s, close.at[d, s] * (1 + cfg.max_chase)) for s in score.index[: free * 3]]
    return {"equity": pd.Series(eq, index=days), "trades": pd.DataFrame(trades), "skip_chase": skip_chase,
            "skip_limit": skip_limit, "total_cost": tot_cost}


# ── 系統定義（事前登錄，見 quant/swing_spec.json）───────────────────────────────
def _rolling(ctx, name, fn):
    return ctx.cached(name, fn)


def score_52w_high(ctx, d):
    """S1：收盤 ≥ 252 日最高收盤 × 0.95 且 > 200 日均線；依 收盤/52 週高 排序，次排序 12-1 動能。"""
    c = ctx.close
    hi = _rolling(ctx, "hi252", lambda: c.rolling(252, min_periods=240).max())
    ma200 = _rolling(ctx, "ma200", lambda: c.rolling(200, min_periods=190).mean())
    mom = _rolling(ctx, "mom12_1", lambda: c.shift(21) / c.shift(252) - 1)
    x = c.loc[d] / hi.loc[d]
    ok = (x >= 0.95) & (c.loc[d] > ma200.loc[d])
    return (x + mom.loc[d].fillna(0) * 1e-6)[ok]


def revenue_daily(ctx):
    """每個交易日可用的最新月營收（M 月營收在 M+1 月 11 日起可用），回傳 (營收創 12 月新高, 近 3 月年增)。"""
    def build():
        rev = ctx.panel["revenue"].sort_index()
        hi12 = rev.rolling(12, min_periods=12).max()
        new_high = rev >= hi12
        r3 = rev.rolling(3, min_periods=3).sum()
        yoy3 = r3 / r3.shift(12) - 1
        avail = [m + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10) for m in rev.index]
        nh = pd.DataFrame(new_high.values, index=avail, columns=rev.columns).astype(float)
        yy = pd.DataFrame(yoy3.values, index=avail, columns=rev.columns)
        nh = nh.reindex(ctx.cal.union(nh.index)).ffill(limit=None).reindex(ctx.cal)
        yy = yy.reindex(ctx.cal.union(yy.index)).ffill().reindex(ctx.cal)
        # 超過 2 個月沒有新營收就視為缺值
        last = pd.Series(avail, index=avail)
        stamp = last.reindex(ctx.cal.union(last.index)).ffill().reindex(ctx.cal)
        stale = (ctx.cal.to_series() - stamp).dt.days > 75
        nh[stale.values] = np.nan
        yy[stale.values] = np.nan
        return nh.reindex(columns=ctx.close.columns), yy.reindex(columns=ctx.close.columns)
    return ctx.cached("revenue_daily", build)


def score_revenue(ctx, d):
    """S3：最新月營收創 12 個月新高、近 3 月年增 > 0、收盤 > 60 日均線；依近 3 月年增排序。"""
    nh, yy = revenue_daily(ctx)
    c = ctx.close
    ma60 = _rolling(ctx, "ma60", lambda: c.rolling(60, min_periods=55).mean())
    ok = (nh.loc[d] == 1) & (yy.loc[d] > 0) & (c.loc[d] > ma60.loc[d])
    return yy.loc[d][ok]


def exit_revenue(ctx, d, sid, p):
    _, yy = revenue_daily(ctx)
    v = yy.at[d, sid]
    return "rev_yoy<0" if pd.notna(v) and v < 0 else None


def score_turtle(ctx, d):
    """S4：收盤 > 前 20 日最高收盤；依 120 日報酬排序。"""
    c = ctx.close
    hi20 = _rolling(ctx, "hi20_prev", lambda: c.shift(1).rolling(20, min_periods=20).max())
    r120 = _rolling(ctx, "r120", lambda: c / c.shift(120) - 1)
    ok = c.loc[d] > hi20.loc[d]
    return r120.loc[d][ok]


def exit_turtle(ctx, d, sid, p):
    c = ctx.close
    lo10 = _rolling(ctx, "lo10_prev", lambda: c.shift(1).rolling(10, min_periods=10).min())
    v, lo = c.at[d, sid], lo10.at[d, sid]
    return "10d_low" if pd.notna(v) and pd.notna(lo) and v < lo else None


def _rsi2(ctx):
    def build():
        dlt = ctx.close.diff()
        up = dlt.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
        dn = (-dlt.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
        return 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return ctx.cached("rsi2", build)


def score_rsi2(ctx, d):
    """S5：收盤 > 200 日均線且 RSI(2) < 10；RSI 越低越優先。"""
    c = ctx.close
    ma200 = _rolling(ctx, "ma200", lambda: c.rolling(200, min_periods=190).mean())
    r = _rsi2(ctx).loc[d]
    ok = (c.loc[d] > ma200.loc[d]) & (r < 10)
    return (-r)[ok]


def exit_rsi2(ctx, d, sid, p):
    c = ctx.close
    ma5 = _rolling(ctx, "ma5", lambda: c.rolling(5).mean())
    v = c.at[d, sid]
    return "above_ma5" if pd.notna(v) and v > ma5.at[d, sid] else None


def systems() -> dict[str, dict]:
    """事前登錄的系統（S2 Clenow 需排名出場與週調整，此引擎不支援，未測，見 spec）。"""
    return {
        "S1": dict(score_fn=score_52w_high, max_positions=10, time_stop_if_loss=60),
        "S3": dict(score_fn=score_revenue, max_positions=10, exit_fn=exit_revenue),
        "S4": dict(score_fn=score_turtle, max_positions=10, exit_fn=exit_turtle, trail_atr=None),
        "S5": dict(score_fn=score_rsi2, max_positions=10, max_chase=0.0, stop_atr=None, trail_atr=None,
                   max_hold=10, exit_fn=exit_rsi2),
    }


def blend_with_core(sat: pd.Series, core: pd.Series, w_core: float = 0.6) -> pd.Series:
    """S6：w_core 固定 0050 + (1−w_core) 衛星，每月第一個交易日再平衡（再平衡成本以 0.3% × 調整量估）。"""
    rs, rc = sat.pct_change().fillna(0), core.pct_change().fillna(0)
    nav, a, b = 1.0, w_core, 1 - w_core
    out = []
    month = None
    for d in rs.index:
        if month is not None and d.month != month:
            tot = a + b
            shift = abs(a / tot - w_core)
            nav *= 1 - shift * 0.009    # 兩邊都要交易：賣/買個股（含 0.3% 稅與滑價）+ 買/賣 0050
            a, b = w_core * nav, (1 - w_core) * nav
        month = d.month
        a *= 1 + rc.at[d]
        b *= 1 + rs.at[d]
        nav = a + b
        out.append(nav)
    return pd.Series(out, index=rs.index)
