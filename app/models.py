from datetime import date
from typing import Optional

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from .config import now


class Location(SQLModel, table=True):
    id: str = Field(primary_key=True)  # e.g. "NS"
    name: str


class Bin(SQLModel, table=True):
    id: str = Field(primary_key=True)  # e.g. "NS-01"
    location_id: str = Field(foreign_key="location.id")
    capacity_kg: float = 40.0


class Stall(SQLModel, table=True):
    id: str = Field(primary_key=True)
    location_id: str = Field(foreign_key="location.id")
    name: str
    portion_g: int
    cost_per_portion: float  # S$ ingredient cost
    menu: list[str] = Field(sa_column=Column(JSON, nullable=False))


class Drop(SQLModel, table=True):
    """One item of food placed on the bin's scale."""

    id: Optional[int] = Field(default=None, primary_key=True)
    bin_id: str = Field(foreign_key="bin.id", index=True)
    stall_id: str = Field(foreign_key="stall.id", index=True)
    source: str  # "plate" (customer) or "vendor" (end-of-day unsold)
    weight_kg: float
    dish: Optional[str] = None
    confidence: Optional[float] = None
    classified_by: str = "none"  # "openai", "device", "seed", "none"
    # False when the camera saw nothing edible (empty plate, bones, broth). The weight still
    # sits in the bin, but it is left out of food-waste figures.
    is_waste: bool = True
    waste_note: Optional[str] = None
    image_file: Optional[str] = None
    created_at: NaiveDatetime = Field(default_factory=now, index=True)
    transfer_id: Optional[int] = Field(default=None, foreign_key="composttransfer.id", index=True)


class PrepLog(SQLModel, table=True):
    """Portions a vendor cooked on a given day."""

    __table_args__ = (UniqueConstraint("stall_id", "day"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    stall_id: str = Field(foreign_key="stall.id", index=True)
    day: date
    portions: int


class CompostTransfer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bin_id: str = Field(foreign_key="bin.id", index=True)
    weight_kg: float
    created_at: NaiveDatetime = Field(default_factory=now)
