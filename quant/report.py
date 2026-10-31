"""跑真實資料的 walk-forward 回測並輸出報告。

用法（在 repo 根目錄）：
    python -m quant.report                      # 用 data_cache/panel_full.pkl
    python -m quant.report --fetch              # 先下載資料（第一次約 2–3 小時，主要是證交所 T86 限速）

輸出：
    reports/backtest_report.md         報告
    reports/walkforward_configs.csv    每一組設定的樣本內 / 樣本外指標
    reports/monthly_picks.json         只有在樣本外扣成本後仍贏 0050 時才輸出，供 /api/tw/picks/monthly 使用
"""
from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .engine import BacktestConfig, FactorCache, run_backtest, select_picks
from .metrics import summarize
from .walkforward import walk_forward, label

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
IS_START, IS_END = "2015-01-01", "2020-12-31"
OOS_START = "2021-01-01"
FACTOR_ZH = {"momentum_12_1": "12-1 動能", "momentum_6_1": "6-1 動能", "low_vol": "低波動",
             "revenue_yoy": "營收年增", "inst_flow": "法人買超"}


def pct(x, d=1):
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.{d}f}%"


def num(x, d=2):
    return "—" if x is None or not np.isfinite(x) else f"{x:.{d}f}"


def zh_label(factors: str) -> str:
    return " + ".join(FACTOR_ZH.get(f, f) for f in factors.split("+"))


def yearly(eq: pd.Series) -> pd.Series:
    y = eq.resample("YE").last()
    first = pd.Series([eq.iloc[0]], index=[eq.index[0] - pd.Timedelta(days=1)])
    return pd.concat([first, y]).pct_change().dropna()


def passes(oos: dict) -> bool:
    """樣本外扣成本後：年化報酬與 Sharpe 都要高於 0050，且月超額報酬 t 值 ≥ 1。"""
    return (oos["cagr"] > oos["bench_cagr"] and oos["sharpe"] > oos["bench_sharpe"]
            and oos["excess_t_stat"] >= 1.0)


def metrics_table(rows: list[tuple[str, dict]]) -> str:
    out = ["| 項目 | 年化報酬 | 波動 | Sharpe | 最大回撤 | 總報酬 | 年週轉率 | 月超額 t 值 | 贏 0050 月份 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in rows:
        out.append(f"| {name} | {pct(m['cagr'])} | {pct(m['vol'])} | {num(m['sharpe'])} | {pct(m['max_drawdown'])} | "
                   f"{pct(m['total_return'], 0)} | {num(m['annual_turnover'], 1)}x | {num(m['excess_t_stat'])} | "
                   f"{pct(m['excess_pct_months_beat'], 0)} |")
        b = m
    out.append(f"| 0050 買進持有（含息） | {pct(b['bench_cagr'])} | {pct(b['bench_vol'])} | {num(b['bench_sharpe'])} | "
               f"{pct(b['bench_max_drawdown'])} | {pct(b['bench_total_return'], 0)} | — | — | — |")
    return "\n".join(out)


def build_report(panel: dict, wf: dict, baseline: dict, picks_payload: dict | None, oos_end: str) -> str:
    t = wf["table"]
    best = t.loc[t["id"] == wf["best_id"]].iloc[0]
    res = wf["best"]
    ins, oos = summarize(res, IS_START, IS_END), summarize(res, OOS_START, oos_end)
    b_ins, b_oos = summarize(baseline, IS_START, IS_END), summarize(baseline, OOS_START, oos_end)
    ok = passes(oos)
    n_beat_oos = int(((t["oos_cagr"] > t["oos_bench_cagr"]) & (t["oos_sharpe"] > t["oos_bench_sharpe"])).sum())
    n_beat_is = int(((t["is_cagr"] > t["is_bench_cagr"]) & (t["is_sharpe"] > t["is_bench_sharpe"])).sum())
    close = panel["close"]
    n_stocks = close.shape[1]
    n_delisted = int(panel["delist_date"].reindex(close.columns).notna().sum())
    rank_oos = int((t["oos_excess_info_ratio"] > best["oos_excess_info_ratio"]).sum()) + 1

    head = (f"**結論：樣本外（{OOS_START[:4]} 年起）扣成本後，選出的策略{'有' if ok else '沒有'}穩定贏過 0050。**"
            if ok else
            f"**結論：樣本外（{OOS_START[:4]} 年起）扣成本後，選出的策略沒有穩定贏過 0050。"
            f"所以這次不在 App 上推出「每月選股」功能。**")

    yi, yb = yearly(res["equity"]), yearly(res["benchmark"])
    years = "\n".join(f"| {d.year} | {pct(yi[d])} | {pct(yb.get(d, np.nan))} | {pct(yi[d] - yb.get(d, np.nan))} |"
                      for d in yi.index)

    top10 = t.sort_values("is_excess_info_ratio", ascending=False).head(10)
    top10_md = "\n".join(
        f"| {zh_label(r.factors)} | {r.top_n} | {pct(r.is_cagr)} | {num(r.is_excess_info_ratio)} | "
        f"{pct(r.oos_cagr)} | {num(r.oos_excess_info_ratio)} |" for r in top10.itertuples())

    lines = [
        "# 台股多因子選股回測報告",
        "",
        f"產生時間：{datetime.now():%Y-%m-%d %H:%M}　資料截止：{close.index[-1]:%Y-%m-%d}",
        "",
        "> ⚠️ 回測不保證未來獲利。本報告是研究紀錄，不是投資建議。",
        "",
        head,
        "",
        f"- 樣本內（{IS_START[:4]}–{IS_END[:4]}）挑出的最佳設定：**{zh_label(best['factors'])}，持股 {int(best['top_n'])} 檔**",
        f"- 樣本內：年化 {pct(ins['cagr'])}，0050 {pct(ins['bench_cagr'])}；Sharpe {num(ins['sharpe'])} vs {num(ins['bench_sharpe'])}",
        f"- 樣本外：年化 {pct(oos['cagr'])}，0050 {pct(oos['bench_cagr'])}；Sharpe {num(oos['sharpe'])} vs {num(oos['bench_sharpe'])}；"
        f"月超額報酬 t 值 {num(oos['excess_t_stat'])}（{oos['excess_months']} 個月）",
        f"- 一共試了 **{wf['n_configs']} 組設定**（5 個因子各開/關 × 持股 10/20/30 檔）。"
        f"樣本內有 {n_beat_is} 組贏 0050，樣本外只剩 {n_beat_oos} 組；樣本內第一名在樣本外排第 {rank_oos} 名。",
        "  試越多組，樣本內最好的那組越可能只是運氣好（資料探勘偏誤），所以只看樣本外。",
        "",
        "## 1. 方法",
        "",
        f"- **股票池**：所有上市普通股（4 碼代號），共 {n_stocks} 檔有價格資料，其中 {n_delisted} 檔在期間內下市 —— "
        "下市股保留在樣本裡，下市時以最後收盤價扣賣出成本出場，避免倖存者偏差。",
        "- **流動性**：每月只從 60 日平均成交金額 ≥ 2,000 萬元的股票中，取成交金額前 300 名當候選。",
        "- **打分**：每月最後一個交易日收盤後，只用當天以前已公開的資料：",
        "  - 12-1 / 6-1 動能（過去 12 或 6 個月報酬，扣掉最近 1 個月）",
        "  - 低波動（120 日報酬標準差，越低越好）",
        "  - 營收年增（最近 3 個月營收合計 vs 去年同期；**每月營收視為次月 11 日才公開**）",
        "  - 法人買超（近 20 日三大法人買賣超金額 / 成交金額）",
        "  - 各因子在候選池內標準化（z-score，截尾 ±3）後等權相加",
        "- **交易**：隔一個交易日**開盤價**成交，等權買進分數最高的 N 檔，每月調整一次。",
        "- **成本**：手續費 0.1425%（買賣各一次，無折扣）、證交稅 0.3%（賣出）、滑價每邊 0.1%。"
        "來回約 0.785%，按實際換手金額扣。",
        "- **基準**：同一天開盤買進 0050 一直持有（含息，扣買進成本）。",
        f"- **Walk-forward**：{IS_START[:4]}–{IS_END[:4]} 是樣本內，只用這段挑設定（依月超額報酬的資訊比率）；"
        f"{OOS_START[:4]} 起是樣本外，挑完之後完全沒有再調整。",
        "",
        "## 2. 結果（全部已扣成本）",
        "",
        f"### 樣本內 {IS_START[:4]}–{IS_END[:4]}",
        "",
        metrics_table([(f"策略：{zh_label(best['factors'])} / {int(best['top_n'])} 檔", ins),
                       ("對照：候選池 300 檔等權", b_ins)]),
        "",
        f"### 樣本外 {OOS_START[:4]}–{oos_end[:4]}",
        "",
        metrics_table([(f"策略：{zh_label(best['factors'])} / {int(best['top_n'])} 檔", oos),
                       ("對照：候選池 300 檔等權", b_oos)]),
        "",
        "「月超額 t 值」是每月（策略 − 0050）報酬的平均 ÷ 標準誤；大約要 2 以上才算統計上站得住，1 以下跟零沒有差別。",
        "",
        "### 逐年報酬（選出的策略 vs 0050）",
        "",
        "| 年 | 策略 | 0050 | 差 |",
        "|---|---:|---:|---:|",
        years,
        "",
        "### 樣本內前 10 名設定在樣本外的表現",
        "",
        "| 因子 | 持股 | 樣本內年化 | 樣本內 IR | 樣本外年化 | 樣本外 IR |",
        "|---|---:|---:|---:|---:|---:|",
        top10_md,
        "",
        "全部設定的數字在 `reports/walkforward_configs.csv`。",
        "",
        "## 3. 舊版 App 回測的問題（這次已修正）",
        "",
        "1. **單一股票、樣本內勝率**：`_calc_winrate` 拿同一檔股票最近幾個月的資料算「站上 MA20 且 RSI>50 之後 5 天上漲的比例」，"
        "再把勝率 ≥55% 當成信心加分。這是在同一段資料上自己驗證自己，沒有樣本外。",
        "2. **沒有交易成本**：台股來回成本約 0.585%（手續費+稅），加上滑價約 0.785%。每 5 天交易一次，一年 50 次就是約 39% 的成本，"
        "舊版完全沒扣。",
        "3. **重疊交易與複利**：舊版每一天只要訊號成立就開一筆 5 日交易，彼此重疊，卻把所有報酬連乘成淨值曲線，"
        "等於同時下好幾倍的注，最大回撤與報酬都失真。",
        "4. **以訊號當天收盤價進場**：訊號用當天收盤價算，又用同一個收盤價買進，實務上做不到。現在改為隔日開盤進場。",
        "5. **沒有基準**：舊版只報勝率與平均報酬，看不出是否比直接買進持有這檔股票或 0050 好。現在兩者都有。",
        "6. **假的重訓**：`retrain_ai_weights` 讀了紀錄但沒有改任何權重，就存回去並回報「AI 權重重訓完成」。"
        "因為訊號紀錄沒有存各面向分數，根本無法歸因，現在改為誠實回報「未調整」。",
        "7. **倖存者偏差**：掃描池 `TW_SCAN_POOL` 是今天挑的大型股名單，拿來看過去表現，自動排除了這段期間衰退或下市的公司。"
        "本回測改用包含下市股的全上市股票池。",
        "",
        "## 4. 限制與注意事項",
        "",
        "- 還原股價來自 Yahoo Finance（含息還原）；下市股只有 FinMind 未還原價格（少算股利，對下市股略為不利）。",
        "- 法人買超金額用「買賣超股數 × 還原收盤價」近似；只抓每個月底前 20 個交易日的資料。",
        "- 只含上市（TWSE）股票，不含上櫃。",
        "- 滑價固定每邊 0.1%；小型股實際衝擊成本可能更高。現金部位不計利息。",
        "- 月營收以次月 11 日才可用，保守但不完美（少數公司會延後或更正）。",
        "- 2021 年後台積電在 0050 權重極高，0050 本身表現特別強，這段期間任何分散的多因子組合都很難贏。",
        "",
    ]
    if picks_payload:
        lines += ["## 5. 本月選股", "",
                  f"打分日 {picks_payload['as_of']}，預計 {picks_payload['trade_on']} 開盤調整。"
                  "已加到 App 的 `/api/tw/picks/monthly`。", ""]
    lines += ["---", "", "_本報告由 `python -m quant.report` 自動產生。回測不保證未來獲利，非投資建議。_", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--panel", default=str(data.CACHE_DIR / "panel_full.pkl"))
    ap.add_argument("--end", default=None)
    args = ap.parse_args()
    if args.fetch:
        panel = data.build_panel("2013-06-01", args.end or datetime.today().strftime("%Y-%m-%d"))
        pickle.dump(panel, open(args.panel, "wb"))
    panel = pickle.load(open(args.panel, "rb"))
    oos_end = args.end or panel["close"].index[-1].strftime("%Y-%m-%d")

    wf = walk_forward(panel, IS_START, IS_END, OOS_START, oos_end)
    cache = FactorCache(panel)
    baseline = run_backtest(panel, BacktestConfig(weights={"momentum_12_1": 1.0}, top_n=300,
                                                  start=IS_START, end=oos_end), cache)
    REPORTS.mkdir(exist_ok=True)
    wf["table"].to_csv(REPORTS / "walkforward_configs.csv", index=False, float_format="%.4f")

    best = wf["grid"][wf["best_id"]]
    oos = summarize(wf["best"], OOS_START, oos_end)
    payload = None
    picks_file = REPORTS / "monthly_picks.json"
    if passes(oos):
        cfg = BacktestConfig(weights=best["weights"], top_n=best["top_n"])
        as_of = panel["close"].index[-1]
        picks = select_picks(panel, as_of, cfg, cache)
        ins = summarize(wf["best"], IS_START, IS_END)
        payload = {"as_of": f"{as_of:%Y-%m-%d}", "trade_on": "下一個交易日開盤",
                   "factors": label(best["weights"]), "top_n": best["top_n"],
                   "picks": [{"stock_id": s, "score": round(float(v), 3)} for s, v in picks.items()],
                   "in_sample": ins, "out_of_sample": oos, "n_configs_tried": wf["n_configs"],
                   "generated_at": datetime.now().isoformat(timespec="seconds")}
        picks_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif picks_file.exists():
        picks_file.unlink()
    (REPORTS / "backtest_report.md").write_text(build_report(panel, wf, baseline, payload, oos_end), encoding="utf-8")
    print(json.dumps({"best": label(best["weights"]), "top_n": best["top_n"], "passes": passes(oos),
                      "oos_cagr": oos["cagr"], "oos_bench_cagr": oos["bench_cagr"],
                      "oos_sharpe": oos["sharpe"], "oos_bench_sharpe": oos["bench_sharpe"],
                      "oos_t": oos["excess_t_stat"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
