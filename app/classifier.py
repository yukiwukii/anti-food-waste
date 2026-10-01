"""OpenAI vision for the bin camera and for menu photos.

Bin photos: decide whether the item is food waste, estimate the edible share of its weight, name the
dish from the stall's menu, and split the edible weight across the stall's ingredients.

The bin always has a fallback: if there is no photo, recognition is switched off, or the call fails,
we keep whatever label the device sent and split by the recipe. A failed call never blocks a weigh-in.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import openai
from openai import OpenAI

from . import config
from .menu import UNIDENTIFIED, recipe_split

log = logging.getLogger(__name__)

OTHER = "other"

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(max_retries=1, timeout=60.0)
    return _client


def vision_ready() -> bool:
    """Whether photo recognition can run, so the UI can say so."""
    return config.CLASSIFIER != "off" and bool(os.environ.get("OPENAI_API_KEY"))


@dataclass
class Classification:
    dish: Optional[str]
    confidence: Optional[float]
    classified_by: str
    is_waste: bool = True  # unknown counts as waste, so data is never silently dropped
    edible_fraction: float = 1.0  # share of the weighed item that is edible food waste
    ingredients: list[tuple[str, float]] = field(default_factory=list)  # (ingredient, share of edible weight)
    waste_note: Optional[str] = None  # the model's one-sentence observation
    reasoning: Optional[str] = None  # the model's step-by-step explanation
    prompt: Optional[str] = None
    raw_output: Optional[str] = None
    model: Optional[str] = None
    error: Optional[str] = None


def classify(
    image: Optional[bytes],
    media_type: Optional[str],
    menu: dict,
    device_label: Optional[str] = None,
) -> Classification:
    fallback = Classification(
        dish=device_label,
        confidence=None,
        classified_by="device" if device_label else "none",
        ingredients=recipe_split(menu, device_label),
    )
    if not image or not vision_ready():
        return fallback
    try:
        return _classify_with_openai(image, media_type or "image/jpeg", menu)
    except Exception as exc:  # network, auth, bad JSON: keep the weigh-in, lose the label
        log.warning("OpenAI classification failed, using device label: %s", exc)
        fallback.error = _describe(exc)
        return fallback


def _describe(exc: Exception) -> str:
    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI rejected the API key. Check OPENAI_API_KEY and restart the server."
    if isinstance(exc, openai.PermissionDeniedError):
        return f"This OpenAI key cannot use {config.VISION_MODEL}. Set LEFTOVER_VISION_MODEL to a model your account can use."
    if isinstance(exc, openai.NotFoundError):
        return f"OpenAI model {config.VISION_MODEL} was not found. Set LEFTOVER_VISION_MODEL to a vision model your account can use."
    if isinstance(exc, openai.RateLimitError):
        return "OpenAI rate limit or quota reached. Check billing on your OpenAI account."
    if isinstance(exc, openai.APIConnectionError):
        return "Could not reach OpenAI. Check the internet connection."
    return f"Recognition failed: {exc}"


def _menu_text(menu: dict) -> str:
    return "\n".join(
        f"- {item['name']}: " + ", ".join(f"{l['ingredient']} {l['grams']:g} g" for l in item["recipe"])
        for item in menu["items"]
    )


def build_prompt(menu: dict) -> str:
    return (
        "This photo is from a camera mounted above a food-waste bin at a university food court. "
        "Everything in the photo is being weighed together on the bin's scale. "
        "Answer four questions about it.\n\n"
        "Only judge physical food you can actually see. Do not infer food from text, labels, signs or "
        "from the menu below. If the photo does not show real food or food scraps (for example it shows "
        "a screen, a document, a person, or an empty bin or plate), set is_food_waste to false, "
        f'edible_fraction to 0, dish to "{OTHER}" and ingredients to an empty list.\n\n'
        "This stall's menu, with the cooked grams of each ingredient in one portion:\n"
        f"{_menu_text(menu)}\n\n"
        "1. Is there food waste? Food waste means edible food left uneaten, such as rice, noodles, "
        "meat, fish, egg, tofu, vegetables or bread. It is NOT food waste if the photo shows only "
        "inedible or non-food items: an empty or scraped plate, bowl or container; bones, shells or "
        "seeds; leftover soup, broth, gravy or sauce with no solid food in it; sauce smears or a few "
        "stray grains of rice; napkins, cutlery or packaging. If any real portion of edible food is "
        "present, it is food waste.\n\n"
        "2. What fraction of the weight is edible food waste? Estimate edible_fraction between 0 and 1: "
        "the share of the total weight of the food items that is edible food, as opposed to bones, "
        "shells, seeds, broth, sauce and other inedible parts. Ignore the plate or bowl itself; the "
        "scale is tared for it. Judge by weight, not by area: bones and broth are heavy for their size, "
        "rice and vegetables are dense. Use 0 if there is no food waste and 1 if everything is edible.\n\n"
        "3. Which dish does it come from? Choose exactly one menu item name from the list above. "
        f'Use "{OTHER}" if it does not match any of them or the photo shows no food. A vendor\'s '
        "leftover tray may hold a single ingredient; then pick the menu item that uses it.\n\n"
        "4. Which ingredients make up the edible food waste? List each ingredient from the menu above "
        "that you can see, with its share of the edible weight. Shares must add up to 1. Judge from "
        "what is actually left over, not from the recipe: a plate with only rice left is all rice. "
        f'Use "{OTHER}" for edible food that matches none of the ingredients.\n\n'
        "Write reasoning first: list each item you see, whether it is edible, which ingredient it is, "
        "and its rough share of the weight, then explain how you reached edible_fraction, the dish and "
        "the ingredient shares. In observation, summarise what you see in one short sentence. "
        "Set confidence between 0 and 1 for the dish label."
    )


def _image_part(image: bytes, media_type: str) -> dict:
    data_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
    return {"type": "input_image", "image_url": data_url, "detail": "high"}


def _classify_with_openai(image: bytes, media_type: str, menu: dict) -> Classification:
    dishes = [i["name"] for i in menu["items"]] + [OTHER]
    ingredient_names = [i["name"] for i in menu["ingredients"]] + [OTHER]
    schema = {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "observation": {"type": "string"},
            "is_food_waste": {"type": "boolean"},
            "edible_fraction": {"type": "number"},
            "dish": {"type": "string", "enum": dishes},
            "confidence": {"type": "number"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": ingredient_names},
                        "share": {"type": "number"},
                    },
                    "required": ["name", "share"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reasoning", "observation", "is_food_waste", "edible_fraction", "dish", "confidence", "ingredients"],
        "additionalProperties": False,
    }
    prompt = build_prompt(menu)
    response = _get_client().responses.create(
        model=config.VISION_MODEL,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}, _image_part(image, media_type)]}],
        text={"format": {"type": "json_schema", "name": "bin_item", "schema": schema, "strict": True}},
    )
    raw = response.output_text
    data = json.loads(raw)
    is_waste = bool(data["is_food_waste"])
    fraction = _clamp(data["edible_fraction"]) if is_waste else 0.0
    if fraction == 0.0:
        is_waste = False
    dish = data["dish"] if data["dish"] in dishes else OTHER
    return Classification(
        dish=dish,
        confidence=round(_clamp(data["confidence"]), 2),
        classified_by="openai",
        is_waste=is_waste,
        edible_fraction=round(fraction, 2),
        ingredients=_normalise_split(data["ingredients"], menu, dish) if is_waste else [],
        waste_note=str(data["observation"])[:300],
        reasoning=str(data["reasoning"]),
        prompt=prompt,
        raw_output=raw,
        model=getattr(response, "model", None) or config.VISION_MODEL,
    )


def _normalise_split(parts: list[dict], menu: dict, dish: str) -> list[tuple[str, float]]:
    """Merge duplicates, map "other" to Unidentified, and rescale shares to add up to 1."""
    totals: dict[str, float] = {}
    for p in parts:
        name = UNIDENTIFIED if p["name"] == OTHER else p["name"]
        totals[name] = totals.get(name, 0.0) + max(0.0, float(p["share"]))
    total = sum(totals.values())
    if total <= 0:
        return recipe_split(menu, dish)
    return [(n, s / total) for n, s in totals.items() if s > 0]


def _clamp(x) -> float:
    return max(0.0, min(1.0, float(x)))


# ---------- menu photos ----------

MENU_PROMPT = (
    "This is a photo of a food stall's menu at a university food court in Singapore. "
    "Read every dish on the menu. For each dish, list its main ingredients with the cooked grams "
    "of each ingredient in one standard portion. Menus rarely show weights, so estimate typical "
    "Singapore hawker portions. Use one shared ingredient list for the whole stall: if two dishes use "
    "the same rice, name it the same way in both. Leave out soup, broth, gravy and sauces (the bin does not "
    "count liquids as food waste), and garnishes and condiments under 20 g.\n\n"
    "For each ingredient also estimate cooked_per_raw, the cooked weight divided by the raw weight "
    "(for example white rice about 2.5, dried noodles about 2, fresh noodles about 1.6, chicken about 0.75, "
    "leafy vegetables about 0.85, deep-fried items about 0.7), and cost_per_raw_kg, a typical Singapore "
    "wholesale price in S$ per raw kg.\n\n"
    "Only list dishes you can read on the menu. Do not invent dishes. If the photo is not a menu, return "
    "empty lists and say so in notes. Use notes for anything the vendor should check."
)

MENU_SCHEMA = {
    "type": "object",
    "properties": {
        "notes": {"type": "string"},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "cooked_per_raw": {"type": "number"},
                    "cost_per_raw_kg": {"type": "number"},
                },
                "required": ["name", "cooked_per_raw", "cost_per_raw_kg"],
                "additionalProperties": False,
            },
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "recipe": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"ingredient": {"type": "string"}, "grams": {"type": "number"}},
                            "required": ["ingredient", "grams"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "recipe"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["notes", "ingredients", "items"],
    "additionalProperties": False,
}


class MenuScanError(Exception):
    pass


def scan_menu(image: bytes, media_type: str) -> dict:
    """Read a menu photo into a draft menu. The vendor reviews it before it is saved."""
    if not vision_ready():
        raise MenuScanError("Menu reading needs an OpenAI API key. Add OPENAI_API_KEY to .env and restart the server.")
    try:
        response = _get_client().responses.create(
            model=config.VISION_MODEL,
            input=[{"role": "user", "content": [{"type": "input_text", "text": MENU_PROMPT}, _image_part(image, media_type)]}],
            text={"format": {"type": "json_schema", "name": "stall_menu", "schema": MENU_SCHEMA, "strict": True}},
        )
        draft = json.loads(response.output_text)
    except Exception as exc:
        log.warning("Menu scan failed: %s", exc)
        raise MenuScanError(_describe(exc)) from exc
    # Make sure every recipe ingredient is in the ingredient list, so the draft can be saved after review.
    known = {i["name"].strip().lower() for i in draft["ingredients"]}
    for item in draft["items"]:
        for line in item["recipe"]:
            if line["ingredient"].strip().lower() not in known:
                draft["ingredients"].append({"name": line["ingredient"].strip(), "cooked_per_raw": 1.0, "cost_per_raw_kg": 0.0})
                known.add(line["ingredient"].strip().lower())
    draft["model"] = getattr(response, "model", None) or config.VISION_MODEL
    return draft
