"""每日報告存檔：每次排程把「今日」快照整理成當天的盤前／收盤報告，累積成 public/data/reports.json。

用法：python -m pipeline.report [today.json] [輸出檔]
- 盤前（交易日 09:00 前）：存結論、開盤預估、風險燈、隔夜、觀察名單、新聞標題，並算出當沖 5 檔候選。
- 收盤（13:35 後且當天有成交）：存 0050 實際開盤與收盤、觀察名單收盤，並替當天的候選對答案。
- 歷史存在 Firestore（cloudstore），因為 GitHub Actions 每次都是全新機器。任何一段失敗都不影響其他段。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import cloudstore
from pipeline import picks as P

TPE = timezone(timedelta(hours=8))
STORE = Path(__file__).resolve().parent / "reports.json"
MAX_DAYS = 60


def phase(now: datetime) -> str | None:
    if now.weekday() >= 5:
        return None
    hm = (now.hour, now.minute)
    return "pre" if hm < (9, 0) else ("close" if hm >= (13, 35) else None)


def pre_section(snap: dict) -> dict:
    g, r, ov = snap.get("gap_estimate") or {}, snap.get("risk") or {}, snap.get("overnight") or {}
    night = ov.get("night") or {}
    return {
        "at": snap.get("generated_at"), "conclusion": snap.get("conclusion"),
        "gap": {"ok": bool(g.get("ok")), "pct": g.get("pct"), "note": g.get("note")},
        "risk": {k: r.get(k) for k in ("ok", "color", "label", "text", "dist_ma200_pct", "vol20_pct")},
        "overnight": [{"name": x["name"], "chg_pct": x["chg_pct"]} for x in ov.get("us") or []]
                     + ([{"name": "台指期夜盤", "chg_pct": night.get("pct")}] if night.get("fresh") else []),
        "watchlist": [{k: w.get(k) for k in ("code", "close", "chg_pct", "dist_ma200_pct", "vol20_pct", "rev_yoy_pct", "disposition")}
                      for w in snap.get("watchlist") or []],
        "news": [n.get("title") for n in (snap.get("news") or [])[:8]],
    }


def close_section(snap: dict, day: str) -> dict | None:
    act = snap.get("actual") or {}
    if act.get("date") != day:
        return None
    return {"at": snap.get("generated_at"), "gap_pct": act.get("gap_pct"), "close_chg_pct": act.get("close_chg_pct"),
            "watchlist": [{k: w.get(k) for k in ("code", "close", "chg_pct")} for w in snap.get("watchlist") or [] if w.get("date") == day]}


def update(arch: dict, snap: dict, now: datetime, picks: dict | None = None, results: list[dict] | None = None) -> dict:
    """純函式：把這次的資料併進存檔。同一天重跑只會更新，不會重複。"""
    days = {d["date"]: dict(d) for d in arch.get("days", [])}
    day, ph = now.date().isoformat(), phase(now)
    if ph == "pre":
        e = days.setdefault(day, {"date": day})
        e["pre"] = pre_section(snap)
        if picks and picks.get("items") and not e.get("picks"):
            e["picks"] = picks
    elif ph == "close":
        sec = close_section(snap, day)
        if sec:
            e = days.setdefault(day, {"date": day})
            e["close"] = sec
            if results:   # 19:00 收盤價定稿時重算，蓋掉 13:45 的初步結果
                e["results"] = results
    ordered = [days[k] for k in sorted(days, reverse=True)][:MAX_DAYS]
    keep = all_results({"results_all": arch.get("results_all"), "days": list(days.values())})
    done = [r for k in sorted(keep) for r in keep[k]]
    out = {"schema": 1, "updated_at": now.isoformat(timespec="seconds"), "days": ordered, "results_all": keep,
            "picks_totals": P.totals(done), "picks_days": len(keep),
            "picks_rule": {"version": P.VERSION, "note": "模擬追蹤，不是買賣建議。A 版回測扣成本後為負；B 版（開盤跌 1% 以上才買）要累積 100 筆以上才下結論。每檔 1 張，成本用元大費率。"}}
    if arch.get("next_picks"):
        out["next_picks"] = arch["next_picks"]
    return out


def target_day(now: datetime) -> str:
    """下一份當沖候選是給哪一天用的：交易日 09:00 前是今天，否則是下一個平日（國定假日不另外判斷）。"""
    d = now.date()
    if now.weekday() < 5 and (now.hour, now.minute) < (9, 0):
        return d.isoformat()
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def place_next_picks(arch: dict, today: str) -> dict:
    """純函式：next_picks 的日期到了（或已過），就放進那一天的報告；尚未到的留著給畫面顯示「下個交易日」。"""
    np = arch.get("next_picks")
    if not np or np.get("for_date", "9999") > today:
        return arch
    days = {d["date"]: dict(d) for d in arch.get("days", [])}
    e = days.setdefault(np["for_date"], {"date": np["for_date"]})
    if not e.get("picks"):
        e["picks"] = {k: v for k, v in np.items() if k != "for_date"}
    out = dict(arch, days=[days[k] for k in sorted(days, reverse=True)][:MAX_DAYS])
    out.pop("next_picks", None)
    return out


def all_results(arch: dict) -> dict:
    """累計成績不受 60 天保存上限影響：每天的對答案另外留一份（date -> results）。"""
    keep = dict(arch.get("results_all") or {})
    for d in arch.get("days", []):
        if d.get("results"):
            keep[d["date"]] = d["results"]
    return keep


def score_day(entry: dict, day: str) -> list[dict]:
    out = []
    with httpx.Client(timeout=30, headers=P.UA, follow_redirects=True) as cl:
        for p in (entry.get("picks") or {}).get("items") or []:
            try:
                bar = next((b for b in P.daily(cl, p["code"], p["mkt"], "1mo") if b["d"] == day), None)
                if bar:
                    out.append(P.score(p, bar))
            except Exception as e:
                print("score failed", p["code"], type(e).__name__, str(e)[:80])
    return out


LIVE = "https://taiwanstock-ben.web.app/data/reports.json"


def load() -> dict:
    """先從 Firestore 拉；拉不到就用線上那份，避免把歷史洗掉。"""
    cloudstore.pull(STORE)
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        r = httpx.get(LIVE, timeout=30, follow_redirects=True)
        if r.status_code == 200 and isinstance(r.json().get("days"), list):
            return r.json()
    except Exception:
        pass
    return {"days": []}


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    src = Path(argv[1]) if len(argv) > 1 else root / "public" / "data" / "today.json"
    out = Path(argv[2]) if len(argv) > 2 else root / "public" / "data" / "reports.json"
    now = datetime.now(TPE)
    arch = load()
    try:
        snap = json.loads(src.read_text(encoding="utf-8"))
        if snap.get("generated_at", "")[:10] != now.date().isoformat():
            snap = None   # 快照不是今天產生的（例如沿用舊檔），不能當今天的報告
    except Exception:
        snap = None
    # 舊的候選還沒有個股回測就補上（只補最近一天，約 5 次抓取）
    for d in (arch.get("days") or [])[:1]:
        items = (d.get("picks") or {}).get("items") or []
        if items and any("bt" not in x for x in items):
            try:
                P.attach_bt(items)
            except Exception as e:
                print("bt backfill failed:", type(e).__name__, str(e)[:120])
    # 當沖 5 檔：收盤後（或隔天清晨）就先算好「下個交易日」的候選。
    # GitHub 的定時工作常延後好幾個小時，不能只靠 06:50 那一次。
    tday = target_day(now)
    have = any(d.get("date") == tday and d.get("picks") for d in arch.get("days", [])) \
        or (arch.get("next_picks") or {}).get("for_date") == tday
    after_close = now.weekday() < 5 and (now.hour, now.minute) >= (13, 35)
    if not have and (after_close or tday == now.date().isoformat() or now.weekday() >= 5):
        try:
            picks = P.build()
            if picks.get("items"):
                arch["next_picks"] = dict(picks, for_date=tday)
                print("picks built for", tday, "from", picks.get("signal_date"), [x["code"] for x in picks["items"]])
            else:
                print("picks empty: universe", picks.get("universe_n"))
        except Exception as e:
            print("picks failed:", type(e).__name__, str(e)[:160])
    arch = place_next_picks(arch, now.date().isoformat())
    if snap:
        day, ph = now.date().isoformat(), phase(now)
        entry = next((d for d in arch.get("days", []) if d["date"] == day), {})
        picks = results = None
        if ph == "close" and entry.get("picks"):
            results = score_day(entry, day) or None
        arch = update(arch, snap, now, picks, results)
    text = json.dumps(arch, ensure_ascii=False, separators=(",", ":"))
    STORE.write_text(text, encoding="utf-8")
    print("reports stored:", cloudstore.push(STORE), "days:", len(arch.get("days", [])))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
