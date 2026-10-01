from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Drop, DropIngredient
from app.seed import ensure_reference_data, refresh_demo_history


def make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    ensure_reference_data(session)
    return session


def last_demo_day(session):
    return session.exec(select(func.max(Drop.created_at)).where(Drop.classified_by == "seed")).one().date()


def test_stale_demo_window_moves_forward_and_keeps_real_data(tmp_path):
    s = make_session(tmp_path)
    refresh_demo_history(s, today=date(2026, 10, 1))
    assert last_demo_day(s) == date(2026, 9, 30)
    s.add(Drop(bin_id="NS-01", stall_id="cr", source="plate", weight_kg=0.1, waste_kg=0.1, classified_by="device"))
    s.commit()

    refresh_demo_history(s, today=date(2026, 10, 9))
    assert last_demo_day(s) == date(2026, 10, 8)
    first = s.exec(select(func.min(Drop.created_at)).where(Drop.classified_by == "seed")).one().date()
    assert first == date(2026, 10, 8) - timedelta(days=13)
    assert s.exec(select(Drop).where(Drop.classified_by == "device")).first() is not None
    assert s.exec(select(DropIngredient).limit(1)).first() is not None


def test_fresh_window_is_left_alone(tmp_path):
    s = make_session(tmp_path)
    refresh_demo_history(s, today=date(2026, 10, 1))
    count = len(s.exec(select(Drop)).all())
    refresh_demo_history(s, today=date(2026, 10, 1))
    assert len(s.exec(select(Drop)).all()) == count


def test_old_weigh_ins_get_split_by_recipe(tmp_path):
    from app.seed import backfill_drop_ingredients

    s = make_session(tmp_path)
    s.add(Drop(bin_id="NS-01", stall_id="cr", source="vendor", weight_kg=3.9, waste_kg=3.9, dish="Roasted chicken rice"))
    s.add(Drop(bin_id="NS-01", stall_id="cr", source="plate", weight_kg=0.2, waste_kg=0.0, is_waste=False))
    s.commit()
    assert backfill_drop_ingredients(s) == 1
    parts = {p.ingredient: p.waste_kg for p in s.exec(select(DropIngredient)).all()}
    assert parts == {"White rice": 2.5, "Roast chicken": 1.1, "Cucumber": 0.3}
    assert backfill_drop_ingredients(s) == 0
