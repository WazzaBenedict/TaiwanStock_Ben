"""台股時光機 (Taiwan Time Machine): replay a day-trade plan 10,000 times, after costs.

Method adapted from `trader-timemachine` in Jake Schincariol's day-trader-skill
(https://github.com/Jakeschincariol/day-trader-skill, MIT License, Copyright (c) 2026
Jake Schincariol). This is a re-implementation for Taiwan stocks, not a copy:

- Session 09:00-13:30 Asia/Taipei, 54 five-minute bars (last bar = closing auction).
- Long only (現股當沖 先買後賣).
- Every replay and every historical trade is charged commission (min NT$20), the 0.15%
  day-trade sell tax and tick-based slippage, so the odds are NET of costs.
- Data: FinMind TaiwanStockKBar 1-minute bars, aggregated to 5 minutes.

How a replay works: the pool is the stock's own full sessions before the plan date.
Each bar is stored as four ratios to the previous bar's close. From the entry bar to
the exit bar, every step draws a past bar from the same time of day (+/- `window`
bars), scales it to the current price, and checks the stop first, then the target
(a bar touching both counts as the stop). The history section re-runs the same rule
on every past session: that part is what really happened, not a simulation.

It is a simulation built from recent bars, not a prediction. Most retail day traders
lose money, and a good-looking replay does not change that.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import asdict, dataclass, field

try:  # package import (app) or script run
    from .costs import DayTradeCosts, round_to_tick, tick_size
    from .data import SESSION_BARS, LAST_SOURCE, bar_time, parse_hhmm, load_sessions, load_offline, DataError
except ImportError:  # pragma: no cover
    from costs import DayTradeCosts, round_to_tick, tick_size  # type: ignore
    from data import SESSION_BARS, LAST_SOURCE, bar_time, parse_hhmm, load_sessions, load_offline, DataError  # type: ignore

DEFAULT_SEED = 19
MIN_POOL = 20
LAST_ENTRY_BAR = parse_hhmm("13:00")   # no new entries after 13:00
EXIT_BAR = SESSION_BARS - 1            # flat at the closing auction (13:25-13:30 bar)


class TMError(Exception):
    pass


@dataclass
class Rule:
    """The rule the history re-runs. orb = opening-range breakout, long only."""
    orb_minutes: int = 15        # opening range length
    target_r: float = 1.0        # target distance in multiples of risk
    stop_rule: str = "orb_mid"   # "orb_mid" | "orb_low" | "pct"
    stop_pct: float = 0.0        # used when stop_rule == "pct" (e.g. 0.015 = 1.5%)


@dataclass
class Plan:
    stock_id: str
    date: str
    entry: float
    entry_bar: int
    stop: float
    target: float
    shares: int = 1000
    rule: Rule = field(default_factory=Rule)
    source: str = "manual"   # "orb" when derived from the rule on `date`

    @property
    def risk(self) -> float:
        return self.entry - self.stop


# ── rule helpers ─────────────────────────────────────────────────────────────

def orb_signal(bars: list[list[float]], rule: Rule):
    """First bar after the opening range whose close breaks above the range high.
    Returns (entry_bar, range_high, range_low) where entry is at the OPEN of entry_bar,
    i.e. the bar after the signal closed, or None."""
    n = max(1, rule.orb_minutes // 5)
    hi = max(b[1] for b in bars[:n])
    lo = min(b[2] for b in bars[:n])
    for i in range(n, LAST_ENTRY_BAR):
        if bars[i][3] > hi:
            return i + 1, hi, lo
    return None


def stop_for(entry: float, hi: float, lo: float, rule: Rule) -> float:
    if rule.stop_rule == "orb_low":
        s = lo
    elif rule.stop_rule == "pct":
        s = entry * (1 - rule.stop_pct)
    else:
        s = (hi + lo) / 2
    return round_to_tick(s, "down")


def target_for(entry: float, stop: float, rule: Rule) -> float:
    return round_to_tick(entry + rule.target_r * (entry - stop), "up")


def plan_from_orb(stock_id: str, date: str, bars, rule: Rule, costs: DayTradeCosts, shares: int) -> Plan:
    sig = orb_signal(bars, rule)
    if not sig:
        raise TMError("%s %s: no opening-range breakout before 13:00 on that day" % (stock_id, date))
    eb, hi, lo = sig
    entry = costs.slip(bars[eb][0], "buy")
    stop = stop_for(entry, hi, lo, rule)
    if stop >= entry:
        raise TMError("stop %.2f is not below entry %.2f" % (stop, entry))
    return Plan(stock_id, date, entry, eb, stop, target_for(entry, stop, rule), shares, rule, "orb")


# ── one trade, bar by bar ─────────────────────────────────────────────────────

def walk(entry: float, stop: float, target: float, bars_iter, costs: DayTradeCosts):
    """Walk bars after entry. Returns (outcome, gross_exit_price, net_exit_price, last_close).
    outcome: 'target' | 'stop' | 'neither' (closed at the exit bar)."""
    last = entry
    for o, h, l, c in bars_iter:
        if l <= stop:
            px = min(o, stop)                      # a gap through the stop fills at the open
            return "stop", px, costs.slip(px, "sell"), c
        if h >= target:
            return "target", max(o, target), max(o, target), c   # limit order: no slippage
        last = c
    return "neither", last, costs.slip(last, "sell"), last


def net_r(plan: Plan, sell_net: float, costs: DayTradeCosts) -> tuple[float, float]:
    pnl = costs.net_pnl(plan.entry, sell_net, plan.shares)
    return pnl / (plan.risk * plan.shares), pnl


# ── Monte Carlo ───────────────────────────────────────────────────────────────

def build_pool(sessions: dict, before: str) -> list[list[tuple]]:
    """pool[i] = list of (o,h,l,c) ratios to the previous close for bar i, from full
    sessions strictly before `before`. Bar 0 uses the session's own open as the base so
    the overnight gap is never part of an intraday replay."""
    pool: list[list[tuple]] = [[] for _ in range(SESSION_BARS)]
    used = 0
    for ds, bars in sessions.items():
        if ds >= before or len(bars) != SESSION_BARS:
            continue
        used += 1
        pc = bars[0][0]
        for i, b in enumerate(bars):
            if pc <= 0:
                break
            pool[i].append((b[0] / pc, b[1] / pc, b[2] / pc, b[3] / pc))
            pc = b[3]
    return pool if used else []


def monte_carlo(plan: Plan, pool, costs: DayTradeCosts, replays: int, seed: int,
                window: int = 2, exit_bar: int = EXIT_BAR) -> dict:
    rng = random.Random(seed)
    cand = []
    for i in range(SESSION_BARS):
        lo, hi = max(0, i - window), min(SESSION_BARS - 1, i + window)
        cand.append([r for j in range(lo, hi + 1) for r in pool[j]])
    counts = {"target": 0, "stop": 0, "neither": 0}
    rs, closes, profitable = [], [], 0
    for _ in range(replays):
        price = plan.entry
        def gen():
            nonlocal price
            for i in range(plan.entry_bar, exit_bar + 1):
                ro, rh, rl, rc = rng.choice(cand[i])
                o, h, l, c = price * ro, price * rh, price * rl, price * rc
                price = c
                yield o, h, l, c
        outcome, _, sell_net, last = walk(plan.entry, plan.stop, plan.target, gen(), costs)
        counts[outcome] += 1
        r, pnl = net_r(plan, sell_net, costs)
        rs.append(r)
        closes.append(last)
        profitable += pnl > 0
    closes.sort()
    q = lambda p: round(closes[min(len(closes) - 1, int(p * len(closes)))], 2)
    n = float(replays)
    return {
        "replays": replays, "seed": seed, "window": window,
        "target_first": round(counts["target"] / n * 100, 1),
        "stop_first": round(counts["stop"] / n * 100, 1),
        "neither": round(counts["neither"] / n * 100, 1),
        "profitable_after_costs": round(profitable / n * 100, 1),
        "avg_net_r": round(statistics.fmean(rs), 3),
        "exit_p5": q(0.05), "exit_median": q(0.5), "exit_p95": q(0.95),
    }


# ── History: the same rule on every past session ─────────────────────────────

def history(plan: Plan, sessions: dict, costs: DayTradeCosts, exit_bar: int = EXIT_BAR) -> dict:
    trades = []
    for ds, bars in sessions.items():
        if ds >= plan.date or len(bars) != SESSION_BARS:
            continue
        if plan.source == "orb":
            sig = orb_signal(bars, plan.rule)
            if not sig:
                continue
            eb, hi, lo = sig
            entry = costs.slip(bars[eb][0], "buy")
            stop = stop_for(entry, hi, lo, plan.rule)
        else:  # manual plan: same entry time, same stop distance in %, same R
            eb = plan.entry_bar
            entry = costs.slip(bars[eb][0], "buy")
            stop = round_to_tick(entry * plan.stop / plan.entry, "down")
        if stop >= entry:
            continue
        target = target_for(entry, stop, plan.rule) if plan.source == "orb" else \
            round_to_tick(entry + (plan.target - plan.entry) / plan.risk * (entry - stop), "up")
        p = Plan(plan.stock_id, ds, entry, eb, stop, target, plan.shares, plan.rule, plan.source)
        outcome, _, sell_net, _ = walk(entry, stop, target,
                                       (b[:4] for b in bars[eb:exit_bar + 1]), costs)
        r, pnl = net_r(p, sell_net, costs)
        trades.append({"date": ds, "outcome": outcome, "net_r": round(r, 3), "net_pnl": round(pnl)})
    n = len(trades)
    out = {"sessions": sum(1 for d in sessions if d < plan.date), "trades": n}
    if n:
        out.update({
            "target": sum(t["outcome"] == "target" for t in trades),
            "stop": sum(t["outcome"] == "stop" for t in trades),
            "neither": sum(t["outcome"] == "neither" for t in trades),
            "profitable": sum(t["net_pnl"] > 0 for t in trades),
            "avg_net_r": round(statistics.fmean(t["net_r"] for t in trades), 3),
            "total_net_pnl": sum(t["net_pnl"] for t in trades),
        })
    out["list"] = trades[-20:]
    return out


def verdict(mc: dict, hist: dict) -> list[str]:
    r = mc["avg_net_r"]
    if r <= -0.15:
        line = "扣成本後明顯偏虧：平均每筆 %.2fR。" % r
    elif r < -0.05:
        line = "扣成本後偏虧：平均每筆 %.2fR。" % r
    elif r <= 0.05:
        line = "扣成本後接近損益兩平（%.2fR），等於擲銅板再付手續費。" % r
    elif r < 0.15:
        line = "扣成本後略偏正（%.2fR），優勢很薄，滑價多一檔就可能消失。" % r
    else:
        line = "扣成本後偏正（%.2fR），仍需更多樣本與模擬交易驗證。" % r
    lines = [line]
    if mc["neither"] > 40:
        lines.append("%.1f%% 的重播到收盤都沒碰到停損或停利，結果主要由收盤價決定。" % mc["neither"])
    n = hist.get("trades", 0)
    if n < 30:
        lines.append("歷史只有 %d 筆同規則交易，樣本太少，不能當作勝率。" % n)
    elif (hist["avg_net_r"] > 0) != (r > 0):
        lines.append("歷史實際結果（%.2fR）與重播方向相反，以歷史為準要更保守。" % hist["avg_net_r"])
    return lines


# ── entry point ───────────────────────────────────────────────────────────────

def run(stock_id: str, date: str, *, entry: float | None = None, stop: float | None = None,
        target: float | None = None, entry_time: str | None = None, rule: Rule | None = None,
        costs: DayTradeCosts | None = None, shares: int = 1000, replays: int = 10000,
        seed: int = DEFAULT_SEED, window: int = 2, days: int = 60, sessions: dict | None = None,
        token: str | None = None, source: str = "auto") -> dict:
    rule = rule or Rule()
    costs = costs or DayTradeCosts()
    if replays < 100 or replays > 50000:
        raise TMError("replays must be between 100 and 50,000")
    data_source = "offline"
    if sessions is None:
        sessions = load_sessions(stock_id, date, days=days + 1, token=token, source=source)
        if days < len(sessions) - 1:  # keep the newest `days` sessions before `date`, plus `date`
            keep = sorted(sessions)[-(days + 1):]
            sessions = {k: sessions[k] for k in keep}
        data_source = LAST_SOURCE["name"]
    if date not in sessions:
        raise TMError("%s %s: no complete 5-minute session for that date (holiday, not yet closed, or data gap)"
                      % (stock_id, date))
    bars = sessions[date]
    if entry is None:
        plan = plan_from_orb(stock_id, date, bars, rule, costs, shares)
    else:
        if stop is None or target is None or not entry_time:
            raise TMError("a manual plan needs entry, stop, target and entry_time")
        eb = parse_hhmm(entry_time)
        if not (0 < eb <= LAST_ENTRY_BAR):
            raise TMError("entry_time must be between 09:05 and 13:00")
        if not (stop < entry < target):
            raise TMError("need stop < entry < target for a long day trade")
        rule = Rule(rule.orb_minutes, (target - entry) / (entry - stop), "pct", (entry - stop) / entry)
        plan = Plan(stock_id, date, float(entry), eb, float(stop), float(target), shares, rule, "manual")
    pool = build_pool(sessions, date)
    full = sum(1 for d in sessions if d < date)
    if not pool or full < MIN_POOL:
        raise TMError("only %d full sessions before %s; need at least %d" % (full, date, MIN_POOL))
    mc = monte_carlo(plan, pool, costs, replays, seed, window)
    hist = history(plan, sessions, costs)
    # what the plan actually did on its own day (after costs)
    o, _, sell_net, _ = walk(plan.entry, plan.stop, plan.target,
                             (b[:4] for b in bars[plan.entry_bar:EXIT_BAR + 1]), costs)
    day_r, day_pnl = net_r(plan, sell_net, costs)
    rt_cost = costs.fee(plan.entry * shares) * 2 + plan.entry * shares * costs.tax_rate
    return {
        "plan": {
            "stock_id": stock_id, "date": date, "source": plan.source,
            "entry": plan.entry, "entry_time": bar_time(plan.entry_bar), "stop": plan.stop,
            "target": plan.target, "target_r": round(plan.rule.target_r, 2), "shares": shares,
            "risk_per_share": round(plan.risk, 2),
            "round_trip_cost_pct": round(rt_cost / (plan.entry * shares) * 100 +
                                         2 * costs.slip_ticks * tick_size(plan.entry) / plan.entry * 100, 3),
            "rule": asdict(plan.rule),
        },
        "costs": asdict(costs),
        "data_source": data_source,
        "pool": {"sessions": full, "from": min(d for d in sessions if d < date), "to": max(d for d in sessions if d < date)},
        "mc": mc,
        "history": hist,
        "actual_day": {"outcome": o, "net_r": round(day_r, 3), "net_pnl": round(day_pnl)},
        "verdict": verdict(mc, hist),
        "disclaimer": "模擬結果來自過去 %d 個交易日的 5 分 K，不是預測，也不是投資建議。" % full,
        "credit": "Method adapted from trader-timemachine by Jake Schincariol (MIT).",
    }


def format_text(res: dict) -> str:
    p, mc, h = res["plan"], res["mc"], res["history"]
    out = [
        "%s %s  進場 %.2f @%s  停損 %.2f  停利 %.2f (%.2fR)  %d 股  來回成本約 %.2f%%"
        % (p["stock_id"], p["date"], p["entry"], p["entry_time"], p["stop"], p["target"],
           p["target_r"], p["shares"], p["round_trip_cost_pct"]),
        "%d 次重播（seed %d），樣本 %d 個交易日 %s ~ %s，資料來源 %s"
        % (mc["replays"], mc["seed"], res["pool"]["sessions"], res["pool"]["from"], res["pool"]["to"],
           res.get("data_source", "")),
        "  先碰停利 %5.1f%%" % mc["target_first"],
        "  先碰停損 %5.1f%%" % mc["stop_first"],
        "  都沒碰到 %5.1f%%（13:30 收盤出場）" % mc["neither"],
        "  扣成本後賺錢 %5.1f%%   平均 %.3fR" % (mc["profitable_after_costs"], mc["avg_net_r"]),
        "  出場時股價 中位數 %.2f，90%% 落在 %.2f ~ %.2f" % (mc["exit_median"], mc["exit_p5"], mc["exit_p95"]),
    ]
    if h.get("trades"):
        out.append("歷史：同規則 %d 天中觸發 %d 次，停利 %d / 停損 %d / 收盤 %d，扣成本後賺錢 %d 次，平均 %.3fR"
                   % (h["sessions"], h["trades"], h["target"], h["stop"], h["neither"], h["profitable"], h["avg_net_r"]))
    else:
        out.append("歷史：同規則在過去 %d 天沒有觸發。" % h["sessions"])
    a = res["actual_day"]
    out.append("當天實際：%s，%.3fR，%+d 元" % (a["outcome"], a["net_r"], a["net_pnl"]))
    out += res["verdict"] + [res["disclaimer"]]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="台股時光機：當沖計畫扣成本後的 1 萬次重播")
    ap.add_argument("stock_id")
    ap.add_argument("date", help="YYYY-MM-DD, a completed session")
    ap.add_argument("--entry", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--target", type=float)
    ap.add_argument("--entry-time")
    ap.add_argument("--orb-minutes", type=int, default=15)
    ap.add_argument("--target-r", type=float, default=1.0)
    ap.add_argument("--stop-rule", default="orb_mid", choices=["orb_mid", "orb_low"])
    ap.add_argument("--shares", type=int, default=1000)
    ap.add_argument("--fee-discount", type=float, default=0.6)
    ap.add_argument("--slip-ticks", type=int, default=1)
    ap.add_argument("--replays", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--offline", help="JSON file of sessions or FinMind KBar rows")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--source", default="auto", choices=["auto", "finmind", "yahoo"])
    a = ap.parse_args(argv)
    try:  # Windows consoles default to a legacy code page
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        res = run(a.stock_id, a.date, entry=a.entry, stop=a.stop, target=a.target, entry_time=a.entry_time,
                  rule=Rule(a.orb_minutes, a.target_r, a.stop_rule),
                  costs=DayTradeCosts(fee_discount=a.fee_discount, slip_ticks=a.slip_ticks),
                  shares=a.shares, replays=a.replays, seed=a.seed, days=a.days,
                  sessions=load_offline(a.offline) if a.offline else None, source=a.source)
    except (TMError, DataError) as e:
        print("錯誤：%s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else format_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
