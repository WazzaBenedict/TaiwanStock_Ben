# daytrade/ 台股當沖研究工具

## 台股時光機 (Time Machine)

Replays a long day-trade plan 10,000 times from the stock's own last 60 sessions of
5-minute bars, and re-runs the same rule on each of those sessions. All results are
**net of costs**: commission (default 6折, NT$20 minimum), the 0.15% day-trade sell tax,
and 1 tick of slippage on each market fill.

The method is adapted from `trader-timemachine` in
[Jake Schincariol's day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT). Here it is re-implemented for Taiwan: 09:00–13:30 session (54 bars), long only,
FinMind minute data, and costs included.

```bash
# needs FINMIND_TOKEN in the environment; TaiwanStockKBar may need a paid tier
python -m daytrade.timemachine 2330 2026-10-30                    # opening-range breakout plan, auto
python -m daytrade.timemachine 2330 2026-10-30 --entry 1050 --stop 1040 --target 1070 --entry-time 10:15
python -m daytrade.timemachine 2330 2026-10-30 --offline bars.json --json
python -m daytrade.test_daytrade                                   # tests, synthetic data, no network
```

API: `GET /api/daytrade/timemachine?stock_id=2330&date=2026-10-30` (see `api.py` for options).
App: the ⏳ 時光機 tab.

Minute bars are cached in `daytrade/cache/` (git-ignored). It is a simulation, not a
prediction, and not investment advice.
