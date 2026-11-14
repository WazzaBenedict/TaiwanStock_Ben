"""對帳單／成交明細文字匯入（CSV、Tab 分隔、從網頁表格貼上的文字）。

不綁定單一券商格式：用欄位名稱比對（成交日期、代號、買賣別、成交價、股數、手續費、交易稅）。
認不出的列會回報原因，不會悄悄略過。
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import statistics

COLS = {
    "date": ["成交日期", "交易日期", "成交日", "交易日", "日期"],
    "time": ["成交時間", "交易時間", "時間"],
    "code": ["股票代號", "證券代號", "商品代號", "股票代碼", "代號", "代碼"],
    "name": ["股票名稱", "證券名稱", "商品名稱", "股票", "商品", "名稱"],
    "side": ["買賣別", "交易類別", "交易種類", "交易別", "買賣", "類別"],
    "price": ["成交價格", "成交單價", "成交均價", "成交價", "單價", "價格"],
    "shares": ["成交股數", "成交數量", "股數", "數量"],
    "lots": ["成交張數", "張數"],
    "fee": ["手續費"],
    "tax": ["交易稅", "證交稅"],
}
CODE_RE = re.compile(r"(?<![0-9A-Za-z])(\d{4,6}[A-Za-z]?)(?![0-9A-Za-z])")


def _clean(s) -> str:
    return str(s or "").replace("﻿", "").replace("　", " ").strip().strip('"').strip()


def _num(s):
    s = _clean(s).replace(",", "").replace("$", "").replace("元", "")
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(s) -> str | None:
    """2026/11/13、2026-11-13、20261113、115/11/13（民國）→ YYYY-MM-DD。"""
    s = _clean(s).split(" ")[0]
    m = re.match(r"^(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif re.match(r"^\d{8}$", s):
        y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:])
    elif re.match(r"^\d{7}$", s):
        y, mo, d = int(s[:3]), int(s[3:5]), int(s[5:])
    else:
        return None
    if y < 1911:
        y += 1911
    if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _side(s) -> str | None:
    s = _clean(s)
    low = s.lower()
    if "買" in s or low in ("b", "buy"):
        return "buy"
    if "賣" in s or low in ("s", "sell"):
        return "sell"
    return None


def _rows(text: str) -> list[list[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    head = "\n".join(text.split("\n")[:30])
    delim = "\t" if head.count("\t") >= head.count(",") and "\t" in head else ","
    return [[_clean(c) for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _header(rows) -> tuple[int, dict] | None:
    """找出標題列：至少認得日期、買賣別、價格三種欄位中的兩種，且總共認得三欄以上。"""
    for i, r in enumerate(rows[:40]):
        m: dict[str, int] = {}
        for j, cell in enumerate(r):
            cell = cell.replace(" ", "")
            if not cell:
                continue
            for key, names in COLS.items():
                if key in m:
                    continue
                if any(cell == n or (len(n) >= 3 and n in cell) for n in names):
                    m[key] = j
                    break
        if len(m) >= 3 and sum(k in m for k in ("date", "side", "price")) >= 2:
            return i, m
    return None


def parse(text: str, default_date: str | None = None) -> dict:
    rows = _rows(text or "")
    found = _header(rows)
    if not found:
        return {"fills": [], "skipped": [], "columns": {}, "error": "找不到標題列。需要有「成交日期、買賣別、成交價、股數」這類欄位名稱。"}
    hi, m = found
    fills, skipped, seen = [], [], {}

    def cell(r, k):
        j = m.get(k)
        return r[j] if j is not None and j < len(r) else ""

    for n, r in enumerate(rows[hi + 1:], start=hi + 2):
        if not any(r):
            continue
        d = parse_date(cell(r, "date")) or (default_date if "date" not in m else None)
        side = _side(cell(r, "side"))
        price = _num(cell(r, "price"))
        shares = _num(cell(r, "shares"))
        if shares is None and "lots" in m and _num(cell(r, "lots")) is not None:
            shares = _num(cell(r, "lots")) * 1000
        cm = CODE_RE.search(cell(r, "code")) or CODE_RE.search(cell(r, "name"))
        if not d and not side and price is None:
            continue                                   # 小計、頁尾之類的列
        why = ("日期看不懂" if not d else "買賣別看不懂" if not side else "沒有股票代號" if not cm
               else "成交價看不懂" if not price or price <= 0 else "股數看不懂" if not shares or shares <= 0 else None)
        if why:
            skipped.append({"line": n, "reason": why, "raw": " | ".join(r)[:200]})
            continue
        tm = re.search(r"(\d{1,2}):(\d{2})", cell(r, "time") or cell(r, "date"))
        t = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""
        code = cm.group(1).upper()
        key = f"{d}|{t}|{code}|{side}|{price:g}|{int(shares)}"
        seen[key] = seen.get(key, 0) + 1                # 同一天同價同量的重複成交要保留
        fid = "imp_" + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:12]
        raw_side = cell(r, "side")
        fills.append({"id": fid, "date": d, "time": t, "code": code, "side": side, "price": price, "shares": int(shares),
                      "fee": _num(cell(r, "fee")), "tax": _num(cell(r, "tax")),
                      "note": raw_side if ("融" in raw_side or "券" in raw_side) else "", "source": "import"})
    return {"fills": fills, "skipped": skipped, "columns": {k: rows[hi][j] for k, j in m.items()},
            "implied_fee_discount": implied_discount(fills), "error": None}


def implied_discount(fills: list[dict], fee_rate: float = 0.001425) -> dict | None:
    """從實際手續費反推折數。只看手續費高於低消 20 元的成交，避免低消干擾。"""
    xs = []
    for f in fills:
        fee, notional = f.get("fee"), f["price"] * f["shares"]
        if fee and fee > 20 and notional > 0:
            xs.append((fee + 0.5) / (notional * fee_rate))     # 手續費無條件捨去到元，取中點
    if len(xs) < 3:
        return None
    med = statistics.median(xs)
    return {"discount": round(med, 2), "samples": len(xs), "min": round(min(xs), 3), "max": round(max(xs), 3)}
