"""跑真實資料的事前登錄 walk-forward 回測並輸出報告。

用法（在 repo 根目錄）：
    python -m quant.signal_validation   # 先驗證 App 評分，並產生月底 App 評分表（C01 用）
    python -m quant.report              # 從 data_cache/ 的快取組 panel（沒有快取會下載，第一次約 2–3 小時）

輸出：
    reports/backtest_report.md         報告
    reports/walkforward_configs.csv    事前登錄設定的樣本內 / 樣本外指標
    reports/trials_log.csv             所有試過的設定（含登錄前的探索）
    reports/monthly_picks.json         只有在通過 spec.json 的 pass_rule 時才輸出，供 /api/tw/picks/monthly 使用
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
from .metrics import deflated_sharpe, summarize
from .walkforward import label, load_spec, walk_forward

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
FACTOR_ZH = {"momentum_12_1": "12-1 動能", "momentum_6_1": "6-1 動能", "low_vol": "低波動",
             "revenue_yoy": "營收年增", "inst_flow": "法人買超", "app_score": "App 技術面評分（BUY）"}
EXPLORATORY_TRIALS = 45   # 登錄前的探索性網格（見 spec.json disclosure）
DISCLAIMER = "研究／模擬組合，非投資建議。回測不保證未來獲利；長期核心部位以 0050 等大盤 ETF 為預設。"


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


def daily_excess(res: dict, start, end) -> pd.Series:
    eq, b = res["equity"].loc[start:end], res["benchmark"].loc[start:end]
    return (eq.pct_change() - b.pct_change()).dropna()


def metrics_table(rows: list[tuple[str, dict]]) -> str:
    out = ["| 項目 | 年化報酬 | 波動 | Sharpe | 最大回撤 | 總報酬 | 年週轉率 | 月超額 t 值 | 贏 0050 月份 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in rows:
        out.append(f"| {name} | {pct(m['cagr'])} | {pct(m['vol'])} | {num(m['sharpe'])} | {pct(m['max_drawdown'])} | "
                   f"{pct(m['total_return'], 0)} | {num(m['annual_turnover'], 1)}x | {num(m['excess_t_stat'])} | "
                   f"{pct(m['excess_pct_months_beat'], 0)} |")
    b = rows[0][1]
    out.append(f"| 0050 買進持有（含息） | {pct(b['bench_cagr'])} | {pct(b['bench_vol'])} | {num(b['bench_sharpe'])} | "
               f"{pct(b['bench_max_drawdown'])} | {pct(b['bench_total_return'], 0)} | — | — | — |")
    return "\n".join(out)


def load_panel(end: str, log=print) -> dict:
    """從快取組 panel（用目前版本的資料處理程式碼），並接上 App 評分表。"""
    panel = data.build_panel("2013-06-01", end, log=log)
    f = data.CACHE_DIR / "app_scores.pkl"
    if f.exists():
        panel.update(pickle.load(open(f, "rb")))
    else:
        log("app_scores.pkl 不存在：請先跑 python -m quant.signal_validation，C01 會被略過")
    return panel


def write_trials_log(table: pd.DataFrame, spec: dict) -> None:
    cols = ["is_cagr", "is_sharpe", "is_excess_info_ratio", "oos_cagr", "oos_sharpe", "oos_bench_cagr", "oos_bench_sharpe"]
    rows = []
    pre = data.CACHE_DIR / "wf_prelim.pkl"
    if pre.exists():
        for r in pd.read_pickle(pre).to_dict("records"):
            rows.append({"phase": "exploratory (before registration)", "config": f"E{r['id']:02d}",
                         "factors": r["factors"], "top_n": r["top_n"], **{c: r[c] for c in cols}})
    for r in table.to_dict("records"):
        rows.append({"phase": f"registered {spec['registered_at']}", "config": r["config_id"],
                     "factors": r["factors"], "top_n": r["top_n"], **{c: r[c] for c in cols}})
    pd.DataFrame(rows).to_csv(REPORTS / "trials_log.csv", index=False, float_format="%.4f")


def passes(oos: dict, dsr: float) -> bool:
    return bool(oos["cagr"] > oos["bench_cagr"] and oos["sharpe"] > oos["bench_sharpe"]
                and oos["excess_t_stat"] >= 1.0 and dsr >= 0.95)


def signal_validation_summary() -> list[str]:
    f = REPORTS / "signal_validation.json"
    if not f.exists():
        return ["（尚未執行 `python -m quant.signal_validation`）"]
    v = json.loads(f.read_text(encoding="utf-8"))
    return [f"- 持有 {name}：評分與未來報酬的 rank IC 平均 {r['ic_mean']:.3f}（t 值 {r['ic_t']:.2f}）；"
            f"BUY 訊號 {r['n_buy']:,} 筆扣成本後平均 {pct(r['buy_net'], 2)}，比同期 0050 {pct(r['buy_vs_0050'], 2)}"
            for name, r in v.items()]


def build_report(panel, spec, wf, extra, picks_payload, IS, OOS, oos_end) -> str:
    t = wf["table"]
    best = t.loc[t["id"] == wf["best_id"]].iloc[0]
    res = wf["best"]
    ins, oos = summarize(res, *IS), summarize(res, OOS[0], oos_end)
    ew = extra["ew"]
    dsr_is, dsr_oos = extra["dsr_is"], extra["dsr_oos"]
    close = panel["close"]
    n_delisted = int(panel["delist_date"].reindex(close.columns).notna().sum())
    rank_oos = int((t["oos_excess_info_ratio"] > best["oos_excess_info_ratio"]).sum()) + 1
    n_beat_oos = int(((t["oos_cagr"] > t["oos_bench_cagr"]) & (t["oos_sharpe"] > t["oos_bench_sharpe"])).sum())
    name = f"{best['config_id']}：{zh_label(best['factors'])} / {int(best['top_n'])} 檔"

    head = (f"**結論：事前登錄的 {len(t)} 組設定中，樣本內最好的那組在樣本外（{OOS[0][:4]} 年起）扣成本後"
            + ("通過事前訂好的門檻，贏過 0050。**" if extra["passed"]
               else "沒有通過門檻、沒有穩定贏過 0050。因此 App 不推出「每月選股」，0050 仍是預設的核心部位。**"))

    yi, yb, ye = yearly(res["equity"]), yearly(res["benchmark"]), yearly(ew["equity"])
    oos_year = int(OOS[0][:4])
    years = "\n".join(f"| {d.year}{'（樣本外）' if d.year >= oos_year else ''} | {pct(yi[d])} | {pct(yb.get(d, np.nan))} | "
                      f"{pct(ye.get(d, np.nan))} | {pct(yi[d] - yb.get(d, np.nan))} |" for d in yi.index)
    cfg_rows = "\n".join(
        f"| {r['config_id']}{' ⭐' if r['id'] == wf['best_id'] else ''} | {zh_label(r['factors'])} | {r['top_n']} | "
        f"{pct(r['is_cagr'])} | {num(r['is_sharpe'])} | {num(r['is_excess_info_ratio'])} | "
        f"{pct(r['oos_cagr'])} | {num(r['oos_sharpe'])} | {num(r['oos_excess_t_stat'])} |"
        for r in t.to_dict("records"))

    lines = [
        "# 台股多因子選股回測報告",
        "",
        f"產生時間：{datetime.now():%Y-%m-%d %H:%M}　資料截止：{close.index[-1]:%Y-%m-%d}",
        "",
        f"> ⚠️ {DISCLAIMER}",
        "",
        head,
        "",
        f"- 樣本內（{IS[0][:4]}–{IS[1][:4]}）挑出：**{name}**",
        f"- 樣本內：年化 {pct(ins['cagr'])} vs 0050 {pct(ins['bench_cagr'])}；Sharpe {num(ins['sharpe'])} vs {num(ins['bench_sharpe'])}",
        f"- **樣本外：年化 {pct(oos['cagr'])} vs 0050 {pct(oos['bench_cagr'])}；Sharpe {num(oos['sharpe'])} vs {num(oos['bench_sharpe'])}；"
        f"最大回撤 {pct(oos['max_drawdown'])} vs {pct(oos['bench_max_drawdown'])}；"
        f"月超額 t 值 {num(oos['excess_t_stat'])}（{oos['excess_months']} 個月）**",
        f"- Deflated Sharpe（以 {extra['n_trials']} 次試驗計，對 0050 的每日超額報酬）：樣本內 {num(dsr_is['dsr'])}、"
        f"樣本外 {num(dsr_oos['dsr'])}（需 ≥ 0.95 才算顯著）",
        f"- {len(t)} 組登錄設定在樣本外有 {n_beat_oos} 組同時在年化與 Sharpe 贏 0050；樣本內第一名在樣本外排第 {rank_oos} 名。",
        "",
        "## 1. 事前登錄與試驗紀錄",
        "",
        f"- 規格檔 `quant/spec.json`（{spec['registered_at']}，跑樣本外之前寫好）：設定清單、挑選規則、通過門檻。",
        f"- **揭露**：登錄前我做過一次探索性回測（{EXPLORATORY_TRIALS} 組），看過那批設定的樣本外結果，"
        "所以這次樣本外不是完全沒看過的資料。那次樣本內第一名的樣本外年化與 0050 打平、Sharpe 較低，同樣沒有贏。"
        f"兩次加總 {extra['n_trials']} 組，全部記錄在 `reports/trials_log.csv`。",
        f"- 通過門檻：{spec['pass_rule']}",
        "",
        "## 2. 方法",
        "",
        f"- **股票池**：上市普通股共 {close.shape[1]} 檔，其中 {n_delisted} 檔在期間內下市 —— 下市股保留在樣本裡，"
        "資料中斷後以最後收盤價、0.5% 滑價扣成本出場（避免倖存者偏差）。",
        "- **流動性**：每月只從 20 日平均成交金額 ≥ 5,000 萬元的股票中，取前 300 名當候選。",
        "- **打分**：每月最後一個交易日收盤後，只用當時已公開的資料；在候選池內做百分位排名後等權相加。",
        "  - 12-1 動能（還原價）、低波動（120 日）、營收年增（近 3 個月對去年同月，**次月 11 日才可用**，依月份標籤對齊）、"
        "法人買超（近 20 日三大法人買賣超金額 / 成交金額，金額用未還原價）、App 技術面評分（只取 BUY）",
        "  - 某因子在候選池覆蓋率不到一半（資料源缺漏）時，該月略過該因子並記錄，不會讓候選清單變空",
        "- **交易**：下一個交易日**開盤價**成交、等權、每月調整。",
        "- **成本**：手續費 0.1425%（買賣各一次，**每筆最低 20 元**，假設資金 100 萬）、證交稅 0.3%、"
        "滑價依流動性分級（≥10 億 0.1%、≥3 億 0.2%、≥1 億 0.3%、其餘 0.5%）。",
        "- **基準**：(1) 0050 買進持有（含息）；(2) 候選池 300 檔等權、月調整、同樣扣成本。",
        "",
        "## 3. 結果（全部已扣成本）",
        "",
        f"### 樣本內 {IS[0][:4]}–{IS[1][:4]}",
        "",
        metrics_table([(name, ins), ("候選池 300 檔等權", summarize(ew, *IS))]),
        "",
        f"### 樣本外 {OOS[0][:4]}–{oos_end[:4]}",
        "",
        metrics_table([(name, oos), ("候選池 300 檔等權", summarize(ew, OOS[0], oos_end)),
                       ("同設定、固定滑價 0.3%", summarize(extra["slip"], OOS[0], oos_end)),
                       ("同設定、排除 2330 台積電", summarize(extra["ex2330"], OOS[0], oos_end))]),
        "",
        "「月超額 t 值」= 每月（策略 − 0050）報酬平均 ÷ 標準誤；約 2 以上才算統計上站得住，1 以下跟 0 沒有差別。",
        "",
        "### 事前登錄的設定",
        "",
        "| 設定 | 因子 | 持股 | 樣本內年化 | 樣本內 Sharpe | 樣本內 IR（挑選依據） | 樣本外年化 | 樣本外 Sharpe | 樣本外 t 值 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        cfg_rows,
        "",
        f"同期 0050：樣本內年化 {pct(ins['bench_cagr'])}、Sharpe {num(ins['bench_sharpe'])}；"
        f"樣本外年化 {pct(oos['bench_cagr'])}、Sharpe {num(oos['bench_sharpe'])}。⭐ = 依樣本內 IR 選出的設定。",
        "",
        "### 逐年報酬",
        "",
        "| 年 | 選出的策略 | 0050 | 候選池等權 | 策略 − 0050 |",
        "|---|---:|---:|---:|---:|",
        years,
        "",
        "## 4. App 現有技術面評分的全市場驗證",
        "",
        *signal_validation_summary(),
        "",
        "完整數字見 `reports/signal_validation.md`；月調整版本（C01）的結果在上表。",
        "",
        "## 5. 舊版 App 回測的問題（這次已修正）",
        "",
        "1. **單一股票、樣本內勝率**：`_calc_winrate` 拿同一檔股票最近的資料算「站上 MA20 且 RSI>50 之後 5 天上漲的比例」，"
        "勝率 ≥55% 還會讓信心分數 +5。這是用同一段資料自己驗證自己 —— 加分已移除，勝率改為扣成本、不重疊，少於 30 筆顯示「樣本不足」。",
        "2. **沒有交易成本**：台股來回約 0.585%（手續費 + 稅），加滑價約 0.785%。每 5 天一次，一年 50 次就是約 39% 的成本，舊版完全沒扣。",
        "3. **重疊交易與複利**：每天只要訊號成立就開一筆 5 日交易，彼此重疊卻把報酬全部連乘，等於同時下好幾倍的注。",
        "4. **以訊號當天收盤價進場**：用收盤價算訊號又用同一個收盤價買進，實務上做不到。現在改為隔日開盤進場。",
        "5. **回測與即時分析輸入不一致**：回測把量比、漲跌幅、近期價格固定成預設值，等於關掉量能、過熱、假突破判斷。現在與即時分析相同。",
        "6. **沒有基準**：只報勝率與平均報酬。現在附「買進持有本股」與「0050」同期報酬。",
        "7. **假的重訓**：`retrain_ai_weights` 沒改任何權重就回報「AI 權重重訓完成」。現在誠實回報「未調整」。",
        "8. **倖存者偏差**：掃描池 `TW_SCAN_POOL` 是今天挑的大型股名單。本回測改用含下市股的全上市股票池。",
        "9. **交易計畫 R:R 虛胖**：停損取最寬、目標取最樂觀。現在取最近的合理停損與目標。",
        "",
        "## 6. 限制",
        "",
        f"- 單日漲跌超過 30%（台股漲跌幅限制 10%）視為減資換股或資料錯誤，當日報酬設為 0；共修正 {panel.get('price_breaks_fixed', 0)} 筆。",
        "- 還原股價來自 Yahoo Finance（含息還原）；下市股只有 FinMind 未還原價格（少算股利，對下市股略為不利）。",
        "- 月營收以公開資訊觀測站每月彙總表為準；公司事後更正（restatement）的數字會覆蓋原始公告，可能有輕微的前視偏誤。",
        "- 法人買賣超只抓每月底前 20 個交易日；只含上市（TWSE），不含上櫃。",
        "- 滑價為估計值；現金部位不計利息；未計股利所得稅與二代健保補充保費。",
        "- 2021 年後台積電在 0050 權重極高、表現特別強，分散的多因子組合在這段期間本來就很難贏 0050（見「排除 2330」一列）。",
        "",
    ]
    if picks_payload:
        lines += ["## 7. 本月研究／模擬組合", "",
                  f"打分日 {picks_payload['as_of']}。{DISCLAIMER}已加到 App 的 `/api/tw/picks/monthly`。", ""]
    lines += ["---", "", f"_本報告由 `python -m quant.report` 自動產生。{DISCLAIMER}_", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2026-10-31")
    args = ap.parse_args()
    spec = load_spec()
    IS = tuple(spec["in_sample"])
    OOS = (spec["out_of_sample"][0], None)
    panel = load_panel(args.end)
    oos_end = panel["close"].index[-1].strftime("%Y-%m-%d")
    grid = [c for c in spec["configs"] if "app_score" not in c["weights"] or "app_score" in panel]

    wf = walk_forward(panel, IS[0], IS[1], OOS[0], oos_end, grid=grid)
    best = wf["grid"][wf["best_id"]]
    cache = FactorCache(panel)
    kw = dict(weights=best["weights"], top_n=best["top_n"], start=IS[0], end=oos_end)
    extra = {
        "ew": run_backtest(panel, BacktestConfig(weights={"momentum_12_1": 1.0}, top_n=300, start=IS[0], end=oos_end), cache),
        "slip": run_backtest(panel, BacktestConfig(slippage=0.003, **kw), cache),
        "ex2330": run_backtest(panel, BacktestConfig(exclude=("2330",), **kw), cache),
        "n_trials": EXPLORATORY_TRIALS + len(grid),
    }
    # 各登錄設定在樣本內「每日」超額 Sharpe 的變異數（deflated Sharpe 用）
    srs = [s.mean() / s.std() for s in (daily_excess(r, *IS) for r in wf["results"]) if s.std() > 0]
    var_sr = float(np.var(srs)) if len(srs) > 1 else 0.0
    extra["dsr_is"] = deflated_sharpe(daily_excess(wf["best"], *IS), extra["n_trials"], var_sr)
    extra["dsr_oos"] = deflated_sharpe(daily_excess(wf["best"], OOS[0], oos_end), extra["n_trials"], var_sr)
    oos = summarize(wf["best"], OOS[0], oos_end)
    extra["passed"] = passes(oos, extra["dsr_oos"]["dsr"])

    REPORTS.mkdir(exist_ok=True)
    wf["table"].to_csv(REPORTS / "walkforward_configs.csv", index=False, float_format="%.4f")
    write_trials_log(wf["table"], spec)

    payload = None
    picks_file = REPORTS / "monthly_picks.json"
    if extra["passed"]:
        cfg = BacktestConfig(weights=best["weights"], top_n=best["top_n"])
        as_of = panel["close"].index[-1]
        picks = select_picks(panel, as_of, cfg, cache)
        payload = {"as_of": f"{as_of:%Y-%m-%d}", "config_id": best["id"], "factors": label(best["weights"]),
                   "top_n": best["top_n"], "picks": [{"stock_id": s, "score": round(float(v), 4)} for s, v in picks.items()],
                   "in_sample": summarize(wf["best"], *IS), "out_of_sample": oos, "n_configs_tried": extra["n_trials"],
                   "disclaimer": DISCLAIMER, "generated_at": datetime.now().isoformat(timespec="seconds")}
        picks_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif picks_file.exists():
        picks_file.unlink()
    (REPORTS / "backtest_report.md").write_text(build_report(panel, spec, wf, extra, payload, IS, OOS, oos_end),
                                                encoding="utf-8")
    print(json.dumps({"best": best["id"], "factors": label(best["weights"]), "passes": extra["passed"],
                      "oos_cagr": oos["cagr"], "oos_bench_cagr": oos["bench_cagr"], "oos_sharpe": oos["sharpe"],
                      "oos_bench_sharpe": oos["bench_sharpe"], "oos_t": oos["excess_t_stat"],
                      "dsr_oos": extra["dsr_oos"]["dsr"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
