"""Identify the dish in a bin camera photo with the OpenAI vision API.

The bin always has a fallback: if there is no photo, recognition is switched off, or the call fails,
we keep whatever label the device sent (or none). A failed classification never blocks a weigh-in.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import openai
from openai import OpenAI

from . import config

log = logging.getLogger(__name__)

OTHER = "other"

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(max_retries=1, timeout=30.0)
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
    waste_note: Optional[str] = None  # the model's one-sentence observation
    reasoning: Optional[str] = None  # the model's step-by-step explanation
    prompt: Optional[str] = None
    raw_output: Optional[str] = None
    model: Optional[str] = None
    error: Optional[str] = None


def classify(
    image: Optional[bytes],
    media_type: Optional[str],
    menu: list[str],
    device_label: Optional[str] = None,
) -> Classification:
    fallback = Classification(
        dish=device_label,
        confidence=None,
        classified_by="device" if device_label else "none",
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
    return f"Dish recognition failed: {exc}"


def build_prompt(menu: list[str]) -> str:
    return (
        "This photo is from a camera mounted above a food-waste bin at a university food court. "
        "Everything in the photo is being weighed together on the bin's scale. "
        "Answer three questions about it.\n\n"
        "Only judge physical food you can actually see. Do not infer food from text, labels, signs or "
        "from the menu below. If the photo does not show real food or food scraps (for example it shows "
        "a screen, a document, a person, or an empty bin or plate), set is_food_waste to false, "
        f'edible_fraction to 0 and dish to "{OTHER}".\n\n'
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
        "3. Which dish does it come from? Choose exactly one label from this stall's menu: "
        f"{', '.join(menu)}. "
        f'Use "{OTHER}" if it does not match any of them or the photo shows no food.\n\n'
        "Write reasoning first: list each item you see, whether it is edible, and its rough share of "
        "the weight, then explain how you reached edible_fraction and the dish. "
        "In observation, summarise what you see in one short sentence. "
        "Set confidence between 0 and 1 for the dish label."
    )


def _classify_with_openai(image: bytes, media_type: str, menu: list[str]) -> Classification:
    labels = menu + [OTHER]
    schema = {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "observation": {"type": "string"},
            "is_food_waste": {"type": "boolean"},
            "edible_fraction": {"type": "number"},
            "dish": {"type": "string", "enum": labels},
            "confidence": {"type": "number"},
        },
        "required": ["reasoning", "observation", "is_food_waste", "edible_fraction", "dish", "confidence"],
        "additionalProperties": False,
    }
    prompt = build_prompt(menu)
    data_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
    response = _get_client().responses.create(
        model=config.VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        ],
        text={"format": {"type": "json_schema", "name": "bin_item", "schema": schema, "strict": True}},
    )
    raw = response.output_text
    data = json.loads(raw)
    is_waste = bool(data["is_food_waste"])
    fraction = _clamp(data["edible_fraction"]) if is_waste else 0.0
    if fraction == 0.0:
        is_waste = False
    dish = data["dish"] if data["dish"] in labels else OTHER
    return Classification(
        dish=dish,
        confidence=round(_clamp(data["confidence"]), 2),
        classified_by="openai",
        is_waste=is_waste,
        edible_fraction=round(fraction, 2),
        waste_note=str(data["observation"])[:300],
        reasoning=str(data["reasoning"]),
        prompt=prompt,
        raw_output=raw,
        model=getattr(response, "model", None) or config.VISION_MODEL,
    )


def _clamp(x) -> float:
    return max(0.0, min(1.0, float(x)))
