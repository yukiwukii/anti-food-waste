"""Turn bin weigh-ins into a daily prep suggestion for a vendor.

For each day we know how many portions the vendor cooked (PrepLog) and how much unsold food
they dropped in the bin at closing (vendor drops). Unsold portions = unsold kg / portion size,
so portions sold = cooked - unsold. The suggestion is average weekday sales plus half a
standard deviation, so the stall rarely sells out.
"""

import math
from dataclasses import dataclass
from datetime import date
from statistics import mean, pstdev

SAFETY_SD = 0.5
OPEN_DAYS_PER_MONTH = 22


@dataclass
class DayRow:
    day: date
    prepared: int
    unsold_kg: float
    plate_kg: float
    unsold: int
    sold: int
    weekend: bool


def build_day(day: date, prepared: int, unsold_kg: float, plate_kg: float, portion_g: int) -> DayRow:
    unsold = min(prepared, round(unsold_kg * 1000 / portion_g))
    return DayRow(
        day=day,
        prepared=prepared,
        unsold_kg=round(unsold_kg, 3),
        plate_kg=round(plate_kg, 3),
        unsold=unsold,
        sold=prepared - unsold,
        weekend=day.weekday() >= 5,
    )


def suggest(rows: list[DayRow], portion_g: int, cost_per_portion: float) -> dict | None:
    weekdays = [r for r in rows if not r.weekend]
    if len(weekdays) < 3:
        return None
    sold = [r.sold for r in weekdays]
    avg_sold = mean(sold)
    sd = pstdev(sold)
    avg_prepared = mean(r.prepared for r in weekdays)
    avg_unsold = mean(r.unsold for r in weekdays)
    suggested = math.ceil(avg_sold + SAFETY_SD * sd)
    cut = max(0, round(avg_prepared - suggested))
    return {
        "weekdays_used": len(weekdays),
        "avg_prepared": round(avg_prepared, 1),
        "avg_sold": round(avg_sold, 1),
        "avg_unsold": round(avg_unsold, 1),
        "sd_sold": round(sd, 1),
        "waste_pct": round(avg_unsold / avg_prepared * 100, 1) if avg_prepared else 0.0,
        "suggested_prep": suggested,
        "portions_saved_per_day": cut,
        "kg_saved_per_day": round(cut * portion_g / 1000, 1),
        "sgd_saved_per_day": round(cut * cost_per_portion, 2),
        "sgd_saved_per_month": round(cut * cost_per_portion * OPEN_DAYS_PER_MONTH, 2),
    }
