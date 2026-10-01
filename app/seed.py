"""Reference data for NTU North Spine and South Spine, plus optional demo history.

Demo history is generated with a fixed seed. Its weigh-ins are marked classified_by="seed" and its
prep logs and compost transfers is_demo=True, so it is never mistaken for real data and can be
removed and regenerated. The window always ends yesterday, so the chart has no gap on the day of a demo.
"""

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from .config import now
from .models import Bin, CompostTransfer, Drop, Location, PrepLog, Stall

LOCATIONS = [
    Location(id="NS", name="North Spine"),
    Location(id="SS", name="South Spine"),
]
BINS = [
    Bin(id="NS-01", location_id="NS"),
    Bin(id="SS-01", location_id="SS"),
]
# (id, location, name, portion grams, S$ cost per portion, menu, typical weekday demand, typical weekday prep)
STALL_SPECS = [
    ("cr", "NS", "Chicken Rice", 350, 1.20, ["Roasted chicken rice", "Steamed chicken rice"], 180, 215),
    ("mv", "NS", "Mixed Veg Rice", 400, 1.50, ["Mixed veg rice", "Curry vegetables"], 210, 250),
    ("we", "NS", "Western", 380, 2.20, ["Chicken chop", "Fish and chips", "Spaghetti"], 120, 150),
    ("in", "NS", "Indian", 400, 1.60, ["Briyani", "Prata", "Thosai"], 95, 120),
    ("bm", "SS", "Ban Mian", 450, 1.30, ["Ban mian soup", "Dry ban mian"], 140, 165),
    ("ml", "SS", "Mala Xiang Guo", 420, 2.50, ["Mala xiang guo", "Mala soup"], 110, 140),
    ("jp", "SS", "Japanese", 380, 2.00, ["Chicken katsu don", "Ramen", "Teriyaki bento"], 100, 125),
]


def ensure_reference_data(session: Session) -> None:
    if session.get(Location, "NS"):
        return
    for loc in LOCATIONS:
        session.add(Location.model_validate(loc))
    session.flush()
    for b in BINS:
        session.add(Bin.model_validate(b))
    for sid, loc, name, portion, cost, menu, _, _ in STALL_SPECS:
        session.add(Stall(id=sid, location_id=loc, name=name, portion_g=portion, cost_per_portion=cost, menu=menu))
    session.commit()


DEMO_DAYS = 14


def clear_demo_history(session: Session) -> None:
    session.exec(delete(Drop).where(Drop.classified_by == "seed"))
    session.exec(delete(CompostTransfer).where(col(CompostTransfer.is_demo)))
    session.exec(delete(PrepLog).where(col(PrepLog.is_demo)))
    session.commit()


def reset_demo_history(session: Session, today: date | None = None) -> None:
    """Replace the demo history with a fresh window ending yesterday. Real data is kept."""
    clear_demo_history(session)
    seed_demo_history(session, today=today)


def refresh_demo_history(session: Session, today: date | None = None) -> None:
    """At startup: add demo history to a new database, or move a stale window forward to end yesterday."""
    today = today or now().date()
    last_demo_day = session.exec(select(func.max(PrepLog.day)).where(col(PrepLog.is_demo))).one()
    if last_demo_day is None:
        if session.exec(select(PrepLog).limit(1)).first() is None:
            seed_demo_history(session, today=today)
    elif last_demo_day < today - timedelta(days=1):
        reset_demo_history(session, today=today)


def seed_demo_history(session: Session, days: int = DEMO_DAYS, today: date | None = None) -> None:
    """Add `days` of demo history ending yesterday. Stall-days that already have a real prep log are skipped."""
    today = today or now().date()
    real_days = {(p.stall_id, p.day) for p in session.exec(select(PrepLog).where(~col(PrepLog.is_demo)))}
    rng = random.Random(20261001)
    bin_for_loc = {b.location_id: b.id for b in BINS}

    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        weekend = day.weekday() >= 5
        day_drops: dict[str, list[Drop]] = {b.id: [] for b in BINS}
        for sid, loc, _name, portion, _cost, menu, base, prep in STALL_SPECS:
            demand = max(10, round(base * (0.5 if weekend else 1) * rng.gauss(1, 0.08)))
            prepared = round(prep * (0.7 if weekend else 1) * rng.gauss(1, 0.04))
            sold = min(prepared, demand)
            unsold = prepared - sold
            if (sid, day) in real_days:
                continue
            session.add(PrepLog(stall_id=sid, day=day, portions=prepared, is_demo=True))
            bin_id = bin_for_loc[loc]

            # Customer plate waste through the day; only eat-in meals reach the bin.
            for _ in range(max(1, round(sold * 0.65 * 0.12))):
                t = datetime.combine(day, time(11, 0)) + timedelta(minutes=rng.randint(0, 540))
                day_drops[bin_id].append(Drop(
                    bin_id=bin_id, stall_id=sid, source="plate",
                    weight_kg=(w := round(rng.uniform(0.04, 0.25), 3)), waste_kg=w,
                    dish=rng.choice(menu), confidence=round(rng.uniform(0.8, 0.97), 2),
                    classified_by="seed", created_at=t,
                ))
            # Vendor dumps unsold food at closing.
            if unsold > 0:
                day_drops[bin_id].append(Drop(
                    bin_id=bin_id, stall_id=sid, source="vendor",
                    weight_kg=(w := round(unsold * portion / 1000, 3)), waste_kg=w,
                    dish=menu[0], confidence=0.95, classified_by="seed",
                    created_at=datetime.combine(day, time(20, 30)) + timedelta(minutes=rng.randint(0, 25)),
                ))

        # Staff empty each bin into compost after closing.
        for bin_id, drops in day_drops.items():
            if not drops:
                continue
            transfer = CompostTransfer(
                bin_id=bin_id,
                weight_kg=round(sum(d.weight_kg for d in drops), 3),
                created_at=datetime.combine(day, time(21, 15)),
                is_demo=True,
            )
            session.add(transfer)
            session.flush()
            for d in drops:
                d.transfer_id = transfer.id
                session.add(d)
    session.commit()
