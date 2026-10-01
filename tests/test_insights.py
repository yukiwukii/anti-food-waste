from datetime import date, timedelta

from app.insights import build_day, suggest


def test_build_day_converts_unsold_kg_to_portions():
    row = build_day(date(2026, 9, 30), prepared=200, unsold_kg=7.0, plate_kg=1.2, portion_g=350)
    assert row.unsold == 20
    assert row.sold == 180
    assert not row.weekend


def test_build_day_caps_unsold_at_prepared():
    row = build_day(date(2026, 9, 30), prepared=10, unsold_kg=50.0, plate_kg=0, portion_g=350)
    assert row.unsold == 10
    assert row.sold == 0


def test_suggest_uses_weekdays_only():
    start = date(2026, 9, 21)  # Monday
    rows = [build_day(start + timedelta(days=i), 200, 7.0, 0, 350) for i in range(7)]
    s = suggest(rows, 350, 1.20)
    assert s["weekdays_used"] == 5
    assert s["avg_sold"] == 180
    assert s["suggested_prep"] == 180  # no variation, so no safety margin
    assert s["portions_saved_per_day"] == 20
    assert s["sgd_saved_per_month"] == 20 * 1.20 * 22


def test_suggest_needs_three_weekdays():
    rows = [build_day(date(2026, 9, 21), 200, 7.0, 0, 350)]
    assert suggest(rows, 350, 1.20) is None
