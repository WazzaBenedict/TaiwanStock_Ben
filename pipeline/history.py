"""開盤預估命中紀錄：每天盤前記下預估，收盤後填入實際，累計命中率並對照基準。

基準＝「永遠猜跟費半同方向」。預估若贏不了這個基準，就沒有額外價值。
紀錄存在 Firestore（cloudstore），GitHub Actions 每次執行都是全新機器，所以先拉回再寫入。
"""
from __future__ import annotations

import json
from pathlib import Path

import cloudstore

LOG_FILE = Path(__file__).resolve().parent / "today_log.json"
MAX_ROWS = 400


def _sign(v) -> int:
    return 0 if v is None or abs(v) < 0.05 else (1 if v > 0 else -1)


def update(log: list[dict], snap: dict) -> list[dict]:
    """把這次快照寫進紀錄（同一天只留一筆預估；有實際值就補上）。"""
    rows = {r["date"]: dict(r) for r in log}
    day = snap["generated_at"][:10]
    gap = snap.get("gap_estimate") or {}
    if snap.get("phase") == "premarket" and gap.get("ok"):
        sox = next((o["chg_pct"] for o in (snap.get("overnight") or {}).get("us", []) if o["symbol"] == "^SOX"), None)
        rows[day] = {"date": day, "pred_pct": gap["pct"], "basis": gap.get("basis"), "sox_pct": sox,
                     "actual_pct": rows.get(day, {}).get("actual_pct")}
    act = snap.get("actual") or {}
    if act.get("gap_pct") is not None and act.get("date") in rows:
        rows[act["date"]]["actual_pct"] = act["gap_pct"]
    return [rows[k] for k in sorted(rows)][-MAX_ROWS:]


def summarize(log: list[dict]) -> dict:
    done = [r for r in log if r.get("actual_pct") is not None and _sign(r["actual_pct"]) != 0]
    hit = sum(1 for r in done if _sign(r.get("pred_pct")) == _sign(r["actual_pct"]))
    base = sum(1 for r in done if _sign(r.get("sox_pct")) == _sign(r["actual_pct"]))
    err = [abs(r["pred_pct"] - r["actual_pct"]) for r in done if r.get("pred_pct") is not None]
    n = len(done)
    return {"n": n, "hits": hit, "baseline_hits": base,
            "hit_rate_pct": round(hit / n * 100) if n else None,
            "baseline_rate_pct": round(base / n * 100) if n else None,
            "mean_abs_error_pct": round(sum(err) / len(err), 2) if err else None,
            "recent": log[-10:][::-1],
            "note": "基準＝永遠猜與費半同方向；樣本少於 30 天時不要下結論"}


def load() -> list[dict]:
    cloudstore.pull(LOG_FILE)
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8")).get("rows", [])
    except Exception:
        return []


def save(log: list[dict]) -> bool:
    LOG_FILE.write_text(json.dumps({"rows": log}, ensure_ascii=False), encoding="utf-8")
    return cloudstore.push(LOG_FILE)
