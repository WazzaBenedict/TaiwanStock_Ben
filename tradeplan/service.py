"""組合 API 回應：今天的交易計畫 + 同規則在此股的歷史成績 + 隨機進場對照 + 0050。"""
from __future__ import annotations

import pandas as pd

from .costs import Costs, is_etf
from .rules import PlanRules, make_plan, position_size
from .simulate import random_entry_control, simulate, summarize

RESEARCH_LABEL = "研究／模擬 · 規則未通過樣本外檢驗，不構成投資建議"
CAVEATS = [
    "歷史成績只用此股近幾年資料，筆數少時只能當描述，不能當證據。",
    "股票池是今天還在交易的股票，有倖存者偏差，歷史表現會被高估。",
    "使用未還原權息的價格，除權息缺口可能被誤判為停損。",
    "成本已扣：手續費 0.1425%×2、證交稅 0.3%（ETF 0.1%、債券 ETF 0%）、滑價 0.1%×2；未計每筆最低 20 元。",
    "同期 0050 為價格漲跌、未含配息；規則累積報酬只算持有期間，空手時沒有報酬。",
    "計畫只用已收盤的日 K；盤中查詢會用前一個交易日收盤。",
]


def _bdays_after(as_of: str, n: int) -> str:
    """估算第 n 個交易日（只排除週末，未排除國定假日，故標「約」）。"""
    return (pd.Timestamp(as_of) + pd.offsets.BDay(n)).strftime("%Y-%m-%d")


def bench_return(bench: pd.DataFrame | None, start: str, end: str) -> float | None:
    if bench is None or bench.empty:
        return None
    b = bench.copy()
    b["日期"] = pd.to_datetime(b["日期"])
    w = b[(b["日期"] >= pd.Timestamp(start)) & (b["日期"] <= pd.Timestamp(end))]
    if len(w) < 2:
        return None
    return round((float(w["收盤價"].iloc[-1]) / float(w["收盤價"].iloc[0]) - 1) * 100, 1)


def build_card(stock_id: str, df: pd.DataFrame, setup: pd.Series, bench: pd.DataFrame | None = None,
               capital: float | None = None, risk_pct: float = 0.01,
               rules: PlanRules = PlanRules(), costs: Costs = Costs()) -> dict:
    etf = is_etf(stock_id)
    plan = make_plan(df, rules, etf)
    trades = simulate(df, setup, rules, costs, etf)
    hist = summarize(trades)
    control = random_entry_control(df, hist["n"], rules, costs, etf) if hist["n"] else {"runs": 0}
    if hist["n"]:
        hist["bench_0050_pct"] = bench_return(bench, hist["first_date"], hist["last_date"])
        span = max(1, len(pd.bdate_range(hist["first_date"], hist["last_date"])))
        hist["exposure_pct"] = round(min(100.0, hist["days_held"] / span * 100), 1)
    setup_today = bool(pd.Series(setup).fillna(False).astype(bool).iloc[-1]) if len(setup) else False

    # 狀態：只有「樣本夠、扣成本後 95% 區間下緣 > 0、且贏過隨機進場的第 90 百分位」才叫條件符合
    ci = hist.get("avg_ret_ci95_pct")
    verified = bool(hist.get("sample_ok") and ci and ci[0] > 0 and control.get("runs")
                    and hist["avg_ret_pct"] > control.get("p90_pct", float("inf")))
    if not plan:
        status, status_text = "NO_PLAN", "資料不足，無法產生計畫"
    elif not setup_today:
        status, status_text = "NOT_TRIGGERED", "今天未觸發進場條件"
    elif hist["n"] and hist.get("avg_ret_pct", 0) <= 0:
        status, status_text = "NEGATIVE_EV", "條件出現，但此規則在本股歷史扣成本後平均為負"
    elif not verified:
        status, status_text = "UNVERIFIED", "條件出現，但證據不足"
    else:
        status, status_text = "SETUP", "條件符合"

    if plan:
        plan["valid_until"] = _bdays_after(plan["as_of"], rules.entry_valid_days)
        plan["time_exit_by"] = _bdays_after(plan["as_of"], rules.entry_valid_days + rules.max_hold_days)
        plan["buy_rules"] = [
            f"掛限價 {plan['entry']} 買進，不追高；約 {plan['valid_until']} 收盤前沒成交就取消",
            f"開盤已低於停損 {plan['stop']} 就不買（計畫失效）",
        ]
        plan["sell_rules"] = [
            f"跌破停損 {plan['stop']} 就賣（開盤跳空跌破則開盤賣）",
            f"漲到目標 {plan['target']}（+{rules.target_r:g}R）賣出",
            f"收盤站上 {plan['breakeven_trigger']}（+1R）後，停損上移到進場價；之後停損 = 最高收盤 − {rules.trail_atr:g}×ATR",
            f"持有滿 {rules.max_hold_days} 個交易日還沒出場，當天收盤賣（約 {plan['time_exit_by']} 前）",
        ]
        if capital:
            plan["position"] = position_size(capital, risk_pct, plan["entry"], plan["stop"], costs, etf)
            plan["position"]["risk_pct_of_capital"] = round(risk_pct * 100, 2)

    return {
        "stock_id": stock_id, "etf": etf, "label": RESEARCH_LABEL,
        "status": status, "status_text": status_text, "setup_today": setup_today,
        "plan": plan, "history": hist, "random_control": control,
        "recent_trades": trades[-8:][::-1], "rules": rules.as_dict(), "caveats": CAVEATS,
    }
