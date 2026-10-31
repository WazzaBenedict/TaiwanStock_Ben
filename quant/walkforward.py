"""Walk-forward：只用樣本內（in-sample）挑因子權重與持股數，樣本外（out-of-sample）原封不動報告。

每組設定都從樣本內起點連續跑到樣本外終點（打分只用當時資料，所以後段不影響前段），
再把淨值切成兩段分別計算。挑選只看樣本內指標。
"""
from __future__ import annotations

from itertools import product

import pandas as pd

from .engine import BacktestConfig, FactorCache, run_backtest
from .metrics import summarize

FACTOR_NAMES = ["momentum_12_1", "momentum_6_1", "low_vol", "revenue_yoy", "inst_flow"]
TOP_N_GRID = [10, 20, 30]


def config_grid(factors=FACTOR_NAMES, top_ns=TOP_N_GRID) -> list[dict]:
    """每個因子權重 0 或 1（至少一個非 0）× 持股數。5 因子 × 3 種持股數 = 93 組。"""
    grid = []
    for mask in product([0, 1], repeat=len(factors)):
        if not any(mask):
            continue
        w = {f: float(m) for f, m in zip(factors, mask)}
        for n in top_ns:
            grid.append({"weights": w, "top_n": n})
    return grid


def label(weights: dict) -> str:
    return "+".join(k for k, v in weights.items() if v) or "none"


def walk_forward(panel: dict, is_start: str, is_end: str, oos_start: str, oos_end: str | None = None,
                 grid: list[dict] | None = None, select_by: str = "excess_info_ratio",
                 base: dict | None = None, log=print) -> dict:
    grid = grid or config_grid()
    cache = FactorCache(panel)
    rows, results = [], []
    for i, g in enumerate(grid):
        cfg = BacktestConfig(weights=g["weights"], top_n=g["top_n"], start=is_start, end=oos_end, **(base or {}))
        res = run_backtest(panel, cfg, cache)
        ins = summarize(res, is_start, is_end)
        oos = summarize(res, oos_start, oos_end)
        rows.append({"id": i, "factors": label(g["weights"]), "top_n": g["top_n"],
                     **{f"is_{k}": v for k, v in ins.items()}, **{f"oos_{k}": v for k, v in oos.items()}})
        results.append(res)
        if i % 10 == 0:
            log(f"config {i + 1}/{len(grid)}")
    table = pd.DataFrame(rows)
    best = int(table.sort_values(f"is_{select_by}", ascending=False).iloc[0]["id"])
    return {"table": table, "best_id": best, "best": results[best], "n_configs": len(grid),
            "select_by": select_by, "grid": grid}
