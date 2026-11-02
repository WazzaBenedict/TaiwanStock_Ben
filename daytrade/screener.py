"""當沖候選掃描 (day-trade candidate screen), long only (先買後賣).

1. Universe: TWSE listed stocks from the last session (STOCK_DAY_ALL), no ETFs,
   price >= NT$20, top N by traded value.
2. Must be on TWSE's 現股當沖 list (TWTB4U) and not on today's 處置 / 注意 lists.
3. For each survivor, about 60 sessions of 5-minute bars (Yahoo; FinMind when a sponsor
   token is set) are used to measure intraday range and to run the Time Machine's
   opening-range-breakout rule on every session, NET of commission, the 0.15% day-trade
   tax and slippage.
4. The same stock is also traded with RANDOM entries (same stop distance, same target R)
   as a control. A rule that does not beat random entry on that stock has no edge there,
   whatever its win rate.

Ranking is by the rule's average net R. A stock is marked as passing only when its
average net R is above zero, it has at least MIN_TRADES trades and it beats the random
control. With ~60 sessions even a pass is weak evidence: treat it as a paper-trading
watch list, not a buy list.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

try:
    from .costs import DayTradeCosts, round_to_tick, tick_size
    from .data import CACHE_DIR, SESSION_BARS, DataError, bar_time, fetch_today_yahoo, load_sessions, taipei_today
    from . import timemachine as tm
except ImportError:  # pragma: no cover
    from costs import DayTradeCosts, round_to_tick, tick_size  # type: ignore
    from data import CACHE_DIR, SESSION_BARS, DataError, bar_time, fetch_today_yahoo, load_sessions, taipei_today  # type: ignore
    import timemachine as tm  # type: ignore

UA = {"User-Agent": "Mozilla/5.0 (taiwanstock-daytrade/1.0)"}
URL_DAY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_TWTB4U = "https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date=%s"
URL_PUNISH = "https://www.twse.com.tw/rwd/zh/announcement/punish?response=json"
URL_NOTICE = "https://www.twse.com.tw/rwd/zh/announcement/notice?response=json&startDate=%s&endDate=%s"
MIN_TRADES = 15
RANDOM_DRAWS = 20


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(x) -> float:
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return 0.0


def _roc_date(s: str) -> str:
    """'1151030' (ROC year 115) -> '2026-10-30'."""
    s = s.strip()
    if re.fullmatch(r"\d{7}", s):
        return "%04d-%s-%s" % (int(s[:3]) + 1911, s[3:5], s[5:7])
    return s


def universe(top: int = 40, min_price: float = 20.0) -> list[dict]:
    rows = _get_json(URL_DAY_ALL)
    out = []
    for r in rows:
        code = str(r.get("Code", "")).strip()
        if not re.fullmatch(r"[1-9]\d{3}", code):  # 4-digit common stocks; skips 00xx ETFs
            continue
        close = _num(r.get("ClosingPrice"))
        value = _num(r.get("TradeValue"))
        if close < min_price or value <= 0:
            continue
        out.append({"stock_id": code, "name": str(r.get("Name", "")).strip(), "close": close,
                    "date": _roc_date(str(r.get("Date", ""))),
                    "trade_value": value, "high": _num(r.get("HighestPrice")), "low": _num(r.get("LowestPrice"))})
    out.sort(key=lambda x: -x["trade_value"])
    return out[:top]


def _codes_in(payload) -> set[str]:
    """Collect 4-digit codes from the first cells of every row of every table in a TWSE
    JSON payload (formats differ between endpoints and years)."""
    codes: set[str] = set()
    tables = []
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            tables.append(payload["data"])
        for t in payload.get("tables") or []:
            if isinstance(t, dict) and isinstance(t.get("data"), list):
                tables.append(t["data"])
    for rows in tables:
        for row in rows:
            cells = row if isinstance(row, list) else list(row.values()) if isinstance(row, dict) else []
            for c in cells[:4]:
                c = str(c).strip()
                if re.fullmatch(r"[1-9]\d{3}", c):
                    codes.add(c)
                    break
    return codes


def daytrade_list(date: str) -> set[str]:
    """Stocks on TWSE's 現股當沖 list for `date` (YYYY-MM-DD). Empty set if unavailable."""
    try:
        return _codes_in(_get_json(URL_TWTB4U % date.replace("-", "")))
    except Exception:
        return set()


def flagged_lists() -> tuple[set[str], set[str]]:
    # the undated notice list is today's, published after the close: ask for the last
    # few weekdays instead so attention stocks are flagged overnight and intraday
    end = taipei_today()
    start, k = end, 0
    while k < 3:
        start -= dt.timedelta(days=1)
        k += start.weekday() < 5
    out = []
    for url in (URL_PUNISH, URL_NOTICE % (start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))):
        try:
            out.append(_codes_in(_get_json(url)))
        except Exception:
            out.append(set())
    return out[0], out[1]


# ── per-stock evaluation ─────────────────────────────────────────────────────

def _stats(rs: list[float]) -> dict:
    if not rs:
        return {"n": 0, "avg_net_r": None, "se": None, "win_rate": None}
    se = statistics.stdev(rs) / len(rs) ** 0.5 if len(rs) > 1 else None
    return {"n": len(rs), "avg_net_r": round(statistics.fmean(rs), 3),
            "se": round(se, 3) if se is not None else None,
            "win_rate": round(sum(r > 0 for r in rs) / len(rs) * 100, 1)}


def random_control(sessions: dict, stop_pct: float, target_r: float, costs: DayTradeCosts,
                   seed: int = 7, draws: int = RANDOM_DRAWS) -> list[float]:
    """Random entry bar each session (after the first 15 minutes, before 13:00), same
    stop distance in % and same target R as the rule. Returns net R per trade."""
    rng = random.Random(seed)
    rs = []
    for ds, bars in sessions.items():
        if len(bars) != SESSION_BARS:
            continue
        for _ in range(draws):
            eb = rng.randint(3, tm.LAST_ENTRY_BAR)
            entry = costs.slip(bars[eb][0], "buy")
            stop = entry * (1 - stop_pct)
            target = entry + target_r * (entry - stop)
            outcome, _, sell_net, _ = tm.walk(entry, stop, target, (b[:4] for b in bars[eb:tm.EXIT_BAR + 1]), costs)
            pnl = costs.net_pnl(entry, sell_net, 1000)
            rs.append(pnl / ((entry - stop) * 1000))
    return rs


def evaluate(stock_id: str, sessions: dict, rule: tm.Rule, costs: DayTradeCosts) -> dict:
    days = sorted(sessions)
    last20 = [sessions[d] for d in days[-20:]]
    ranges = [(max(b[1] for b in s) - min(b[2] for b in s)) / s[0][0] * 100 for s in last20]
    dummy = tm.Plan(stock_id, "9999-12-31", 1.0, 1, 0.5, 1.5, 1000, rule, "orb")
    hist = tm.history(dummy, sessions, costs)
    rs = [t["net_r"] for t in _all_orb_trades(sessions, rule, costs)]
    orb = _stats(rs)
    stop_pcts = _orb_stop_pcts(sessions, rule, costs)
    stop_pct = statistics.median(stop_pcts) if stop_pcts else 0.01
    rnd = _stats(random_control(sessions, stop_pct, rule.target_r, costs))
    last_close = sessions[days[-1]][-1][3]
    rt_cost = (costs.fee(last_close * 1000) * 2 + last_close * 1000 * costs.tax_rate) / (last_close * 1000) * 100 \
        + 2 * costs.slip_ticks * tick_size(last_close) / last_close * 100
    edge = None if orb["avg_net_r"] is None or rnd["avg_net_r"] is None else round(orb["avg_net_r"] - rnd["avg_net_r"], 3)
    passed = bool(orb["n"] >= MIN_TRADES and orb["avg_net_r"] is not None and orb["avg_net_r"] > 0 and edge and edge > 0)
    return {
        "stock_id": stock_id, "sessions": len(days), "from": days[0], "to": days[-1],
        "avg_range_pct": round(statistics.fmean(ranges), 2),
        "round_trip_cost_pct": round(rt_cost, 3),
        "median_stop_pct": round(stop_pct * 100, 2),
        "orb": orb, "random": rnd, "edge_vs_random_r": edge,
        "orb_outcomes": {k: hist.get(k, 0) for k in ("target", "stop", "neither")},
        "passed": passed,
    }


def _orb_trades_iter(sessions, rule, costs):
    for ds, bars in sessions.items():
        if len(bars) != SESSION_BARS:
            continue
        sig = tm.orb_signal(bars, rule)
        if not sig:
            continue
        eb, hi, lo = sig
        entry = costs.slip(bars[eb][0], "buy")
        stop = tm.stop_for(entry, hi, lo, rule)
        if stop >= entry:
            continue
        yield ds, bars, eb, entry, stop


def _orb_stop_pcts(sessions, rule, costs):
    return [(e - s) / e for _, _, _, e, s in _orb_trades_iter(sessions, rule, costs)]


def _all_orb_trades(sessions, rule, costs):
    out = []
    for ds, bars, eb, entry, stop in _orb_trades_iter(sessions, rule, costs):
        target = tm.target_for(entry, stop, rule)
        outcome, _, sell_net, _ = tm.walk(entry, stop, target, (b[:4] for b in bars[eb:tm.EXIT_BAR + 1]), costs)
        pnl = costs.net_pnl(entry, sell_net, 1000)
        out.append({"date": ds, "outcome": outcome, "net_r": pnl / ((entry - stop) * 1000)})
    return out


# ── today's prices: entry, stop-loss, take-profit ─────────────────────────────

def plan_levels(bars: list[list[float]], rule: tm.Rule, costs: DayTradeCosts, shares: int = 1000,
                is_today: bool = True) -> dict:
    """Entry / stop / target for today from the bars traded so far (5-minute, from 09:00).

    Before the opening range is complete only the rule is known. After it, the trigger
    (range high), the estimated entry (one tick above it, plus slippage), the stop (range
    midpoint or low) and the target (entry + R x risk) are fixed. Once a 5-minute bar has
    closed above the trigger, the entry is the next bar's open and the trade is followed
    to its stop, target or the close."""
    n = max(1, rule.orb_minutes // 5)
    out = {"bars_so_far": len(bars), "last_bar": bar_time(len(bars) - 1) if bars else None}
    if len(bars) < n:
        out.update(status="waiting_range",
                   message="開盤區間 09:00–%s 還沒走完，%s 後才有進場價。" % (bar_time(n), bar_time(n)))
        return out
    hi = max(b[1] for b in bars[:n])
    lo = min(b[2] for b in bars[:n])
    trigger = hi
    est_entry = costs.slip(round_to_tick(hi + tick_size(hi), "up"), "buy")
    stop = tm.stop_for(est_entry, hi, lo, rule)
    target = tm.target_for(est_entry, stop, rule)
    out.update(range_high=round(hi, 2), range_low=round(lo, 2), trigger=round(trigger, 2),
               entry=est_entry, stop=stop, target=target, entry_is_estimate=True)
    sig = None
    for i in range(n, min(len(bars), tm.LAST_ENTRY_BAR)):
        if bars[i][3] > hi:
            sig = i
            break
    if sig is None:
        if len(bars) > tm.LAST_ENTRY_BAR or not is_today:
            out.update(status="no_signal", message="13:00 前沒有收盤突破開盤區間高點，今天不進場。")
        else:
            out.update(status="waiting_breakout",
                       message="等某根 5 分 K 收盤站上 %.2f，下一根開盤買進（約 %.2f）。" % (trigger, est_entry))
    elif sig + 1 >= len(bars):
        out.update(status="breakout_now", message="%s 那根已收盤突破，下一根開盤買進。" % bar_time(sig))
    else:
        entry = costs.slip(bars[sig + 1][0], "buy")
        stop = tm.stop_for(entry, hi, lo, rule)
        target = tm.target_for(entry, stop, rule)
        out.update(entry=entry, stop=stop, target=target, entry_is_estimate=False, entry_time=bar_time(sig + 1))
        if stop >= entry:
            out.update(status="skip", message="進場價已低於停損，不進場。")
            return out
        res, px, sell_net, _ = tm.walk(entry, stop, target, (b[:4] for b in bars[sig + 1:]), costs)
        finished = len(bars) >= SESSION_BARS or not is_today
        if res == "neither" and finished:
            px = bars[-1][3]
            pnl = costs.net_pnl(entry, costs.slip(px, "sell"), shares)
            out.update(status="closed_close", exit=round(px, 2), net_pnl=round(pnl),
                       message="沒碰到停損停利，收盤出場（%.2f），扣成本後 %+d 元。" % (px, round(pnl)))
        elif res == "neither":
            out.update(status="in_trade", last=round(bars[-1][3], 2),
                       message="已在 %s 進場，持有中；碰 %.2f 停損、%.2f 停利，否則 13:25 前出場。"
                       % (bar_time(sig + 1), stop, target))
        else:
            pnl = costs.net_pnl(entry, sell_net, shares)
            out.update(status="closed_" + res, exit=round(px, 2), net_pnl=round(pnl),
                       message="已%s出場（%.2f），扣成本後 %+d 元。" % ("停利" if res == "target" else "停損", px, round(pnl)))
    e, s_ = out["entry"], out["stop"]
    out["risk_per_lot"] = round((e - s_) * shares + costs.fee(e * shares) * 2 + e * shares * costs.tax_rate)
    out["risk_pct"] = round((e - s_) / e * 100, 2)
    return out


def live_levels(stock_ids: list[str], rule: tm.Rule | None = None, costs: DayTradeCosts | None = None,
                shares: int = 1000) -> dict:
    rule = rule or tm.Rule()
    costs = costs or DayTradeCosts()
    out = {}
    for sid in stock_ids:
        got = fetch_today_yahoo(sid)
        if not got:
            out[sid] = {"status": "no_data", "message": "取不到今天的 5 分 K（盤前、休市或資料源延遲）。"}
            continue
        ds, bars = got
        is_today = ds == taipei_today().isoformat()
        lv = plan_levels(bars, rule, costs, shares, is_today)
        lv["date"] = ds
        if not is_today:
            lv["note"] = "這是 %s 的資料，今天還沒開盤或尚無資料。" % ds
        out[sid] = lv
    return {"rule": {"orb_minutes": rule.orb_minutes, "target_r": rule.target_r}, "levels": out,
            "data_note": "Yahoo 盤中資料可能延遲數分鐘以上，下單前請以券商報價為準。"}


# ── the screen ───────────────────────────────────────────────────────────────

def screen(top: int = 40, rule: tm.Rule | None = None, costs: DayTradeCosts | None = None,
           min_range_pct: float = 2.0, pause: float = 0.3, use_cache: bool = True, log=None) -> dict:
    rule = rule or tm.Rule()
    costs = costs or DayTradeCosts()
    today = taipei_today().isoformat()
    cpath = CACHE_DIR / ("screen-%s-%d-%d-%s-d%g-s%d.json" % (today, top, rule.orb_minutes, rule.target_r,
                                                          costs.fee_discount, costs.slip_ticks))
    if use_cache and cpath.exists():
        return json.loads(cpath.read_text(encoding="utf-8"))
    log = log or (lambda *_: None)
    uni = universe(top)
    if not uni:
        raise DataError("TWSE STOCK_DAY_ALL returned no stocks")
    # the day-trade list is published per trading day; try today, then back up to 5 weekdays
    dtl, d = set(), taipei_today()
    for _ in range(6):
        if d.weekday() < 5:
            dtl = daytrade_list(d.isoformat())
            if dtl:
                break
        d -= dt.timedelta(days=1)
    punish, notice = flagged_lists()
    notes = []
    if uni[0].get("date"):
        notes.append("成交值排名用 %s 的資料。" % uni[0]["date"])
    if not dtl:
        notes.append("無法取得證交所現股當沖名單，未以此過濾，請自行確認可當沖。")
    rows, skipped = [], []
    for u in uni:
        sid = u["stock_id"]
        if dtl and sid not in dtl:
            skipped.append({"stock_id": sid, "name": u["name"], "reason": "不在現股當沖名單", "kind": "不可當沖"})
            continue
        if sid in punish:
            skipped.append({"stock_id": sid, "name": u["name"], "reason": "處置股", "kind": "處置股"})
            continue
        try:
            sessions = load_sessions(sid, today)
        except DataError as e:
            skipped.append({"stock_id": sid, "name": u["name"], "reason": "分 K 取得失敗：%s" % str(e)[:80], "kind": "資料失敗"})
            continue
        finally:
            time.sleep(pause)
        sessions = {k: v for k, v in sessions.items() if k < today}  # completed sessions only
        if len(sessions) < tm.MIN_POOL:
            skipped.append({"stock_id": sid, "name": u["name"], "reason": "分 K 只有 %d 天" % len(sessions), "kind": "資料不足"})
            continue
        ev = evaluate(sid, sessions, rule, costs)
        if ev["avg_range_pct"] < min_range_pct:
            skipped.append({"stock_id": sid, "name": u["name"],
                            "reason": "平均日內振幅 %.1f%% 太小" % ev["avg_range_pct"], "kind": "振幅太小"})
            continue
        ev.update({"name": u["name"], "close": round(sessions[ev["to"]][-1][3], 2),
                   "trade_value_e8": round(u["trade_value"] / 1e8, 1),
                   "attention": sid in notice})
        rows.append(ev)
        log("%s %s range %.1f%% orb %s rnd %s" % (sid, u["name"], ev["avg_range_pct"],
                                                   ev["orb"]["avg_net_r"], ev["random"]["avg_net_r"]))
    rows.sort(key=lambda r: (r["orb"]["avg_net_r"] is None, -(r["orb"]["avg_net_r"] or -9)))
    res = {
        "as_of": today, "universe_date": uni[0].get("date", ""),
        "last_session": max((r["to"] for r in rows), default=""), "rule": {"orb_minutes": rule.orb_minutes, "target_r": rule.target_r,
                                 "stop_rule": rule.stop_rule},
        "costs": {"broker": costs.broker, "fee_discount": costs.fee_discount, "min_fee": costs.min_fee, "tax_rate": costs.tax_rate, "slip_ticks": costs.slip_ticks},
        "universe": len(uni), "daytrade_list_size": len(dtl), "candidates": rows, "skipped": skipped,
        "passed": sum(r["passed"] for r in rows), "notes": notes,
        "how_to_trade": ("規則：9:%02d 前不進場；之後某根 5 分 K 收盤突破開盤 %d 分鐘高點，下一根開盤買進；"
                         "停損設在開盤區間中點；停利 %.1fR；沒碰到就在 13:25 前市價出場（或參加收盤競價）。13:00 後不進新單。"
                         % (rule.orb_minutes, rule.orb_minutes, rule.target_r)),
        "disclaimer": "歷史只有約 60 個交易日，即使通過也只是模擬觀察名單，不是投資建議。多數散戶當沖長期是虧損的。",
    }
    try:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return res


def format_text(res: dict) -> str:
    out = ["當沖候選掃描 %s　規則：開盤 %d 分鐘突破、停利 %.1fR　（成交值前 %d 名，可當沖名單 %d 檔）"
           % (res["as_of"], res["rule"]["orb_minutes"], res["rule"]["target_r"], res["universe"],
              res["daytrade_list_size"])]
    out += res["notes"]
    out.append("%-6s %-8s %8s %7s %7s %5s %8s %8s %7s  %s" % ("代號", "名稱", "收盤", "振幅%", "成本%", "筆數",
                                                              "規則R", "隨機R", "勝隨機", "結論"))
    for r in res["candidates"]:
        o, rd = r["orb"], r["random"]
        out.append("%-6s %-8s %8.2f %7.2f %7.2f %5d %8s %8s %7s  %s%s" % (
            r["stock_id"], r["name"][:8], r["close"], r["avg_range_pct"], r["round_trip_cost_pct"], o["n"],
            o["avg_net_r"], rd["avg_net_r"], r["edge_vs_random_r"],
            "通過（僅供模擬觀察）" if r["passed"] else "不建議", "，注意股" if r.get("attention") else ""))
    kinds: dict[str, list[str]] = {}
    for sk in res["skipped"]:
        kinds.setdefault(sk.get("kind", "其他"), []).append(sk["stock_id"])
    out.append("通過 %d 檔。略過 %d 檔：%s" % (res["passed"], len(res["skipped"]),
               "；".join("%s %s" % (k, ",".join(v[:6]) + ("…" if len(v) > 6 else "")) for k, v in kinds.items()) or "無"))
    out += [res["how_to_trade"], res["disclaimer"]]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="當沖候選掃描（先買後賣，扣成本後回測）")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--orb-minutes", type=int, default=15)
    ap.add_argument("--target-r", type=float, default=1.0)
    ap.add_argument("--fee-discount", type=float, default=DayTradeCosts().fee_discount)
    ap.add_argument("--slip-ticks", type=int, default=1)
    ap.add_argument("--min-range", type=float, default=2.0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    res = screen(a.top, tm.Rule(a.orb_minutes, a.target_r), DayTradeCosts(fee_discount=a.fee_discount,
                 slip_ticks=a.slip_ticks), a.min_range, use_cache=not a.no_cache,
                 log=lambda s: print(s, file=sys.stderr))
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else format_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
