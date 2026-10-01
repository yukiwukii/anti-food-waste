from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.models import Drop, PrepLog
from app.seed import ensure_reference_data, refresh_demo_history


def make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    ensure_reference_data(session)
    return session


def last_demo_day(session):
    return session.exec(select(func.max(PrepLog.day)).where(col(PrepLog.is_demo))).one()


def test_stale_demo_window_moves_forward(tmp_path):
    s = make_session(tmp_path)
    refresh_demo_history(s, today=date(2026, 10, 1))
    assert last_demo_day(s) == date(2026, 9, 30)
    s.add(PrepLog(stall_id="cr", day=date(2026, 10, 1), portions=200))  # real entry
    s.commit()

    refresh_demo_history(s, today=date(2026, 10, 9))
    assert last_demo_day(s) == date(2026, 10, 8)
    first = s.exec(select(func.min(PrepLog.day)).where(col(PrepLog.is_demo))).one()
    assert first == date(2026, 10, 8) - timedelta(days=13)
    # The real prep log survives and is not duplicated by demo data.
    rows = s.exec(select(PrepLog).where(PrepLog.stall_id == "cr", PrepLog.day == date(2026, 10, 1))).all()
    assert [(r.portions, r.is_demo) for r in rows] == [(200, False)]
    assert s.exec(select(Drop).where(Drop.classified_by == "seed").limit(1)).first() is not None


def test_fresh_window_is_left_alone(tmp_path):
    s = make_session(tmp_path)
    refresh_demo_history(s, today=date(2026, 10, 1))
    count = len(s.exec(select(PrepLog)).all())
    refresh_demo_history(s, today=date(2026, 10, 1))
    assert len(s.exec(select(PrepLog)).all()) == count
