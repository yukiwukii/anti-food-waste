"""Reference data for NTU North Spine and South Spine, plus optional demo history.

Demo history is generated with a fixed seed and is marked classified_by="seed",
so it is never mistaken for real weigh-ins.
"""

import random
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

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


def seed_demo_history(session: Session, days: int = 14, today: date | None = None) -> bool:
    """Add `days` of history before today. Skips if any prep log already exists."""
    if session.exec(select(PrepLog).limit(1)).first():
        return False
    today = today or now().date()
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
            session.add(PrepLog(stall_id=sid, day=day, portions=prepared))
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
            transfer = CompostTransfer(
                bin_id=bin_id,
                weight_kg=round(sum(d.weight_kg for d in drops), 3),
                created_at=datetime.combine(day, time(21, 15)),
            )
            session.add(transfer)
            session.flush()
            for d in drops:
                d.transfer_id = transfer.id
                session.add(d)
    session.commit()
    return True
