"""FastAPI routes for the day-trade research tools. Mounted in app.py."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query

from .costs import DayTradeCosts, DEFAULT_DISCOUNT
from .data import DataError
from . import timemachine as tm
from . import screener

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
    fee_discount: float = Query(DEFAULT_DISCOUNT, ge=0, le=1),
    slip_ticks: int = Query(1, ge=0, le=5),
    replays: int = Query(10000, ge=100, le=20000),
    seed: int = tm.DEFAULT_SEED,
    days: int = Query(60, ge=20, le=120),
    source: str = Query("auto", pattern="^(auto|finmind|yahoo)$"),
):
    """Sync def: FastAPI runs it in a worker thread, so the FinMind calls don't block the loop."""
    if not re.fullmatch(r"\d{4,6}[A-Z]?", stock_id) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise HTTPException(400, "stock_id 或 date 格式錯誤")
    try:
        return tm.run(
            stock_id, date, entry=entry, stop=stop, target=target, entry_time=entry_time,
            rule=tm.Rule(orb_minutes, target_r, stop_rule),
            costs=_tm_costs(stock_id, fee_discount, slip_ticks),
            shares=shares, replays=replays, seed=seed, days=days, source=source,
        )
    except tm.TMError as e:
        raise HTTPException(422, str(e))
    except DataError as e:
        raise HTTPException(502, "分 K 資料取得失敗（FinMind 分 K 需要贊助會員，免費改用 Yahoo 只有近 60 天）：%s" % e)


def _tm_costs(stock_id: str, fee_discount: float, slip_ticks: int) -> DayTradeCosts:
    """ETF 當沖沒有減半，證交稅照 ETF 稅率（0.1%，債券 ETF 依 twcosts）；一般股票用當沖 0.15%。"""
    from twcosts import BrokerFees, is_etf
    etf = is_etf(stock_id)
    if etf:
        return DayTradeCosts(fee_discount=fee_discount, slip_ticks=slip_ticks, tax_rate=BrokerFees().tax_rate(etf))
    return DayTradeCosts(fee_discount=fee_discount, slip_ticks=slip_ticks)


@router.get("/screen")
def screen(
    top: int = Query(40, ge=10, le=80),
    orb_minutes: int = Query(15, ge=5, le=60),
    target_r: float = Query(1.0, gt=0, le=5),
    fee_discount: float = Query(DEFAULT_DISCOUNT, ge=0, le=1),
    slip_ticks: int = Query(1, ge=0, le=5),
    refresh: bool = False,
):
    """Day-trade candidates (long only), each with after-cost history vs a random-entry
    control. Cached per day; the first call fetches ~2 Yahoo requests per stock."""
    try:
        return screener.screen(top, tm.Rule(orb_minutes, target_r),
                               DayTradeCosts(fee_discount=fee_discount, slip_ticks=slip_ticks),
                               use_cache=not refresh)
    except DataError as e:
        raise HTTPException(502, "掃描資料取得失敗：%s" % e)
    except Exception as e:  # TWSE endpoints down or changed format
        raise HTTPException(502, "掃描失敗：%s" % e)


@router.get("/levels")
def levels(
    ids: str = Query(..., description="comma-separated stock ids, max 10"),
    orb_minutes: int = Query(15, ge=5, le=60),
    target_r: float = Query(1.0, gt=0, le=5),
    shares: int = Query(1000, ge=1, le=1_000_000),
    fee_discount: float = Query(DEFAULT_DISCOUNT, ge=0, le=1),
    slip_ticks: int = Query(1, ge=0, le=5),
):
    """Today's entry / stop-loss / take-profit for each stock under the opening-range rule."""
    lst = [x.strip() for x in ids.split(",") if x.strip()][:10]
    if not lst or not all(re.fullmatch(r"\d{4,6}[A-Z]?", x) for x in lst):
        raise HTTPException(400, "ids 格式錯誤")
    return screener.live_levels(lst, tm.Rule(orb_minutes, target_r),
                                DayTradeCosts(fee_discount=fee_discount, slip_ticks=slip_ticks), shares)
