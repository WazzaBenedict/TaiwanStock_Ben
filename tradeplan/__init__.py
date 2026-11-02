"""交易計畫 v2：進場價、停損、停利、何時賣、部位大小，以及同一套規則的扣成本歷史成績。

純函式、不連網，方便測試；資料抓取與 API 掛載在 app.py。
"""
from .rules import PlanRules, make_plan, position_size, tick_size, round_tick  # noqa: F401
from .simulate import simulate, summarize, random_entry_control  # noqa: F401
