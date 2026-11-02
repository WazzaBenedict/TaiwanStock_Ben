"""FastAPI routes for the day-trade research tools. Mounted in app.py."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from .costs import DayTradeCosts
from .data import DataError
from . import timemachine as tm

router = APIRouter(prefix="/api/daytrade", tags=["daytrade"])


@router.get("/timemachine")
def timemachine(
    stock_id: str = Query(..., description="e.g. 2330"),
    date: str = Query(..., description="YYYY-MM-DD, a completed session"),
    entry: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    entry_time: str | None = Query(None, description="HH:MM, manual plan only"),
    orb_minutes: int = Query(15, ge=5, le=60),
    target_r: float = Query(1.0, gt=0, le=5),
    stop_rule: str = Query("orb_mid", pattern="^(orb_mid|orb_low)$"),
    shares: int = Query(1000, ge=1, le=1_000_000),
    fee_discount: float = Query(0.6, ge=0, le=1),
    slip_ticks: int = Query(1, ge=0, le=5),
    replays: int = Query(10000, ge=100, le=20000),
    seed: int = tm.DEFAULT_SEED,
    days: int = Query(60, ge=20, le=120),
):
    """Sync def: FastAPI runs it in a worker thread, so the FinMind calls don't block the loop."""
    if not re.fullmatch(r"\d{4,6}[A-Z]?", stock_id) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "stock_id 或 date 格式錯誤")
    try:
        return tm.run(
            stock_id, date, entry=entry, stop=stop, target=target, entry_time=entry_time,
            rule=tm.Rule(orb_minutes, target_r, stop_rule),
            costs=DayTradeCosts(fee_discount=fee_discount, slip_ticks=slip_ticks),
            shares=shares, replays=replays, seed=seed, days=days,
        )
    except tm.TMError as e:
        raise HTTPException(422, str(e))
    except DataError as e:
        raise HTTPException(502, "分 K 資料取得失敗（FinMind 可能需要付費等級的 token，或配額用完）：%s" % e)
