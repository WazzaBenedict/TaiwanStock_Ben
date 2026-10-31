"""績效指標。輸入皆為每日淨值序列（已扣成本）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def cagr(eq: pd.Series) -> float:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    if years <= 0 or eq.iloc[0] <= 0:
        return float("nan")
    return float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)


def volatility(eq: pd.Series) -> float:
    return float(eq.pct_change().dropna().std() * np.sqrt(TRADING_DAYS))


def sharpe(eq: pd.Series, rf: float = 0.0) -> float:
    r = eq.pct_change().dropna() - rf / TRADING_DAYS
    sd = r.std()
    return float(r.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else float("nan")


def max_drawdown(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def monthly_returns(eq: pd.Series) -> pd.Series:
    m = eq.resample("ME").last()
    first = pd.Series([eq.iloc[0]], index=[eq.index[0] - pd.Timedelta(days=1)])
    return pd.concat([first, m]).pct_change().dropna()


def excess_stats(eq: pd.Series, bench: pd.Series) -> dict:
    """月超額報酬（策略 − 0050）的平均、t 值、打敗 0050 的月份比例、資訊比率。"""
    ex = (monthly_returns(eq) - monthly_returns(bench)).dropna()
    n = len(ex)
    sd = ex.std()
    t = float(ex.mean() / sd * np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    return {
        "months": n,
        "mean_monthly_excess": float(ex.mean()) if n else float("nan"),
        "t_stat": t,
        "pct_months_beat": float((ex > 0).mean()) if n else float("nan"),
        "info_ratio": float(ex.mean() / sd * np.sqrt(12)) if n > 1 and sd > 0 else float("nan"),
    }


def annual_turnover(rebalances: list[dict], eq: pd.Series) -> float:
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    return float(sum(r["turnover"] for r in rebalances) / years) if years > 0 else float("nan")


def summarize(result: dict, start=None, end=None) -> dict:
    """result 來自 engine.run_backtest；可指定子區間（以該區間起點重新歸一）。"""
    eq, bench = result["equity"], result["benchmark"]
    if start or end:
        eq, bench = eq.loc[start:end], bench.loc[start:end]
    rebs = [r for r in result["rebalances"]
            if (not start or r["trade_date"] >= pd.Timestamp(start)) and (not end or r["trade_date"] <= pd.Timestamp(end))]
    eq, bench = eq / eq.iloc[0], bench / bench.iloc[0]
    out = {
        "start": eq.index[0].strftime("%Y-%m-%d"), "end": eq.index[-1].strftime("%Y-%m-%d"),
        "cagr": cagr(eq), "vol": volatility(eq), "sharpe": sharpe(eq), "max_drawdown": max_drawdown(eq),
        "total_return": float(eq.iloc[-1] - 1),
        "bench_cagr": cagr(bench), "bench_vol": volatility(bench), "bench_sharpe": sharpe(bench),
        "bench_max_drawdown": max_drawdown(bench), "bench_total_return": float(bench.iloc[-1] - 1),
        "annual_turnover": annual_turnover(rebs, eq),
        "avg_cost_per_rebalance": float(np.mean([r["cost"] for r in rebs])) if rebs else 0.0,
    }
    out.update({f"excess_{k}": v for k, v in excess_stats(eq, bench).items()})
    return out
