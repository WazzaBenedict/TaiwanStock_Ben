"""Intraday bars for Taiwan stocks: FinMind 1-minute K bars -> 5-minute sessions.

A Taiwan regular session runs 09:00-13:30 Asia/Taipei. Continuous trading ends at
13:25 and 13:25-13:30 is the closing call auction. With 5-minute bars labelled by
their start time that is 54 bars: 09:00, 09:05, ... 13:25 (the last one holds the
closing auction print).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
BAR_MINUTES = 5
SESSION_OPEN = dt.time(9, 0)
SESSION_BARS = 54  # 09:00 .. 13:25 bar starts
CACHE_DIR = Path(os.getenv("DAYTRADE_CACHE_DIR", Path(__file__).resolve().parent / "cache"))


class DataError(Exception):
    pass


class TierError(DataError):
    """FinMind refused the request because of the account level or quota."""
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def bar_index(t: dt.time) -> int:
    """Index of the 5-minute bar (by start time) that a bar starting at `t` belongs to."""
    mins = (t.hour * 60 + t.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    return mins // BAR_MINUTES


def bar_time(idx: int) -> str:
    mins = SESSION_OPEN.hour * 60 + SESSION_OPEN.minute + idx * BAR_MINUTES
    return "%02d:%02d" % (mins // 60, mins % 60)


def parse_hhmm(s: str) -> int:
    """'10:15' or '10:15:00' -> bar index."""
    parts = [int(x) for x in str(s).strip().split(":")[:2]]
    return bar_index(dt.time(parts[0], parts[1]))


def minute_rows_to_bars(rows: list[dict]) -> list[list[float] | None]:
    """Aggregate one day's 1-minute rows into 54 five-minute [o,h,l,c,v] bars.

    FinMind's `minute` field is the bar's clock label. Feeds differ on whether that is
    the start or the end of the minute; if the first label of the day is 09:01 we treat
    labels as end times and shift them back one minute. Missing bars stay None.
    """
    pts = []
    for r in rows:
        m = str(r.get("minute") or r.get("time") or "")
        if not m:
            continue
        hh, mm = int(m[0:2]), int(m[3:5])
        pts.append((hh * 60 + mm, r))
    if not pts:
        return [None] * SESSION_BARS
    pts.sort(key=lambda x: x[0])
    shift = 1 if pts[0][0] == 9 * 60 + 1 else 0
    bars: list[list[float] | None] = [None] * SESSION_BARS
    for mins, r in pts:
        start = mins - shift
        idx = (start - 9 * 60) // BAR_MINUTES
        if start >= 13 * 60 + 30 and start <= 13 * 60 + 33:
            idx = SESSION_BARS - 1  # closing auction print stamped 13:30
        if idx < 0 or idx >= SESSION_BARS:
            continue
        o, h, l, c = (float(r.get(k) or 0) for k in ("open", "high", "low", "close"))
        v = float(r.get("volume") or 0)
        if min(o, h, l, c) <= 0:
            continue
        b = bars[idx]
        if b is None:
            bars[idx] = [o, h, l, c, v]
        else:
            b[1] = max(b[1], h)
            b[2] = min(b[2], l)
            b[3] = c
            b[4] += v
    return bars


def fill_quiet_bars(bars: list[list[float] | None], max_gaps: int = 3) -> list[list[float]] | None:
    """Thin stocks can have 5-minute bars with no trade. Fill up to `max_gaps` such bars
    with a flat bar at the previous close; reject the day if more are missing or the
    first bar is missing."""
    if not bars or bars[0] is None:
        return None
    out, gaps = [], 0
    for b in bars:
        if b is None:
            gaps += 1
            if gaps > max_gaps:
                return None
            pc = out[-1][3]
            out.append([pc, pc, pc, pc, 0.0])
        else:
            out.append(list(b))
    return out


def fetch_finmind_day(stock_id: str, date: str, token: str | None = None, timeout: int = 20) -> list[dict]:
    q = {"dataset": "TaiwanStockKBar", "data_id": stock_id, "start_date": date}
    url = FINMIND_URL + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "taiwanstock-daytrade/1.0"})
    token = token or os.getenv("FINMIND_TOKEN", "")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # 400/402/403 = account level, 429 = quota
        msg = ""
        try:
            msg = json.loads(e.read().decode("utf-8")).get("msg", "")
        except Exception:
            pass
        raise TierError("FinMind %s %s: HTTP %s %s" % (stock_id, date, e.code, msg or e.reason),
                        e.code) from e
    except Exception as e:  # network
        raise DataError("FinMind %s %s: %s" % (stock_id, date, e)) from e
    if payload.get("status") not in (200, None):
        raise DataError("FinMind %s %s: %s" % (stock_id, date, payload.get("msg")))
    return [r for r in payload.get("data", []) if str(r.get("date", ""))[:10] == date]


def load_sessions_finmind(stock_id: str, end_date: str, days: int = 60, token: str | None = None,
                          use_cache: bool = True, pause: float = 0.3) -> dict[str, list[list[float]]]:
    """Up to `days` trading sessions ending on `end_date` (inclusive), as 5-minute bars.

    Walks back over calendar days (weekends skipped) until enough non-empty sessions
    are found or 2x`days` weekdays were tried. Days already in the cache are not
    re-fetched; today's date is never cached because the session may be incomplete.
    """
    end = dt.date.fromisoformat(end_date)
    today = dt.date.today()
    sessions: dict[str, list[list[float]]] = {}
    tried, d = 0, end
    errors = []
    while len(sessions) < days and tried < days * 2:
        if d.weekday() < 5:
            tried += 1
            ds = d.isoformat()
            cpath = CACHE_DIR / stock_id / (ds + ".json")
            rows = None
            if use_cache and cpath.exists():
                rows = json.loads(cpath.read_text(encoding="utf-8"))
            else:
                try:
                    rows = fetch_finmind_day(stock_id, ds, token)
                except TierError:
                    raise  # every other day will fail the same way
                except DataError as e:
                    errors.append(str(e))
                    if len(errors) >= 5 and not sessions:
                        raise DataError("; ".join(errors[:3]))
                    rows = None
                if rows is not None and use_cache and d < today:
                    cpath.parent.mkdir(parents=True, exist_ok=True)
                    cpath.write_text(json.dumps(rows), encoding="utf-8")
                time.sleep(pause)
            if rows:
                bars = fill_quiet_bars(minute_rows_to_bars(rows))
                if bars is not None:
                    sessions[ds] = bars
        d -= dt.timedelta(days=1)
    return dict(sorted(sessions.items()))


LAST_SOURCE = {"name": ""}  # which feed the last load_sessions call used
YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m"


def parse_yahoo_chart(payload: dict, end_date: str | None = None) -> dict[str, list[list[float]]]:
    """Yahoo v8 chart JSON (5-minute) -> {date: 54 bars}. Timestamps are bar starts in
    UTC; the exchange offset comes from meta.gmtoffset (Taipei = +8h). A bar stamped
    13:25 or later (the closing auction) is merged into the last bar."""
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        err = (payload.get("chart") or {}).get("error") or {}
        raise DataError("Yahoo: %s" % (err.get("description") or "no data"))
    r0 = res[0]
    off = int((r0.get("meta") or {}).get("gmtoffset") or 28800)
    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    by_day: dict[str, list] = {}
    for i, t in enumerate(ts):
        o, h, l, c = (q.get(k, [None] * len(ts))[i] for k in ("open", "high", "low", "close"))
        v = (q.get("volume") or [0] * len(ts))[i] or 0
        if None in (o, h, l, c) or min(o, h, l, c) <= 0:
            continue
        local = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).replace(tzinfo=None)
        ds = local.date().isoformat()
        if end_date and ds > end_date:
            continue
        idx = min(bar_index(local.time()), SESSION_BARS - 1)
        if idx < 0:
            continue
        bars = by_day.setdefault(ds, [None] * SESSION_BARS)
        b = bars[idx]
        if b is None:
            bars[idx] = [float(o), float(h), float(l), float(c), float(v)]
        else:
            b[1], b[2], b[3], b[4] = max(b[1], h), min(b[2], l), float(c), b[4] + v
    out = {}
    for ds, bars in sorted(by_day.items()):
        full = fill_quiet_bars(bars)
        if full is not None:
            out[ds] = full
    return out


def load_sessions_yahoo(stock_id: str, end_date: str, timeout: int = 20) -> dict[str, list[list[float]]]:
    """Free fallback: Yahoo keeps about 60 days of 5-minute bars. Tries the TWSE suffix
    (.TW) and then TPEx (.TWO). Unofficial and can lag or have gaps."""
    last = None
    for suffix in (".TW", ".TWO"):
        url = YAHOO_URL % urllib.parse.quote(stock_id + suffix)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (taiwanstock-daytrade/1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = parse_yahoo_chart(json.loads(r.read().decode("utf-8")), end_date)
            if out:
                return out
        except Exception as e:
            last = e
    raise DataError("Yahoo %s: %s" % (stock_id, last or "no 5-minute data"))


def load_sessions(stock_id: str, end_date: str, days: int = 60, token: str | None = None,
                  source: str = "auto") -> dict[str, list[list[float]]]:
    """source: "finmind", "yahoo", or "auto" = FinMind when a token is set, falling back
    to Yahoo when FinMind refuses the account level (minute bars are a sponsor-tier
    dataset) or when no token is set."""
    token = token or os.getenv("FINMIND_TOKEN", "")
    LAST_SOURCE["name"] = "yahoo"
    if source == "yahoo" or (source == "auto" and not token):
        return load_sessions_yahoo(stock_id, end_date)
    try:
        out = load_sessions_finmind(stock_id, end_date, days, token)
        LAST_SOURCE["name"] = "finmind"
        return out
    except TierError:
        if source == "finmind":
            raise
        return load_sessions_yahoo(stock_id, end_date)


def load_offline(path: str) -> dict[str, list[list[float]]]:
    """Offline file: either {"YYYY-MM-DD": [[o,h,l,c,v], ... 54 bars]} or a FinMind
    TaiwanStockKBar payload ({"data": [...]}) or a plain list of FinMind rows."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "data" not in raw:
        return {k: v for k, v in sorted(raw.items()) if v and len(v) == SESSION_BARS}
    rows = raw["data"] if isinstance(raw, dict) else raw
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(str(r["date"])[:10], []).append(r)
    out = {}
    for ds, rs in sorted(by_day.items()):
        bars = fill_quiet_bars(minute_rows_to_bars(rs))
        if bars is not None:
            out[ds] = bars
    return out
