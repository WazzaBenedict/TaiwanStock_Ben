"""回補 2004–2013 全市場資料到 data_cache/（做為從未看過的「反向保留樣本」）。

    python -m quant.backfill            # 約 2–4 小時；可中斷後重跑（已下載的會讀快取）
"""
from __future__ import annotations

import pickle
import sys
import time

from . import data


def main(start="2004-01-01", end="2013-12-31"):
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:7.0f}s] {m}", flush=True)
    panel = data.build_panel(start, end, with_inst=False, log=log)
    out = data.CACHE_DIR / f"panel_{start}_{end}.pkl"
    with open(out, "wb") as f:
        pickle.dump(panel, f)
    c = panel["close"]
    log(f"done: {c.shape[1]} stocks, {c.index[0].date()}～{c.index[-1].date()}, saved {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
