"""Reference data for NTU North Spine and South Spine, example menus, and optional demo history.

Example menus are marked is_example. Demo weigh-ins are marked classified_by="seed" and demo
compost transfers is_demo, so they are never mistaken for real data and can be regenerated.
The demo window always ends yesterday, so the chart has no gap on the day of a demo.
"""

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from .config import now
from .menu import MenuIn, recipe_split, replace_menu
from .models import Bin, CompostTransfer, Drop, DropIngredient, Location, MenuItem, PrepLog, Stall

LOCATIONS = [
    Location(id="NS", name="North Spine"),
    Location(id="SS", name="South Spine"),
]
BINS = [
    Bin(id="NS-01", location_id="NS"),
    Bin(id="SS-01", location_id="SS"),
]
STALLS = [("cr", "NS", "Chicken Rice"), ("mv", "NS", "Mixed Veg Rice"), ("we", "NS", "Western"),
          ("in", "NS", "Indian"), ("bm", "SS", "Ban Mian"), ("ml", "SS", "Mala Xiang Guo"), ("jp", "SS", "Japanese")]

# Example menus. Ingredients: (name, cooked weight / raw weight, S$ per raw kg).
# Items: (name, [(ingredient, cooked grams per portion), ...]). Made-up but plausible figures.
EXAMPLE_MENUS = {
    "cr": (
        [("White rice", 2.5, 2.0), ("Roast chicken", 0.75, 7.0), ("Steamed chicken", 0.8, 7.0), ("Cucumber", 1.0, 3.0)],
        [("Roasted chicken rice", [("White rice", 250), ("Roast chicken", 110), ("Cucumber", 30)]),
         ("Steamed chicken rice", [("White rice", 250), ("Steamed chicken", 110), ("Cucumber", 30)])],
    ),
    "mv": (
        [("White rice", 2.5, 2.0), ("Stir-fried vegetables", 0.85, 4.0), ("Meat dishes", 0.75, 9.0),
         ("Tofu", 1.0, 4.0), ("Curry vegetables", 1.1, 4.5)],
        [("Mixed veg rice", [("White rice", 220), ("Stir-fried vegetables", 120), ("Meat dishes", 100), ("Tofu", 50)]),
         ("Curry vegetables", [("White rice", 220), ("Curry vegetables", 180)])],
    ),
    "we": (
        [("Chicken", 0.75, 7.0), ("Fries", 0.7, 4.0), ("Coleslaw", 1.0, 3.5), ("Fish fillet", 0.8, 12.0),
         ("Spaghetti", 2.2, 4.0), ("Tomato sauce", 1.0, 5.0)],
        [("Chicken chop", [("Chicken", 180), ("Fries", 120), ("Coleslaw", 60)]),
         ("Fish and chips", [("Fish fillet", 160), ("Fries", 150), ("Coleslaw", 60)]),
         ("Spaghetti", [("Spaghetti", 280), ("Tomato sauce", 120)])],
    ),
    "in": (
        [("Briyani rice", 2.5, 3.5), ("Mutton", 0.7, 14.0), ("Prata", 0.9, 3.0), ("Dal curry", 3.0, 4.0), ("Thosai", 1.0, 2.5)],
        [("Briyani", [("Briyani rice", 300), ("Mutton", 120)]),
         ("Prata", [("Prata", 160), ("Dal curry", 120)]),
         ("Thosai", [("Thosai", 180), ("Dal curry", 120)])],
    ),
    "bm": (
        [("Ban mian noodles", 1.6, 3.0), ("Minced pork", 0.75, 9.0), ("Leafy vegetables", 0.85, 4.0), ("Egg", 1.0, 4.0)],
        [("Ban mian soup", [("Ban mian noodles", 250), ("Minced pork", 60), ("Leafy vegetables", 50), ("Egg", 50)]),
         ("Dry ban mian", [("Ban mian noodles", 250), ("Minced pork", 60), ("Leafy vegetables", 50), ("Egg", 50)])],
    ),
    "ml": (
        [("Mala vegetables", 0.85, 5.0), ("Mala meats", 0.8, 12.0), ("Instant noodles", 2.0, 4.0)],
        [("Mala xiang guo", [("Mala vegetables", 200), ("Mala meats", 120), ("Instant noodles", 80)]),
         ("Mala soup", [("Mala vegetables", 180), ("Mala meats", 100), ("Instant noodles", 100)])],
    ),
    "jp": (
        [("Japanese rice", 2.4, 3.0), ("Chicken katsu", 0.85, 8.0), ("Egg", 1.0, 4.0), ("Ramen noodles", 1.8, 4.0),
         ("Chashu pork", 0.7, 11.0), ("Teriyaki chicken", 0.75, 7.5)],
        [("Chicken katsu don", [("Japanese rice", 250), ("Chicken katsu", 140), ("Egg", 50)]),
         ("Ramen", [("Ramen noodles", 200), ("Chashu pork", 70), ("Egg", 50)]),
         ("Teriyaki bento", [("Japanese rice", 250), ("Teriyaki chicken", 130)])],
    ),
}


def example_menu(stall_id: str) -> MenuIn:
    ingredients, items = EXAMPLE_MENUS[stall_id]
    return MenuIn.model_validate({
        "ingredients": [{"name": n, "cooked_per_raw": f, "cost_per_raw_kg": c} for n, f, c in ingredients],
        "items": [{"name": n, "recipe": [{"ingredient": i, "grams": g} for i, g in lines]} for n, lines in items],
    })


def ensure_reference_data(session: Session) -> None:
    if not session.get(Location, "NS"):
        for loc in LOCATIONS:
            session.add(Location.model_validate(loc))
        session.flush()
        for b in BINS:
            session.add(Bin.model_validate(b))
        for sid, loc, name in STALLS:
            # portion_g / cost_per_portion are left over from the portion-based model and no longer used.
            session.add(Stall(id=sid, location_id=loc, name=name, portion_g=0, cost_per_portion=0, menu=[]))
        session.commit()
    # Give every stall without a menu the example one.
    for sid, _, _ in STALLS:
        if session.exec(select(MenuItem).where(MenuItem.stall_id == sid).limit(1)).first() is None:
            replace_menu(session, session.get(Stall, sid), example_menu(sid), is_example=True)


DEMO_DAYS = 14


def clear_demo_history(session: Session) -> None:
    seed_ids = select(Drop.id).where(Drop.classified_by == "seed")
    session.exec(delete(DropIngredient).where(col(DropIngredient.drop_id).in_(seed_ids)))
    session.exec(delete(Drop).where(Drop.classified_by == "seed"))
    session.exec(delete(CompostTransfer).where(col(CompostTransfer.is_demo)))
    session.exec(delete(PrepLog).where(col(PrepLog.is_demo)))  # from the old portion-based demo
    session.commit()


def reset_demo_history(session: Session, today: date | None = None) -> None:
    """Replace the demo history with a fresh window ending yesterday. Real data is kept."""
    clear_demo_history(session)
    seed_demo_history(session, today=today)


def _has_ingredient_demo(session: Session) -> bool:
    return session.exec(
        select(DropIngredient.id).join(Drop, col(Drop.id) == DropIngredient.drop_id).where(Drop.classified_by == "seed").limit(1)
    ).first() is not None


def refresh_demo_history(session: Session, today: date | None = None) -> None:
    """At startup: add demo history to a new database, or regenerate it when it is stale or outdated."""
    today = today or now().date()
    last = session.exec(select(func.max(Drop.created_at)).where(Drop.classified_by == "seed")).one()
    if last is None:
        if session.exec(select(Drop.id).limit(1)).first() is None:
            seed_demo_history(session, today=today)
    elif last.date() < today - timedelta(days=1) or not _has_ingredient_demo(session):
        reset_demo_history(session, today=today)


def _stall_menus(session: Session) -> dict:
    from .menu import get_menu

    return {sid: get_menu(session, sid) for sid, _, _ in STALLS}


def seed_demo_history(session: Session, days: int = DEMO_DAYS, today: date | None = None) -> None:
    """Add `days` of demo weigh-ins ending yesterday, each split by ingredient."""
    today = today or now().date()
    rng = random.Random(20261001)
    menus = _stall_menus(session)
    loc_of = {sid: loc for sid, loc, _ in STALLS}
    bin_for_loc = {b.location_id: b.id for b in BINS}
    # How much of each ingredient a stall typically over-cooks on a weekday, in cooked kg:
    # its average grams per portion times a number of surplus portions that varies by ingredient.
    overcook = {}
    for sid, menu in menus.items():
        grams: dict[str, list[float]] = {}
        for item in menu["items"]:
            for line in item["recipe"]:
                grams.setdefault(line["ingredient"], []).append(line["grams"])
        overcook[sid] = {
            name: round(sum(g) / len(g) / 1000 * rng.uniform(4, 25), 2) for name, g in grams.items()
        }

    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        weekend = day.weekday() >= 5
        day_drops: dict[str, list[tuple[Drop, list[tuple[str, float]]]]] = {b.id: [] for b in BINS}
        for sid, menu in menus.items():
            bin_id = bin_for_loc[loc_of[sid]]
            items = menu["items"]

            # Customer plates through the day; only eat-in meals reach the bin.
            for _ in range(rng.randint(6, 10) if weekend else rng.randint(12, 20)):
                item = rng.choice(items)
                weight = round(rng.uniform(0.04, 0.25), 3)
                split = recipe_split(menu, item["name"])
                # People leave the starch more than the protein.
                skewed = [(n, s * (1.8 if i == 0 else rng.uniform(0.3, 1.0))) for i, (n, s) in enumerate(split)]
                total = sum(s for _, s in skewed)
                t = datetime.combine(day, time(11, 0)) + timedelta(minutes=rng.randint(0, 540))
                drop = Drop(bin_id=bin_id, stall_id=sid, source="plate", weight_kg=weight, waste_kg=weight,
                            dish=item["name"], confidence=round(rng.uniform(0.8, 0.97), 2),
                            classified_by="seed", created_at=t)
                day_drops[bin_id].append((drop, [(n, s / total) for n, s in skewed]))

            # At closing the vendor empties each leftover tray: one weigh-in per ingredient.
            for ing, base in overcook[sid].items():
                kg = round(max(0.0, base * (1.3 if weekend else 1.0) * rng.gauss(1, 0.25)), 3)
                if kg < 0.05:
                    continue
                dish = next((i["name"] for i in items if any(l["ingredient"] == ing for l in i["recipe"])), items[0]["name"])
                t = datetime.combine(day, time(20, 30)) + timedelta(minutes=rng.randint(0, 25))
                drop = Drop(bin_id=bin_id, stall_id=sid, source="vendor", weight_kg=kg, waste_kg=kg, dish=dish,
                            confidence=0.95, classified_by="seed", created_at=t)
                day_drops[bin_id].append((drop, [(ing, 1.0)]))

        # Staff empty each bin into compost after closing.
        for bin_id, entries in day_drops.items():
            if not entries:
                continue
            transfer = CompostTransfer(
                bin_id=bin_id, weight_kg=round(sum(d.weight_kg for d, _ in entries), 3),
                created_at=datetime.combine(day, time(21, 15)), is_demo=True,
            )
            session.add(transfer)
            session.flush()
            for drop, split in entries:
                drop.transfer_id = transfer.id
                session.add(drop)
                session.flush()
                for name, share in split:
                    session.add(DropIngredient(drop_id=drop.id, ingredient=name, share=round(share, 4),
                                               waste_kg=round(drop.waste_kg * share, 4)))
    session.commit()


def backfill_drop_ingredients(session: Session) -> int:
    """Weigh-ins saved before ingredient splits existed: split them by their dish's recipe."""
    from .menu import get_menu

    missing = session.exec(
        select(Drop).where(
            col(Drop.waste_kg) > 0,
            ~col(Drop.id).in_(select(DropIngredient.drop_id)),
        )
    ).all()
    menus: dict[str, dict] = {}
    for d in missing:
        menu = menus.setdefault(d.stall_id, get_menu(session, d.stall_id))
        for name, share in recipe_split(menu, d.dish):
            session.add(DropIngredient(drop_id=d.id, ingredient=name, share=round(share, 4), waste_kg=round(d.waste_kg * share, 4)))
    session.commit()
    return len(missing)
