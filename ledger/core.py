"""帳本計算核心（純函式，不連網）。

輸入：成交紀錄 fills（買、賣各一筆）、0050 日線、各代號最新收盤。
輸出：配對後的每筆交易（先進先出）、未平倉部位、對照 0050 的影子帳、紀律檢查、每週結算。

成本：成交紀錄若帶有實際手續費／交易稅（例如從對帳單匯入）就用實際值；
否則用 twcosts（元大電子下單）估算。當沖（同一天買進並賣出）自動套 0.15% 交易稅。

影子帳的定義（刻意簡單，寫在畫面上）：
- 當沖：這筆買進金額若當天放在 0050，開盤到收盤的損益。
- 隔日以上：這筆買進金額若在進場日收盤買 0050，抱到出場日收盤的損益。
- 未平倉：抱到最新收盤。
影子帳不扣 0050 的買賣成本，所以對 0050 略為有利，方向上偏保守。
"""
from __future__ import annotations

import math
from datetime import date

from twcosts import BrokerFees, broker, is_etf

DEFAULT_RULES = {
    "max_notional": 50000,      # 每筆買進金額上限
    "daily_stop": 1000,         # 當日當沖虧損達此金額後不得再進場
    "total_stop": 2500,         # 當沖累計虧損達此金額後不得再進場
    "no_entry_after": "13:00",  # 此時間後不再進場（成交紀錄有時間才檢查）
    "profit_to_0050_pct": 60,   # 每週當沖淨利轉入 0050 的比例
    "cushion_cap": 2000,        # 緩衝金上限，超過的部分也轉入 0050
}


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        f = float(str(v).replace(",", ""))
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def normalize(fills: list[dict]) -> tuple[list[dict], list[dict]]:
    """清理輸入；回傳（可用紀錄，被略過的紀錄與原因）。排序：日期、時間、原順序。"""
    ok, bad = [], []
    for i, f in enumerate(fills or []):
        side = str(f.get("side", "")).lower().strip()
        side = {"b": "buy", "買": "buy", "買進": "buy", "s": "sell", "賣": "sell", "賣出": "sell"}.get(side, side)
        d = str(f.get("date", "")).strip()[:10].replace("/", "-")
        price, shares = _num(f.get("price")), _num(f.get("shares"))
        code = str(f.get("code", "")).strip().upper()
        try:
            date.fromisoformat(d)
        except ValueError:
            bad.append({"index": i, "reason": "日期格式錯誤", "fill": f})
            continue
        if side not in ("buy", "sell") or not code or not price or price <= 0 or not shares or shares <= 0:
            bad.append({"index": i, "reason": "缺少代號、買賣別、價格或股數", "fill": f})
            continue
        ok.append({"id": f.get("id") or f"f{i}", "seq": i, "date": d, "time": str(f.get("time") or "").strip()[:5],
                   "code": code, "side": side, "price": price, "shares": int(shares),
                   "fee": _num(f.get("fee")), "tax": _num(f.get("tax")),
                   "plan_price": _num(f.get("plan_price")), "note": str(f.get("note") or "")[:200]})
    ok.sort(key=lambda r: (r["date"], r["time"] or "99:99", r["seq"]))
    return ok, bad


def _shadow(bars: dict, notional: float, d_in: str, d_out: str) -> float | None:
    """notional 元放在 0050 的損益。bars: {日期: {"o":開, "c":收}}。"""
    b_in, b_out = bars.get(d_in), bars.get(d_out)
    if not b_in or not b_out:
        return None
    base = b_in.get("o") if d_in == d_out else b_in.get("c")
    if not base or not b_out.get("c"):
        return None
    return round(notional * (b_out["c"] / base - 1), 2)


def _week(d: str) -> str:
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def compute(fills: list[dict], bars0050: dict | None = None, last_prices: dict | None = None,
            fee_discount: float | None = None, rules: dict | None = None) -> dict:
    fees: BrokerFees = broker(fee_discount)
    rules = {**DEFAULT_RULES, **(rules or {})}
    bars0050 = bars0050 or {}
    last_prices = last_prices or {}
    last_bar_day = max(bars0050) if bars0050 else None
    rows, skipped = normalize(fills)

    lots: dict[str, list[dict]] = {}       # 未平倉買進批次（先進先出）
    trades: list[dict] = []
    violations: list[dict] = []
    day_dt_net: dict[str, float] = {}      # 每日當沖已實現淨損益
    total_dt_net = 0.0
    used_actual_costs = 0

    def flag(f, rule, text):
        violations.append({"fill_id": f["id"], "date": f["date"], "code": f["code"], "rule": rule, "text": text})

    for f in rows:
        notional = f["price"] * f["shares"]
        if f["side"] == "buy":
            fee = f["fee"] if f["fee"] is not None else fees.fee(f["price"], f["shares"])
            used_actual_costs += f["fee"] is not None
            if notional > rules["max_notional"]:
                flag(f, "max_notional", f"買進 {notional:,.0f} 元，超過每筆上限 {rules['max_notional']:,.0f} 元")
            if day_dt_net.get(f["date"], 0) <= -rules["daily_stop"]:
                flag(f, "daily_stop", f"當日當沖已虧 {-day_dt_net[f['date']]:,.0f} 元，達每日停損後仍進場")
            if total_dt_net <= -rules["total_stop"]:
                flag(f, "total_stop", f"當沖累計已虧 {-total_dt_net:,.0f} 元，達總停損後仍進場")
            if f["time"] and rules.get("no_entry_after") and f["time"] >= rules["no_entry_after"]:
                flag(f, "late_entry", f"{f['time']} 進場，晚於 {rules['no_entry_after']}")
            lots.setdefault(f["code"], []).append({**f, "left": f["shares"], "fee_total": fee})
            continue

        # 賣出：先進先出配對
        queue = lots.get(f["code"], [])
        remain = f["shares"]
        matched = []
        while remain > 0 and queue:
            lot = queue[0]
            q = min(remain, lot["left"])
            matched.append((lot, q))
            lot["left"] -= q
            remain -= q
            if lot["left"] == 0:
                queue.pop(0)
        if remain > 0:
            flag(f, "short_first", f"賣出 {remain} 股沒有對應的買進（先賣後買或漏記買進），這部分未計入損益")
        sold = f["shares"] - remain
        if not sold:
            continue
        etf = is_etf(f["code"])
        sell_fee_total = f["fee"] if f["fee"] is not None else fees.fee(f["price"], f["shares"])
        used_actual_costs += f["fee"] is not None
        est_tax = sum(fees.tax(f["price"], q, etf, daytrade=(lot["date"] == f["date"])) for lot, q in matched)
        tax_total = f["tax"] if f["tax"] is not None else est_tax
        for lot, q in matched:
            share = q / f["shares"]
            buy_fee = lot["fee_total"] * q / lot["shares"]
            sell_fee = sell_fee_total * share
            tax = tax_total * (q / sold)
            gross = (f["price"] - lot["price"]) * q
            net = gross - buy_fee - sell_fee - tax
            dt = lot["date"] == f["date"]
            n_in = lot["price"] * q
            sh = _shadow(bars0050, n_in, lot["date"], f["date"])
            t = {"code": f["code"], "shares": q, "daytrade": dt, "open_date": lot["date"], "close_date": f["date"],
                 "hold_days": (date.fromisoformat(f["date"]) - date.fromisoformat(lot["date"])).days,
                 "buy_price": lot["price"], "sell_price": f["price"], "notional": round(n_in, 2),
                 "gross": round(gross, 2), "cost": round(buy_fee + sell_fee + tax, 2), "net": round(net, 2),
                 "net_pct": round(net / n_in * 100, 2), "shadow_0050": sh,
                 "vs_0050": round(net - sh, 2) if sh is not None else None,
                 "plan_price": lot.get("plan_price"),
                 "slip_vs_plan": round((lot["price"] - lot["plan_price"]) * q, 2) if lot.get("plan_price") else None,
                 "buy_id": lot["id"], "sell_id": f["id"], "week": _week(f["date"])}
            trades.append(t)
            if dt:
                day_dt_net[f["date"]] = day_dt_net.get(f["date"], 0) + net
                total_dt_net += net

    # 未平倉
    positions = []
    for code, queue in lots.items():
        for lot in queue:
            if lot["left"] <= 0:
                continue
            q = lot["left"]
            px = _num(last_prices.get(code))
            n_in = lot["price"] * q
            buy_fee = lot["fee_total"] * q / lot["shares"]
            unreal = None
            if px:
                exit_cost = fees.fee(px, q) + fees.tax(px, q, is_etf(code))
                unreal = round((px - lot["price"]) * q - buy_fee - exit_cost, 2)
            sh = _shadow(bars0050, n_in, lot["date"], last_bar_day) if last_bar_day and lot["date"] != last_bar_day else (0.0 if last_bar_day else None)
            positions.append({"code": code, "shares": q, "open_date": lot["date"], "buy_price": lot["price"],
                              "notional": round(n_in, 2), "last_price": px, "unrealized_net": unreal,
                              "shadow_0050": sh, "vs_0050": round(unreal - sh, 2) if unreal is not None and sh is not None else None,
                              "buy_id": lot["id"]})

    return {"trades": trades, "positions": positions, "violations": violations, "skipped": skipped,
            "summary": _summary(trades, positions, violations),
            "weekly": _weekly(trades, rules), "equity": _equity(trades),
            "rules": rules, "fees": {"name": fees.name, "fee_discount": fees.fee_discount,
                                     "fills_with_actual_costs": used_actual_costs, "fills": len(rows)},
            "notes": ["損益已扣手續費與交易稅；成交紀錄有實際費用時用實際值，否則用元大電子下單費率估算。",
                      "影子 0050：當沖比當天 0050 開盤到收盤；隔日以上比進場日收盤到出場日收盤；未扣 0050 買賣成本。",
                      "先進先出配對；同一天買進並賣出視為當沖（交易稅 0.15%）。"]}


def _agg(ts: list[dict]) -> dict:
    n = len(ts)
    net = sum(t["net"] for t in ts)
    known = [t for t in ts if t["shadow_0050"] is not None]
    sh = sum(t["shadow_0050"] for t in known)
    wins = sum(1 for t in ts if t["net"] > 0)
    return {"n": n, "wins": wins, "win_rate_pct": round(wins / n * 100) if n else None,
            "gross": round(sum(t["gross"] for t in ts), 2), "cost": round(sum(t["cost"] for t in ts), 2),
            "net": round(net, 2), "avg_net": round(net / n, 2) if n else None,
            "shadow_0050": round(sh, 2) if known else None,
            "vs_0050": round(sum(t["net"] for t in known) - sh, 2) if known else None,
            "shadow_coverage": len(known)}


def _summary(trades, positions, violations) -> dict:
    bad_sells = {v["fill_id"] for v in violations}
    bad_trades = [t for t in trades if t["buy_id"] in bad_sells]
    unreal = [p["unrealized_net"] for p in positions if p["unrealized_net"] is not None]
    return {"all": _agg(trades), "daytrade": _agg([t for t in trades if t["daytrade"]]),
            "swing": _agg([t for t in trades if not t["daytrade"]]),
            "open_positions": len(positions), "unrealized_net": round(sum(unreal), 2) if unreal else None,
            "violations": len(violations),
            "violating_trades": {"n": len(bad_trades), "net": round(sum(t["net"] for t in bad_trades), 2)},
            "plan_slip": round(sum(t["slip_vs_plan"] for t in trades if t["slip_vs_plan"] is not None), 2)}


def _weekly(trades: list[dict], rules: dict) -> list[dict]:
    """每週當沖淨利：60% 轉入 0050；其餘進緩衝金，緩衝金超過上限的部分也轉入 0050；虧損週由緩衝金吸收。"""
    weeks: dict[str, float] = {}
    for t in trades:
        if t["daytrade"]:
            weeks[t["week"]] = weeks.get(t["week"], 0) + t["net"]
    out, cushion = [], 0.0
    for w in sorted(weeks):
        net = weeks[w]
        to_0050 = 0.0
        if net > 0:
            to_0050 = math.floor(net * rules["profit_to_0050_pct"] / 100)
            cushion += net - to_0050
            if cushion > rules["cushion_cap"]:
                to_0050 += math.floor(cushion - rules["cushion_cap"])
                cushion = float(rules["cushion_cap"])
        else:
            cushion = max(0.0, cushion + net)
        out.append({"week": w, "daytrade_net": round(net, 2), "to_0050": to_0050, "cushion_after": round(cushion, 2)})
    return out


def _equity(trades: list[dict]) -> list[dict]:
    """依出場日累計：你的淨損益 vs 影子 0050。"""
    days: dict[str, list[float]] = {}
    for t in trades:
        d = days.setdefault(t["close_date"], [0.0, 0.0])
        d[0] += t["net"]
        d[1] += t["shadow_0050"] or 0.0
    out, a, b = [], 0.0, 0.0
    for d in sorted(days):
        a += days[d][0]
        b += days[d][1]
        out.append({"date": d, "net": round(a, 2), "shadow_0050": round(b, 2)})
    return out
