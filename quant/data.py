"""回測用資料載入。

來源：
- FinMind（api.finmindtrade.com）：TaiwanStockInfo、TaiwanStockPrice、TaiwanStockMonthRevenue、
  TaiwanStockInstitutionalInvestorsBuySell、TaiwanStockDelisting。免費未登入每小時約 300 次，
  可設環境變數 FINMIND_TOKEN 提高額度。
- 全市場快速路徑（避免一檔一檔打 FinMind 被限流）：
  - Yahoo Finance 日線（含 adjclose，用來算含息報酬），只有「目前仍上市」的股票
  - 公開資訊觀測站每月營收彙總表（一個月一個檔，涵蓋當月所有上市公司）
  - 證交所 T86 三大法人買賣超日報（一天一個檔，涵蓋全部上市股票）
  下市股票 Yahoo 抓不到，改用 FinMind TaiwanStockPrice，讓下市股留在樣本裡（避免倖存者偏差）。

所有下載結果都快取在 QUANT_CACHE_DIR（預設 repo 根目錄的 data_cache/，已加入 .gitignore）。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
MOPS_REVENUE_URL = "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_{roc}_{month}_0.html"
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

CACHE_DIR = Path(os.getenv("QUANT_CACHE_DIR", Path(__file__).resolve().parent.parent / "data_cache"))
UA = {"User-Agent": "Mozilla/5.0"}


def _cache_path(*parts: str) -> Path:
    p = CACHE_DIR.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _cached(path: Path, fetch, max_age_days: float | None = None) -> pd.DataFrame:
    """讀快取；沒有（或過期）才呼叫 fetch() 並寫入。"""
    if path.exists():
        fresh = max_age_days is None or (time.time() - path.stat().st_mtime) < max_age_days * 86400
        if fresh:
            return pd.read_pickle(path)
    df = fetch()
    df.to_pickle(path)
    return df


def _get(url: str, params: dict | None = None, retries: int = 4, timeout: int = 30) -> requests.Response:
    last: Exception | None = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            last = e
        time.sleep(2 ** (i + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


# ── FinMind ──────────────────────────────────────────────────────────────────
def finmind(dataset: str, data_id: str | None = None, start: str | None = None, end: str | None = None,
            retries: int = 6) -> pd.DataFrame:
    """呼叫 FinMind v4；遇到額度用完會等待後重試。"""
    params = {"dataset": dataset}
    if data_id:
        params["data_id"] = data_id
    if start:
        params["start_date"] = start
    if end:
        params["end_date"] = end
    token = os.getenv("FINMIND_TOKEN")
    if token:
        params["token"] = token
    for i in range(retries):
        try:
            r = requests.get(FINMIND_URL, params=params, headers=UA, timeout=60)
            js = r.json()
        except (requests.RequestException, ValueError):
            time.sleep(2 ** (i + 1))
            continue
        if js.get("status") == 200 or js.get("msg") == "success":
            return pd.DataFrame(js.get("data", []))
        msg = str(js.get("msg", ""))
        if "upper limit" in msg.lower() or r.status_code == 402:
            time.sleep(min(600, 60 * (i + 1)))   # 每小時額度用完：等一下再試
            continue
        raise RuntimeError(f"FinMind {dataset} {data_id}: {msg}")
    raise RuntimeError(f"FinMind {dataset} {data_id}: retries exhausted")


def load_stock_info() -> pd.DataFrame:
    return _cached(_cache_path("finmind", "stock_info.pkl"), lambda: finmind("TaiwanStockInfo"), max_age_days=7)


def load_delisting() -> pd.DataFrame:
    def fetch():
        df = finmind("TaiwanStockDelisting")
        df["date"] = pd.to_datetime(df["date"])
        return df
    return _cached(_cache_path("finmind", "delisting.pkl"), fetch, max_age_days=7)


def load_price_finmind(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """未還原日線：date, open, close, volume, value（成交金額）。"""
    def fetch():
        df = finmind("TaiwanStockPrice", stock_id, start, end)
        if df.empty:
            return pd.DataFrame(columns=["open", "close", "volume", "value"])
        df["date"] = pd.to_datetime(df["date"])
        out = df.set_index("date")[["open", "close", "Trading_Volume", "Trading_money"]]
        out.columns = ["open", "close", "volume", "value"]
        return out[out["close"] > 0]
    return _cached(_cache_path("finmind", "price", f"{stock_id}_{start}_{end}.pkl"), fetch)


def load_month_revenue_finmind(stock_id: str, start: str, end: str) -> pd.Series:
    """月營收，index = 營收「所屬月份」的月初。

    注意 FinMind 的 date 欄是公告月份（例如 2023 年 12 月營收的 date 是 2024-01-01），
    這裡改用 revenue_year / revenue_month，公告延遲交給 factors.revenue_yoy 處理。
    """
    def fetch():
        df = finmind("TaiwanStockMonthRevenue", stock_id, start, end)
        if df.empty:
            return pd.Series(dtype=float)
        idx = pd.to_datetime(dict(year=df["revenue_year"], month=df["revenue_month"], day=1))
        return pd.Series(df["revenue"].astype(float).values, index=idx).sort_index()
    return _cached(_cache_path("finmind", "revenue", f"{stock_id}_{start}_{end}.pkl"), fetch)


def load_institutional_finmind(stock_id: str, start: str, end: str) -> pd.Series:
    """三大法人合計買賣超股數（日）。"""
    def fetch():
        df = finmind("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start, end)
        if df.empty:
            return pd.Series(dtype=float)
        df["date"] = pd.to_datetime(df["date"])
        df["net"] = df["buy"].astype(float) - df["sell"].astype(float)
        return df.groupby("date")["net"].sum()
    return _cached(_cache_path("finmind", "inst", f"{stock_id}_{start}_{end}.pkl"), fetch)


# ── 全市場快速路徑 ────────────────────────────────────────────────────────────
def load_price_yahoo(stock_id: str, start: str, end: str) -> pd.DataFrame:
    """Yahoo 日線：open/close 為「還原（含息）」價格，value 用未還原收盤 × 成交量。"""
    def fetch():
        p1 = int(pd.Timestamp(start).timestamp())
        p2 = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
        try:
            r = _get(YAHOO_URL.format(sym=f"{stock_id}.TW"),
                     {"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"}, retries=3)
            res = (r.json().get("chart", {}).get("result") or [None])[0]
        except RuntimeError:
            res = None
        if not res or not res.get("timestamp"):
            return pd.DataFrame(columns=["open", "close", "volume", "value"])
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
        idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Asia/Taipei").normalize().tz_localize(None)
        df = pd.DataFrame({"open": q["open"], "raw_close": q["close"], "adj": adj, "volume": q["volume"]},
                          index=idx, dtype=float)
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["raw_close"])
        df = df[(df["raw_close"] > 0) & (df["volume"] > 0)]
        factor = df["adj"] / df["raw_close"]
        out = pd.DataFrame({"open": df["open"] * factor, "close": df["adj"],
                            "volume": df["volume"], "value": df["raw_close"] * df["volume"]})
        return out
    return _cached(_cache_path("yahoo", f"{stock_id}_{start}_{end}.pkl"), fetch)


_MOPS_ROW = re.compile(r"<td align=center>(\d{4})</td><td align=left>[^<]*</td><td nowrap>\s*([-\d,]+)</td>")


def load_revenue_month_mops(year: int, month: int) -> pd.Series:
    """某月份所有上市公司的當月營收（千元），index=stock_id。"""
    def fetch():
        r = _get(MOPS_REVENUE_URL.format(roc=year - 1911, month=month))
        html = r.content.decode("big5", errors="ignore")
        rows = {sid: float(v.replace(",", "")) for sid, v in _MOPS_ROW.findall(html)}
        time.sleep(0.5)
        return pd.Series(rows, dtype=float)
    path = _cache_path("mops", f"rev_{year}_{month:02d}.pkl")
    # 當月檔案還可能補登，三天內重抓
    recent = pd.Timestamp(year, month, 1) > pd.Timestamp.today() - pd.DateOffset(months=2)
    return _cached(path, fetch, max_age_days=3 if recent else None)


def load_t86(date: pd.Timestamp) -> pd.Series:
    """某交易日全部上市股票的三大法人買賣超股數，index=stock_id。"""
    def fetch():
        r = _get(TWSE_T86_URL, {"date": date.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"})
        js = r.json()
        time.sleep(2.0)   # 證交所會封鎖過快的請求
        if js.get("stat") != "OK" or not js.get("data"):
            return pd.Series(dtype=float)
        fields = js["fields"]
        col = next((i for i, f in enumerate(fields) if "三大法人" in f), len(fields) - 1)
        out = {}
        for row in js["data"]:
            try:
                out[row[0].strip()] = float(str(row[col]).replace(",", ""))
            except ValueError:
                continue
        return pd.Series(out, dtype=float)
    return _cached(_cache_path("t86", f"{date:%Y%m%d}.pkl"), fetch)


# ── 組成回測 panel ────────────────────────────────────────────────────────────
def build_universe(start: str) -> pd.DataFrame:
    """上市普通股（4 碼、非 0 開頭），包含 start 之後下市的股票。

    FinMind 的 TaiwanStockInfo 會保留已下市股票，其 date 欄停在最後上市日；
    date 等於最新日期者視為目前仍上市。TaiwanStockDelisting 用來補下市日期。
    回傳欄位：stock_id, listed（目前是否仍上市）, delist_date。
    """
    info = load_stock_info()
    info = info.assign(date=pd.to_datetime(info["date"], errors="coerce"))
    twse = info[(info["type"] == "twse") & info["stock_id"].str.fullmatch(r"[1-9]\d{3}")]
    last = twse.groupby("stock_id")["date"].max()
    latest = info["date"].max()
    uni = pd.DataFrame({"stock_id": last.index, "listed": (last == latest).values,
                        "delist_date": last.where(last != latest).values})
    dl = load_delisting().drop_duplicates("stock_id", keep="last").set_index("stock_id")["date"]
    uni["delist_date"] = uni["delist_date"].fillna(uni["stock_id"].map(dl).where(~uni["listed"]))
    keep = uni["listed"] | (uni["delist_date"] >= pd.Timestamp(start)) | uni["delist_date"].isna()
    return uni[keep].reset_index(drop=True)


def build_panel(start: str, end: str, benchmark: str = "0050", with_inst: bool = True,
                inst_days_before_rebalance: int = 20, log=print) -> dict:
    """抓全市場資料並組成 factors / engine 需要的 panel。

    start 要比回測起點早至少 13 個月，讓 12 個月動能與營收年增率有足夠歷史。
    """
    uni = build_universe(start)
    # 下市股只保留曾在上市營收表出現的（排除上櫃/興櫃下市股，與現存樣本一致）
    rev_months = pd.date_range(pd.Timestamp(start) - pd.DateOffset(months=15), end, freq="MS")
    rev_cols = {}
    for m in rev_months:
        if m + pd.offsets.MonthBegin(1) + pd.Timedelta(days=10) > pd.Timestamp.today():
            continue
        try:
            rev_cols[m] = load_revenue_month_mops(m.year, m.month)
        except RuntimeError as e:
            log(f"revenue {m:%Y-%m} failed: {e}")
    revenue = pd.DataFrame(rev_cols).T.sort_index()
    ever_twse = set(revenue.columns)
    uni = uni[uni["listed"] | uni["stock_id"].isin(ever_twse)].reset_index(drop=True)
    log(f"universe: {uni['listed'].sum()} listed + {(~uni['listed']).sum()} delisted")

    opens, closes, values = {}, {}, {}
    for i, row in enumerate(uni.itertuples()):
        sid = row.stock_id
        try:
            df = load_price_yahoo(sid, start, end) if row.listed else pd.DataFrame()
            if df.empty:   # 下市股（或 Yahoo 沒資料）改用 FinMind 未還原日線
                df = load_price_finmind(sid, start, end)
        except RuntimeError as e:
            log(f"price {sid} failed: {e}")
            continue
        if df.empty:
            continue
        opens[sid], closes[sid], values[sid] = df["open"], df["close"], df["value"]
        if i % 100 == 0:
            log(f"prices {i}/{len(uni)}")
    bench = load_price_yahoo(benchmark, start, end)
    close = pd.DataFrame(closes).sort_index()
    cal = bench.index.intersection(close.index)   # 以 0050 交易日為準，剔除 Yahoo 偶發的假日資料
    close = close.reindex(cal)
    panel = {
        "close": close,
        "open": pd.DataFrame(opens).reindex(cal),
        "volume_value": pd.DataFrame(values).reindex(cal),
        "revenue": revenue.reindex(columns=close.columns),
        "benchmark_close": bench["close"].reindex(cal),
        "benchmark_open": bench["open"].reindex(cal),
        "delist_date": uni.set_index("stock_id")["delist_date"],
    }
    if with_inst:
        panel["inst_net"] = build_inst_panel(panel, inst_days_before_rebalance, log)
    return panel


def build_inst_panel(panel: dict, days_before: int, log=print) -> pd.DataFrame:
    """只抓每個月底前 days_before 個交易日的 T86（因子只用最近 20 日），換算成買賣超金額。"""
    cal = panel["close"].index
    month_ends = cal.to_series().groupby(cal.to_period("M")).max()
    need = set()
    for d in month_ends:
        pos = cal.get_loc(d)
        need.update(cal[max(0, pos - days_before + 1): pos + 1])
    need = sorted(need)
    rows = {}
    for i, d in enumerate(need):
        try:
            rows[d] = load_t86(d)
        except RuntimeError as e:
            log(f"T86 {d:%Y-%m-%d} failed: {e}")
        if i % 200 == 0:
            log(f"T86 {i}/{len(need)}")
    shares = pd.DataFrame(rows).T.reindex(columns=panel["close"].columns)
    # 法人買賣超股數 × 未還原收盤價 ≈ 買賣超金額；未還原收盤 = 成交金額 / 成交股數 不可得，
    # 用 value 與 volume 的比例較麻煩，這裡用還原價近似（比例誤差在橫斷面標準化後影響很小）
    px = panel["close"].reindex(shares.index)
    net_value = shares * px
    full = pd.DataFrame(np.nan, index=cal, columns=panel["close"].columns)
    full.loc[net_value.index] = net_value.values
    return full
