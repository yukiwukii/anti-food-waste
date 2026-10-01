"""Stall menus: ingredients, menu items, and recipes (cooked grams per portion)."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, col, delete, select

from .models import MenuItem, RecipeLine, Stall, StallIngredient

UNIDENTIFIED = "Unidentified"


class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    cooked_per_raw: float = Field(gt=0, le=10)
    cost_per_raw_kg: float = Field(ge=0, le=500)


class RecipeLineIn(BaseModel):
    ingredient: str = Field(min_length=1, max_length=60)
    grams: float = Field(gt=0, le=2000)


class MenuItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    recipe: list[RecipeLineIn] = Field(min_length=1)


class MenuIn(BaseModel):
    ingredients: list[IngredientIn] = Field(min_length=1)
    items: list[MenuItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self):
        self.ingredients = [i.model_copy(update={"name": i.name.strip()}) for i in self.ingredients]
        self.items = [i.model_copy(update={"name": i.name.strip()}) for i in self.items]
        names = [i.name.lower() for i in self.ingredients]
        if len(set(names)) != len(names):
            raise ValueError("Each ingredient name must be unique")
        items = [i.name.lower() for i in self.items]
        if len(set(items)) != len(items):
            raise ValueError("Each menu item name must be unique")
        for item in self.items:
            for line in item.recipe:
                if line.ingredient.strip().lower() not in names:
                    raise ValueError(f"'{item.name}' uses '{line.ingredient}', which is not in the ingredient list")
        return self


def get_menu(session: Session, stall_id: str) -> dict:
    ingredients = session.exec(
        select(StallIngredient).where(StallIngredient.stall_id == stall_id).order_by(col(StallIngredient.id))
    ).all()
    by_id = {i.id: i for i in ingredients}
    items = session.exec(select(MenuItem).where(MenuItem.stall_id == stall_id).order_by(col(MenuItem.id))).all()
    lines = session.exec(
        select(RecipeLine).where(col(RecipeLine.menu_item_id).in_([m.id for m in items])).order_by(col(RecipeLine.id))
    ).all() if items else []
    return {
        "is_example": any(i.is_example for i in ingredients) or any(m.is_example for m in items),
        "ingredients": [
            {"name": i.name, "cooked_per_raw": i.cooked_per_raw, "cost_per_raw_kg": i.cost_per_raw_kg}
            for i in ingredients
        ],
        "items": [
            {
                "name": m.name,
                "recipe": [{"ingredient": by_id[l.ingredient_id].name, "grams": l.grams} for l in lines if l.menu_item_id == m.id],
            }
            for m in items
        ],
    }


def replace_menu(session: Session, stall: Stall, menu: MenuIn, is_example: bool = False) -> None:
    """Replace a stall's whole menu. Past weigh-ins keep their own ingredient names."""
    old_items = [m.id for m in session.exec(select(MenuItem).where(MenuItem.stall_id == stall.id))]
    if old_items:
        session.exec(delete(RecipeLine).where(col(RecipeLine.menu_item_id).in_(old_items)))
    session.exec(delete(MenuItem).where(MenuItem.stall_id == stall.id))
    session.exec(delete(StallIngredient).where(StallIngredient.stall_id == stall.id))
    session.flush()

    ids: dict[str, int] = {}
    for ing in menu.ingredients:
        row = StallIngredient(
            stall_id=stall.id, name=ing.name, cooked_per_raw=ing.cooked_per_raw,
            cost_per_raw_kg=ing.cost_per_raw_kg, is_example=is_example,
        )
        session.add(row)
        session.flush()
        ids[ing.name.lower()] = row.id
    for item in menu.items:
        row = MenuItem(stall_id=stall.id, name=item.name, is_example=is_example)
        session.add(row)
        session.flush()
        for line in item.recipe:
            session.add(RecipeLine(menu_item_id=row.id, ingredient_id=ids[line.ingredient.strip().lower()], grams=line.grams))
    # Keep the plain list of dish names on the stall for the bin's dish picker and label checks.
    stall.menu = [i.name for i in menu.items]
    session.add(stall)
    session.commit()


def recipe_split(menu: dict, dish: Optional[str]) -> list[tuple[str, float]]:
    """Split by the recipe's cooked grams when the photo can't tell us. Unknown dish -> Unidentified."""
    item = next((i for i in menu["items"] if i["name"] == dish), None)
    if not item:
        return [(UNIDENTIFIED, 1.0)]
    total = sum(l["grams"] for l in item["recipe"])
    return [(l["ingredient"], l["grams"] / total) for l in item["recipe"]]
