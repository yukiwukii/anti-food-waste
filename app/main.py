import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, col, select

from . import config
from .classifier import classify, vision_ready
from .db import engine, get_session, init_db
from .insights import build_day, suggest
from .models import Bin, CompostTransfer, Drop, Location, PrepLog, Stall
from .seed import ensure_reference_data, refresh_demo_history, reset_demo_history

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with Session(engine) as session:
        ensure_reference_data(session)
        if config.SEED_DEMO:
            refresh_demo_history(session)
    yield


app = FastAPI(title="Leftover Scale", version="0.1.0", lifespan=lifespan)
SessionDep = Annotated[Session, Depends(get_session)]


# ---------- helpers ----------

def _get_or_404(session: Session, model, key):
    obj = session.get(model, key)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} '{key}' not found")
    return obj


def _bin_load(session: Session, bin_id: str) -> float:
    total = session.exec(
        select(func.coalesce(func.sum(Drop.weight_kg), 0.0)).where(Drop.bin_id == bin_id, col(Drop.transfer_id).is_(None))
    ).one()
    return round(float(total), 3)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


DETAIL_FIELDS = {"model_prompt", "model_reasoning", "model_output"}


def _drop_out(d: Drop, detail: bool = False) -> dict:
    out = d.model_dump(exclude={"image_file"} if detail else {"image_file"} | DETAIL_FIELDS)
    out["image_url"] = f"/api/drops/{d.id}/image" if d.image_file else None
    return out


# ---------- reference data ----------

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "today": config.now().date(),
        "classifier": config.CLASSIFIER,
        "vision_ready": vision_ready(),
        "model": config.VISION_MODEL,
    }


@app.get("/api/locations")
def list_locations(session: SessionDep):
    locations = session.exec(select(Location)).all()
    bins = session.exec(select(Bin)).all()
    stalls = session.exec(select(Stall)).all()
    return [
        {
            **loc.model_dump(),
            "bins": [b.model_dump() for b in bins if b.location_id == loc.id],
            "stalls": [s.model_dump() for s in stalls if s.location_id == loc.id],
        }
        for loc in locations
    ]


@app.get("/api/stalls")
def list_stalls(session: SessionDep):
    return session.exec(select(Stall)).all()


# ---------- bins and drops ----------

@app.get("/api/bins/{bin_id}")
def get_bin(bin_id: str, session: SessionDep):
    b = _get_or_404(session, Bin, bin_id)
    load = _bin_load(session, bin_id)
    return {**b.model_dump(), "load_kg": load, "fill_pct": round(load / b.capacity_kg * 100, 1)}


@app.post("/api/bins/{bin_id}/drops", status_code=201)
async def create_drop(
    bin_id: str,
    session: SessionDep,
    stall_id: Annotated[str, Form()],
    source: Annotated[Literal["plate", "vendor"], Form()],
    weight_kg: Annotated[float, Form(gt=0, le=25)],
    dish: Annotated[Optional[str], Form(description="Label from the bin's on-device model, if any")] = None,
    image: Annotated[Optional[UploadFile], File(description="Camera photo of the food")] = None,
):
    """Called by the bin each time the scale settles on a new item."""
    b = _get_or_404(session, Bin, bin_id)
    stall = _get_or_404(session, Stall, stall_id)
    if stall.location_id != b.location_id:
        raise HTTPException(422, f"Stall '{stall.name}' is not served by bin {bin_id}")
    if dish is not None and dish not in stall.menu:
        raise HTTPException(422, f"'{dish}' is not on the {stall.name} menu")
    load = _bin_load(session, bin_id)
    if load + weight_kg > b.capacity_kg:
        raise HTTPException(409, f"Bin {bin_id} is full ({load:.1f} of {b.capacity_kg:.0f} kg). Transfer it to compost first.")

    image_bytes = None
    media_type = None
    image_file = None
    if image is not None and image.filename:
        media_type = image.content_type
        if media_type not in IMAGE_TYPES:
            raise HTTPException(415, "Photo must be JPEG, PNG, WebP or GIF")
        image_bytes = await image.read()
        if len(image_bytes) > config.MAX_IMAGE_BYTES:
            raise HTTPException(413, "Photo is larger than 5 MB")
        image_file = f"{uuid.uuid4().hex}.{media_type.split('/')[1]}"
        (config.IMAGE_DIR / image_file).write_bytes(image_bytes)

    result = classify(image_bytes, media_type, stall.menu, device_label=dish)
    drop = Drop(
        bin_id=bin_id,
        stall_id=stall_id,
        source=source,
        weight_kg=round(weight_kg, 3),
        dish=result.dish,
        confidence=result.confidence,
        classified_by=result.classified_by,
        is_waste=result.is_waste,
        edible_fraction=result.edible_fraction,
        waste_kg=round(weight_kg * result.edible_fraction, 3) if result.is_waste else 0.0,
        waste_note=result.waste_note,
        model=result.model,
        model_prompt=result.prompt,
        model_reasoning=result.reasoning,
        model_output=result.raw_output,
        image_file=image_file,
    )
    session.add(drop)
    session.commit()
    session.refresh(drop)
    return {
        "drop": _drop_out(drop),
        "bin_load_kg": round(load + drop.weight_kg, 3),
        "recognition_error": result.error,
    }


@app.get("/api/drops")
def list_drops(
    session: SessionDep,
    day: Optional[date] = None,
    bin_id: Optional[str] = None,
    stall_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    q = select(Drop).order_by(col(Drop.created_at).desc(), col(Drop.id).desc()).limit(limit)
    if day:
        start, end = _day_bounds(day)
        q = q.where(Drop.created_at >= start, Drop.created_at < end)
    if bin_id:
        q = q.where(Drop.bin_id == bin_id)
    if stall_id:
        q = q.where(Drop.stall_id == stall_id)
    return [_drop_out(d) for d in session.exec(q).all()]


@app.get("/api/drops/{drop_id}")
def get_drop(drop_id: int, session: SessionDep):
    """One weigh-in, including the prompt sent to the vision model and its full answer."""
    d = _get_or_404(session, Drop, drop_id)
    out = _drop_out(d, detail=True)
    out["stall_name"] = session.get(Stall, d.stall_id).name
    return out


@app.get("/api/drops/{drop_id}/image")
def drop_image(drop_id: int, session: SessionDep):
    d = _get_or_404(session, Drop, drop_id)
    if not d.image_file:
        raise HTTPException(404, "This drop has no photo")
    return FileResponse(config.IMAGE_DIR / d.image_file)


# ---------- compost ----------

@app.post("/api/bins/{bin_id}/transfers", status_code=201)
def transfer_to_compost(bin_id: str, session: SessionDep):
    _get_or_404(session, Bin, bin_id)
    pending = session.exec(select(Drop).where(Drop.bin_id == bin_id, col(Drop.transfer_id).is_(None))).all()
    if not pending:
        raise HTTPException(409, f"Bin {bin_id} is empty")
    transfer = CompostTransfer(bin_id=bin_id, weight_kg=round(sum(d.weight_kg for d in pending), 3))
    session.add(transfer)
    session.flush()
    for d in pending:
        d.transfer_id = transfer.id
        session.add(d)
    session.commit()
    session.refresh(transfer)
    return transfer


@app.get("/api/compost")
def compost_summary(session: SessionDep):
    total, count = session.exec(
        select(func.coalesce(func.sum(CompostTransfer.weight_kg), 0.0), func.count(CompostTransfer.id))
    ).one()
    recent = session.exec(select(CompostTransfer).order_by(col(CompostTransfer.created_at).desc()).limit(10)).all()
    bins = [get_bin(b.id, session) for b in session.exec(select(Bin)).all()]
    return {
        "diverted_kg": round(float(total), 1),
        # Composting loses most of its mass as water and CO2; ~30% of input is a common rule of thumb.
        "compost_out_kg": round(float(total) * 0.3, 1),
        "transfers": count,
        "recent": recent,
        "bins": bins,
    }


# ---------- vendor prep and insights ----------

class PrepIn(BaseModel):
    day: date
    portions: int = Field(ge=0, le=5000)


@app.put("/api/stalls/{stall_id}/prep")
def set_prep(stall_id: str, body: PrepIn, session: SessionDep):
    """Vendor records how many portions they cooked that day."""
    _get_or_404(session, Stall, stall_id)
    row = session.exec(select(PrepLog).where(PrepLog.stall_id == stall_id, PrepLog.day == body.day)).first()
    if row is None:
        row = PrepLog(stall_id=stall_id, day=body.day, portions=body.portions)
    else:
        row.portions = body.portions
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@app.get("/api/stalls/{stall_id}/insights")
def stall_insights(stall_id: str, session: SessionDep, days: int = Query(14, ge=3, le=90)):
    stall = _get_or_404(session, Stall, stall_id)
    today = config.now().date()
    start = today - timedelta(days=days)
    preps = {
        p.day: p.portions
        for p in session.exec(select(PrepLog).where(PrepLog.stall_id == stall_id, PrepLog.day >= start, PrepLog.day <= today))
    }
    drops = session.exec(
        select(Drop).where(Drop.stall_id == stall_id, Drop.created_at >= datetime.combine(start, time.min))
    ).all()
    unsold_kg: dict[date, float] = {}
    plate_kg: dict[date, float] = {}
    for d in drops:
        # Only the edible share counts; bones, broth and empty plates add weight but no food waste.
        counted = d.waste_kg if d.waste_kg is not None else (d.weight_kg if d.is_waste else 0.0)
        bucket = unsold_kg if d.source == "vendor" else plate_kg
        bucket[d.created_at.date()] = bucket.get(d.created_at.date(), 0.0) + counted

    history = [
        build_day(day, preps[day], unsold_kg.get(day, 0.0), plate_kg.get(day, 0.0), stall.portion_g)
        for day in sorted(preps)
        if day < today
    ]
    # Today is still open, so it is charted but left out of the suggestion.
    today_row = build_day(
        today, preps.get(today), unsold_kg.get(today, 0.0), plate_kg.get(today, 0.0), stall.portion_g, partial=True
    )
    demo_days = {
        p.day for p in session.exec(select(PrepLog).where(PrepLog.stall_id == stall_id, col(PrepLog.is_demo)))
    }
    return {
        "stall": stall,
        "history": [{**asdict(r), "demo": r.day in demo_days} for r in history]
        + [{**asdict(today_row), "demo": False}],
        "suggestion": suggest(history, stall.portion_g, stall.cost_per_portion),
        "today": {
            "day": today,
            "prepared": preps.get(today),
            "plate_kg": round(plate_kg.get(today, 0.0), 3),
            "unsold_kg": round(unsold_kg.get(today, 0.0), 3),
            "unsold_portions": round(unsold_kg.get(today, 0.0) * 1000 / stall.portion_g),
            "drops": sum(1 for d in drops if d.created_at.date() == today),
            "not_waste_drops": sum(1 for d in drops if d.created_at.date() == today and not d.is_waste),
        },
    }


@app.post("/api/demo/reset")
def reset_demo(session: SessionDep):
    """Regenerate the demo history so it ends yesterday. Real weigh-ins and prep logs are kept."""
    reset_demo_history(session)
    return {"ok": True}


# ---------- frontend ----------

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
