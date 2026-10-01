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
    edible_fraction: float = 1.0  # model's estimate of the share of weight that is edible food
    waste_kg: Optional[float] = None  # weight_kg x edible_fraction; this is what counts as food waste
    waste_note: Optional[str] = None
    # What the vision model was asked and said, so it can be shown on the page.
    model: Optional[str] = None
    model_prompt: Optional[str] = None
    model_reasoning: Optional[str] = None
    model_output: Optional[str] = None
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
    is_demo: bool = False  # generated demo history, removed by a demo reset


class CompostTransfer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    bin_id: str = Field(foreign_key="bin.id", index=True)
    weight_kg: float
    created_at: NaiveDatetime = Field(default_factory=now)
    is_demo: bool = False


class StallIngredient(SQLModel, table=True):
    """An ingredient a stall cooks with. Weights in the bin are cooked weights."""

    __table_args__ = (UniqueConstraint("stall_id", "name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    stall_id: str = Field(foreign_key="stall.id", index=True)
    name: str
    cooked_per_raw: float = 1.0  # cooked weight / raw weight, e.g. rice ~2.5, chicken ~0.75
    cost_per_raw_kg: float = 0.0  # S$
    is_example: bool = False


class MenuItem(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("stall_id", "name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    stall_id: str = Field(foreign_key="stall.id", index=True)
    name: str
    is_example: bool = False


class RecipeLine(SQLModel, table=True):
    """Cooked grams of one ingredient in one portion of a menu item."""

    id: Optional[int] = Field(default=None, primary_key=True)
    menu_item_id: int = Field(foreign_key="menuitem.id", index=True)
    ingredient_id: int = Field(foreign_key="stallingredient.id", index=True)
    grams: float


class DropIngredient(SQLModel, table=True):
    """How a weigh-in's counted food waste splits across ingredients.

    The ingredient name is copied, not linked, so editing a menu never rewrites history.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    drop_id: int = Field(foreign_key="drop.id", index=True)
    ingredient: str
    share: float
    waste_kg: float
