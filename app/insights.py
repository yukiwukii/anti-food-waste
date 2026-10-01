"""Turn per-ingredient bin weigh-ins into advice a vendor can act on.

Cook less: food the vendor throws away at closing is food they cooked but did not sell. For each
ingredient we take the weekday average of unsold cooked kg, keep a safety buffer of half a standard
deviation so the stall rarely runs out, and convert the rest to raw kg with the ingredient's
cooked/raw ratio.

Serve less: food customers leave on their plates means the serving is bigger than people eat. For
each dish and ingredient we take the average grams left per plate that reached the bin and suggest
cutting the serving by most of that.

All weights from the bin are cooked weights.
"""

from datetime import date
from statistics import mean, pstdev

SAFETY_SD = 0.5
OPEN_DAYS_PER_MONTH = 22
SERVE_LESS_SHARE = 0.8  # cut servings by 80% of what is left, so plates aren't scraped clean
MIN_PLATES = 5
MIN_LEFT_G = 15


def cook_less(days: list[date], unsold: dict[str, dict[date, float]], ingredients: dict[str, dict]) -> list[dict]:
    """unsold[ingredient][day] = cooked kg thrown away by the vendor that day."""
    weekdays = [d for d in days if d.weekday() < 5]
    if len(weekdays) < 3:
        return []
    rows = []
    for name, by_day in unsold.items():
        if name not in ingredients:
            continue  # unidentified food, or an ingredient no longer on the menu
        series = [by_day.get(d, 0.0) for d in weekdays]
        avg, sd = mean(series), pstdev(series)
        cut_cooked = max(0.0, avg - SAFETY_SD * sd)
        ing = ingredients[name]
        cut_raw = cut_cooked / ing["cooked_per_raw"]
        rows.append({
            "ingredient": name,
            "avg_unsold_cooked_kg": round(avg, 2),
            "sd_cooked_kg": round(sd, 2),
            "cut_cooked_kg": round(cut_cooked, 2),
            "cut_raw_kg": round(cut_raw, 2),
            "cooked_per_raw": ing["cooked_per_raw"],
            "sgd_per_day": round(cut_raw * ing["cost_per_raw_kg"], 2),
        })
    rows.sort(key=lambda r: r["cut_raw_kg"] * 1000 + r["sgd_per_day"], reverse=True)
    return rows


def serve_less(
    days: list[date],
    plates: dict[str, int],
    plate_left: dict[tuple[str, str], float],
    menu: dict,
    ingredients: dict[str, dict],
) -> list[dict]:
    """plates[dish] = weekday plates of that dish that reached the bin;
    plate_left[(dish, ingredient)] = weekday cooked kg of that ingredient left on those plates."""
    weekdays = [d for d in days if d.weekday() < 5]
    if not weekdays:
        return []
    rows = []
    for item in menu["items"]:
        n = plates.get(item["name"], 0)
        if n < MIN_PLATES:
            continue
        for line in item["recipe"]:
            name = line["ingredient"]
            left_g = plate_left.get((item["name"], name), 0.0) * 1000 / n
            if left_g < MIN_LEFT_G or name not in ingredients:
                continue
            cut_g = min(line["grams"] * 0.5, round(left_g * SERVE_LESS_SHARE / 5) * 5)
            plates_per_day = n / len(weekdays)
            cut_raw_kg = cut_g * plates_per_day / 1000 / ingredients[name]["cooked_per_raw"]
            rows.append({
                "dish": item["name"],
                "ingredient": name,
                "plates_per_day": round(plates_per_day, 1),
                "serving_g": line["grams"],
                "avg_left_g": round(left_g),
                "left_pct": round(left_g / line["grams"] * 100),
                "cut_g": cut_g,
                "new_serving_g": line["grams"] - cut_g,
                "cut_raw_kg_per_day": round(cut_raw_kg, 2),
                "sgd_per_day": round(cut_raw_kg * ingredients[name]["cost_per_raw_kg"], 2),
            })
    rows.sort(key=lambda r: r["avg_left_g"], reverse=True)
    return rows


def totals(cook: list[dict], serve: list[dict]) -> dict:
    per_day = sum(r["sgd_per_day"] for r in cook) + sum(r["sgd_per_day"] for r in serve)
    return {
        "cut_raw_kg_per_day": round(sum(r["cut_raw_kg"] for r in cook) + sum(r["cut_raw_kg_per_day"] for r in serve), 2),
        "sgd_per_day": round(per_day, 2),
        "sgd_per_month": round(per_day * OPEN_DAYS_PER_MONTH, 2),
    }
