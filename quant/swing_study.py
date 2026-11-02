"""每日選股 + 進出場系統研究（規格：quant/swing_spec.json）。

    python -m quant.swing_study selection          # 2014-07 起：跑 S1/S3/S4/S5/S6，依規則選一個
    python -m quant.swing_study holdout --system S1 # 2005–2013 保留期：只跑一次（需先 python -m quant.backfill）
    python -m quant.swing_study today --system S1   # App 用：今日訊號（進場上限價、停損、吊燈）
"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .metrics import cagr, deflated_sharpe, excess_stats, max_drawdown, sharpe, volatility
from .swing import Context, SwingConfig, blend_with_core, run_swing, systems

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((ROOT / "quant" / "swing_spec.json").read_text(encoding="utf-8"))
N_TRIALS = 66
N_RANDOM = 200


def stats(eq: pd.Series) -> dict:
    eq = eq / eq.iloc[0]
    return {"cagr": cagr(eq), "vol": volatility(eq), "sharpe": sharpe(eq), "mdd": max_drawdown(eq)}


def beats(s, b):
    return s["cagr"] > b["cagr"] and s["sharpe"] > b["sharpe"]


def bench_eq(ctx: Context, days: pd.DatetimeIndex) -> pd.Series:
    b = ctx.bclose.loc[days]
    return b / ctx.bopen.loc[days[0]] * (1 - 0.001925)


def load_selection_panel():
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    return data.build_panel("2013-06-01", end, with_inst=False)


def load_holdout_panel():
    f = data.CACHE_DIR / "panel_2004-01-01_2013-12-31.pkl"
    return pickle.load(open(f, "rb"))


def run_system(ctx, sid, start, end=None, **over):
    sysd = systems()
    if sid == "S6":
        sat = run_swing(ctx, SwingConfig(name="S1", start=start, end=end, **{**sysd["S1"], **over}))
        core = bench_eq(ctx, sat["equity"].index)
        eq = blend_with_core(sat["equity"], core, 0.6)
        return {"equity": eq, "trades": sat["trades"], "skip_chase": sat["skip_chase"], "skip_limit": sat["skip_limit"]}
    return run_swing(ctx, SwingConfig(name=sid, start=start, end=end, **{**sysd[sid], **over}))


def evaluate(ctx, sid, start, end=None, full=False, log=print) -> dict:
    r = run_system(ctx, sid, start, end)
    eq = r["equity"]
    b = bench_eq(ctx, eq.index)
    tr = r["trades"]
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    out = {"id": sid, "stats": stats(eq), "bench": stats(b), "n_trades": len(tr),
           "trades_per_year": len(tr) / years, "skip_chase": r["skip_chase"], "skip_limit": r["skip_limit"],
           "win_rate": float((tr["ret"] > 0).mean()) if len(tr) else np.nan,
           "avg_trade": float(tr["ret"].mean()) if len(tr) else np.nan,
           "avg_days": float(tr["days"].mean()) if len(tr) else np.nan,
           "exit_reasons": tr["reason"].value_counts().to_dict() if len(tr) else {},
           "excess": excess_stats(eq, b), "beats": beats(stats(eq), stats(b))}
    yr_n = tr.groupby(pd.to_datetime(tr["entry_day"]).dt.year).size() if len(tr) else pd.Series(dtype=int)
    out["min_trades_per_year"] = int(yr_n.min()) if len(yr_n) else 0
    ys = eq.resample("YE").last().pct_change()
    ys.iloc[0] = eq.resample("YE").last().iloc[0] / eq.iloc[0] - 1
    yb = b.resample("YE").last().pct_change()
    yb.iloc[0] = b.resample("YE").last().iloc[0] / b.iloc[0] - 1
    out["yearly"] = {str(k.year): [float(ys[k]), float(yb[k])] for k in ys.index}
    out["_eq"], out["_b"], out["_trades"] = eq, b, tr
    if not full:
        return out
    # H5 / 警示：成本 × 1.5、× 2
    for m in (1.5, 2.0):
        e2 = run_system(ctx, sid, start, end, cost_mult=m)["equity"]
        out[f"cost_x{m}"] = stats(e2)
        out[f"cost_x{m}_beats"] = beats(stats(e2), out["bench"])
    # H4 / 警示：錯過最好的 1%、5% 交易
    base = "S1" if sid == "S6" else sid
    for q in (0.01, 0.05):
        k = max(1, int(round(len(tr) * q)))
        top = tr.nlargest(k, "ret")
        blocked = frozenset(zip(top["sid"], pd.to_datetime(top["entry_day"])))
        e3 = run_system(ctx, sid, start, end, blocked=blocked)["equity"]
        out[f"minus_top{int(q * 100)}pct"] = stats(e3)
        out[f"minus_top{int(q * 100)}pct_beats_sharpe"] = stats(e3)["sharpe"] > out["bench"]["sharpe"]
    # H3：隨機選股對照
    rs = []
    for i in range(N_RANDOM):
        e4 = run_system(ctx, sid, start, end, random_seed=1000 + i)["equity"]
        rs.append(stats(e4)["sharpe"])
        if i % 20 == 0:
            log(f"{sid} random {i}/{N_RANDOM}")
    out["random_sharpe_p95"] = float(np.percentile(rs, 95))
    out["random_sharpe_median"] = float(np.median(rs))
    out["random_pctile"] = float((np.array(rs) < out["stats"]["sharpe"]).mean())
    return out


def gates(o: dict, period: str) -> dict:
    need = 300 if period == "selection" else 150
    return {
        "H1": o["n_trades"] >= need and o["min_trades_per_year"] >= 20,
        "H2": o["beats"],
        "H3": o["stats"]["sharpe"] > o["random_sharpe_p95"],
        "H4": o["minus_top1pct_beats_sharpe"],
        "H5": o["cost_x1.5_beats"],
        "H6": o["stats"]["mdd"] >= o["bench"]["mdd"] - 0.10,
    }


def pct(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.1f}%"


def f2(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.2f}"


def clean(o):
    return {k: v for k, v in o.items() if not k.startswith("_")}


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def selection(log=print):
    panel = load_selection_panel()
    ctx = Context(panel)
    start = SPEC["periods"]["selection"][0]
    res = {}
    for sid in ("S1", "S3", "S4", "S5", "S6"):
        log(f"running {sid}")
        res[sid] = evaluate(ctx, sid, start)
    bret = res["S1"]["_b"].pct_change().dropna()
    ex = {k: (v["_eq"].pct_change().dropna() - bret).dropna() for k, v in res.items()}
    sr_var = float(np.var([s.mean() / s.std() for s in ex.values()], ddof=1))
    for k in res:
        res[k]["dsr"] = deflated_sharpe(ex[k], N_TRIALS, sr_var)["dsr"]
    elig = [k for k, v in res.items() if v["beats"]]
    chosen = max(elig, key=lambda k: res[k]["stats"]["sharpe"]) if elig else None
    full = None
    if chosen:
        log(f"chosen {chosen}: running robustness + {N_RANDOM} random controls")
        full = evaluate(ctx, chosen, start, full=True, log=log)
        full["dsr"] = res[chosen]["dsr"]
        full["gates"] = gates(full, "selection")
    out = {"period": "selection", "start": start, "end": str(ctx.cal[-1].date()), "commit": git_head(),
           "results": {k: clean(v) for k, v in res.items()}, "eligible": elig, "chosen": chosen,
           "chosen_full": clean(full) if full else None}
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "swing_selection.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = report_md(out)
    (rep / "swing_selection.md").write_text(md, encoding="utf-8")
    log_trials(res, "swing-selection")
    print(md)
    return out


def holdout(system: str, log=print):
    f = ROOT / "reports" / "swing_holdout.json"
    if f.exists():
        raise SystemExit("保留期已經跑過一次，依規格不得重跑（刪除檔案重跑等於違反事前登錄）。")
    panel = load_holdout_panel()
    ctx = Context(panel)
    start, end = SPEC["periods"]["holdout"]
    o = evaluate(ctx, system, start, end, full=True, log=log)
    o["gates"] = gates(o, "holdout")
    out = {"period": "holdout", "start": start, "end": end, "commit": git_head(), "system": system,
           "result": clean(o), "passed": all(o["gates"].values())}
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = report_md({"period": "holdout", "start": start, "end": end, "commit": out["commit"],
                    "results": {system: clean(o)}, "eligible": [system] if o["beats"] else [], "chosen": system,
                    "chosen_full": clean(o)})
    (ROOT / "reports" / "swing_holdout.md").write_text(md, encoding="utf-8")
    print(md)
    return out


def log_trials(res, round_name):
    tl = ROOT / "reports" / "trials_log.csv"
    old = pd.read_csv(tl) if tl.exists() else pd.DataFrame()
    if "round" in old:
        old = old[old["round"].astype(str) != round_name]
    n0 = 61
    rows = [{"trial": n0 + i + 1, "id": k, "round": round_name, "full_cagr": v["stats"]["cagr"],
             "full_sharpe": v["stats"]["sharpe"]} for i, (k, v) in enumerate(res.items())]
    pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(tl, index=False)


def report_md(out) -> str:
    names = {s["id"]: s["name"] for s in SPEC["systems"]}
    L = [f"# 選股 + 進出場系統：{'選擇期' if out['period'] == 'selection' else '保留期（只跑一次）'} {out['start']} ～ {out['end']}\n",
         f"程式版本 `{out['commit'][:10]}`；規格 `quant/swing_spec.json`。全部扣成本；空槽放 0050。\n",
         "> ⚠️ 研究紀錄，非投資建議。下單由使用者本人決定。\n",
         "| 系統 | 年化 | Sharpe | MDD | 波動 | 交易數 | 年交易 | 勝率 | 平均每筆 | 平均天數 | 月超額 t | 贏 0050？ |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    b = None
    for k, v in out["results"].items():
        s = v["stats"]
        b = v["bench"]
        L.append(f"| {k} {names.get(k, '')} | {pct(s['cagr'])} | {f2(s['sharpe'])} | {pct(s['mdd'])} | {pct(s['vol'])} | "
                 f"{v['n_trades']} | {v['trades_per_year']:.0f} | {pct(v['win_rate'])} | {pct(v['avg_trade'])} | "
                 f"{f2(v['avg_days'])} | {f2(v['excess']['t_stat'])} | {'✅' if v['beats'] else '❌'} |")
    L.append(f"| 0050 買進持有 | {pct(b['cagr'])} | {f2(b['sharpe'])} | {pct(b['mdd'])} | {pct(b['vol'])} | — | — | — | — | — | — | — |\n")
    ch = out["chosen"]
    L.append(f"同時贏 0050 的系統：{', '.join(out['eligible']) or '無'}；依規則選出：**{ch or '無'}**\n")
    f = out.get("chosen_full")
    if f:
        g = f["gates"]
        ok = lambda x: "✅" if x else "❌"
        L.append("## 硬門檻\n")
        L.append(f"- H1 交易筆數（{f['n_trades']} 筆，最少一年 {f['min_trades_per_year']} 筆）：{ok(g['H1'])}")
        L.append(f"- H2 年化與 Sharpe 都贏 0050：{ok(g['H2'])}")
        L.append(f"- H3 Sharpe {f2(f['stats']['sharpe'])} > 隨機選股第 95 百分位 {f2(f['random_sharpe_p95'])}（中位數 {f2(f['random_sharpe_median'])}，策略排第 {pct(f['random_pctile'])}）：{ok(g['H3'])}")
        L.append(f"- H4 錯過最好 1% 交易後 Sharpe {f2(f['minus_top1pct']['sharpe'])} vs 0050 {f2(f['bench']['sharpe'])}：{ok(g['H4'])}")
        L.append(f"- H5 成本 ×1.5：年化 {pct(f['cost_x1.5']['cagr'])}、Sharpe {f2(f['cost_x1.5']['sharpe'])}：{ok(g['H5'])}")
        L.append(f"- H6 MDD {pct(f['stats']['mdd'])} vs 0050 {pct(f['bench']['mdd'])}（容許差 10 點）：{ok(g['H6'])}\n")
        L.append("## 警示\n")
        L.append(f"- 錯過最好 5% 交易：Sharpe {f2(f['minus_top5pct']['sharpe'])}（{'仍贏' if f['minus_top5pct_beats_sharpe'] else '輸'} 0050）")
        L.append(f"- 成本 ×2：年化 {pct(f['cost_x2.0']['cagr'])}、Sharpe {f2(f['cost_x2.0']['sharpe'])}")
        L.append(f"- Deflated Sharpe（N={N_TRIALS}）：{f2(f.get('dsr'))}")
        L.append(f"- 月超額 t 值：{f2(f['excess']['t_stat'])}")
        L.append(f"- 因不追高跳過的訊號：{f['skip_chase']} 次；開盤漲停買不到：{f['skip_limit']} 次")
        L.append(f"- 出場原因：{f['exit_reasons']}\n")
        L.append("## 逐年\n\n| 年 | 系統 | 0050 | 差 |\n|---|---:|---:|---:|")
        for y, (a, bb) in f["yearly"].items():
            L.append(f"| {y} | {pct(a)} | {pct(bb)} | {pct(a - bb)} |")
    L.append("\n---\n_由 `python -m quant.swing_study` 產生。研究紀錄，非投資建議。_")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["selection", "holdout"])
    ap.add_argument("--system")
    a = ap.parse_args()
    if a.mode == "selection":
        selection()
    else:
        holdout(a.system)
