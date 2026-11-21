"""帳本 API。行情抓取函式由 app.py 注入，這裡不直接連網，方便測試。"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Body, HTTPException

from . import core, importer

MAX_FILLS = 5000
MAX_OPEN_CODES = 20
BARS_TTL = 1800


def make_router(fetch_history, name_to_code=None) -> APIRouter:
    """fetch_history(code, lookback_days) -> (DataFrame[日期, 開盤價, 收盤價...], source)"""
    router = APIRouter(prefix="/api/ledger", tags=["ledger"])
    cache: dict[str, tuple[dict, float]] = {}

    async def bars(code: str, days: int) -> dict:
        hit = cache.get(code)
        if hit and time.time() - hit[1] < BARS_TTL and hit[0].get("_days", 0) >= days:
            return hit[0]
        out = {"_days": days}
        try:
            df, _ = await fetch_history(code, days)
            for _, r in df.iterrows():
                try:
                    c = float(r["收盤價"])
                    o = float(r["開盤價"]) if "開盤價" in df.columns and r["開盤價"] == r["開盤價"] else c
                    # 有還原收盤價（含股利）就用它，開盤價同比例調整；除息日不會被當成下跌
                    a = float(r["還原收盤價"]) if "還原收盤價" in df.columns and r["還原收盤價"] == r["還原收盤價"] else c
                    if c > 0 and a > 0:
                        f = a / c
                        o = o if o > 0 else c
                        out[str(r["日期"])[:10]] = {"o": o * f, "c": a}
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass
        if len(out) > 1:
            cache[code] = (out, time.time())
        return out

    @router.post("/compute")
    async def compute(payload: dict = Body(default={})):
        fills = payload.get("fills") or []
        if not isinstance(fills, list) or len(fills) > MAX_FILLS:
            raise HTTPException(400, detail=f"成交紀錄格式錯誤或超過 {MAX_FILLS} 筆")
        disc = payload.get("fee_discount")
        try:
            disc = float(disc) if disc is not None else None
            if disc is not None and not (0 < disc <= 1):
                disc = None
        except (TypeError, ValueError):
            disc = None
        raw_rules = payload.get("rules")
        rules = {k: v for k, v in (raw_rules if isinstance(raw_rules, dict) else {}).items() if k in core.DEFAULT_RULES}
        rows, _ = core.normalize(fills)
        days = 400
        if rows:
            from datetime import date
            days = max(60, (date.today() - date.fromisoformat(rows[0]["date"])).days + 30)
        b0050 = await bars("0050", min(days, 3650))
        b = {k: v for k, v in b0050.items() if k != "_days"}
        first = core.compute(fills, b, None, disc, rules)
        codes = sorted({p["code"] for p in first["positions"]})[:MAX_OPEN_CODES]
        last = {}
        if codes:
            got = await asyncio.gather(*[bars(c, 15) for c in codes])
            for c, g in zip(codes, got):
                ds = [k for k in g if k != "_days"]
                if ds:
                    last[c] = g[max(ds)]["c"]
        out = core.compute(fills, b, last, disc, rules) if last else first
        out["data"] = {"bars_0050": len(b), "last_0050_date": max(b) if b else None,
                       "missing_last_price": [c for c in codes if c not in last]}
        if not b:
            out["notes"].insert(0, "暫時抓不到 0050 日線，影子 0050 這次無法計算。")
        return out

    @router.post("/import")
    async def import_text(payload: dict = Body(default={})):
        text = payload.get("text") or ""
        if not isinstance(text, str) or len(text) > 2_000_000:
            raise HTTPException(400, detail="內容格式錯誤或檔案超過 2MB")
        return importer.parse(text, payload.get("default_date"), name_to_code)

    return router
