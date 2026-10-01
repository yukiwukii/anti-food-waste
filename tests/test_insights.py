from datetime import date, timedelta

from app.insights import cook_less, serve_less, totals

MON = date(2026, 9, 21)
WEEK = [MON + timedelta(days=i) for i in range(7)]
INGREDIENTS = {
    "White rice": {"name": "White rice", "cooked_per_raw": 2.5, "cost_per_raw_kg": 2.0},
    "Roast chicken": {"name": "Roast chicken", "cooked_per_raw": 0.75, "cost_per_raw_kg": 7.0},
}
MENU = {"items": [{"name": "Roasted chicken rice", "recipe": [
    {"ingredient": "White rice", "grams": 250}, {"ingredient": "Roast chicken", "grams": 110}]}]}


def test_cook_less_converts_steady_leftovers_to_raw_kg():
    unsold = {"White rice": {d: 5.0 for d in WEEK}}
    [row] = cook_less(WEEK, unsold, INGREDIENTS)
    assert row["avg_unsold_cooked_kg"] == 5.0  # weekdays only, no variation
    assert row["cut_cooked_kg"] == 5.0
    assert row["cut_raw_kg"] == 2.0  # 5 kg cooked / 2.5
    assert row["sgd_per_day"] == 4.0


def test_cook_less_keeps_a_buffer_when_leftovers_vary():
    unsold = {"Roast chicken": {WEEK[0]: 0.0, WEEK[1]: 2.0, WEEK[2]: 0.0, WEEK[3]: 2.0, WEEK[4]: 1.0}}
    [row] = cook_less(WEEK, unsold, INGREDIENTS)
    assert row["avg_unsold_cooked_kg"] == 1.0
    assert row["cut_cooked_kg"] < 1.0


def test_cook_less_ignores_unknown_ingredients():
    assert cook_less(WEEK, {"Unidentified": {MON: 3.0}}, INGREDIENTS) == []


def test_serve_less_suggests_smaller_servings():
    plates = {"Roasted chicken rice": 50}  # 10 plates per weekday
    left = {("Roasted chicken rice", "White rice"): 50 * 0.060}  # 60 g rice left per plate
    [row] = serve_less(WEEK, plates, left, MENU, INGREDIENTS)
    assert row["avg_left_g"] == 60 and row["left_pct"] == 24
    assert row["cut_g"] == 50 and row["new_serving_g"] == 200  # 80% of 60 g, rounded to 5 g
    assert row["cut_raw_kg_per_day"] == 0.2  # 50 g x 10 plates / 2.5


def test_serve_less_needs_enough_plates():
    assert serve_less(WEEK, {"Roasted chicken rice": 2}, {("Roasted chicken rice", "White rice"): 1.0}, MENU, INGREDIENTS) == []


def test_totals_add_both_kinds_of_advice():
    t = totals([{"cut_raw_kg": 2.0, "sgd_per_day": 4.0}], [{"cut_raw_kg_per_day": 0.5, "sgd_per_day": 1.0}])
    assert t == {"cut_raw_kg_per_day": 2.5, "sgd_per_day": 5.0, "sgd_per_month": 110.0}
