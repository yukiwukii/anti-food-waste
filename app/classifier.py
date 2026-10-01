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


def _classify_with_openai(image: bytes, media_type: str, menu: list[str]) -> Classification:
    labels = menu + [OTHER]
    schema = {
        "type": "object",
        "properties": {
            "dish": {"type": "string", "enum": labels},
            "confidence": {"type": "number"},
        },
        "required": ["dish", "confidence"],
        "additionalProperties": False,
    }
    prompt = (
        "This photo is from a camera mounted above a food-waste bin at a university food court. "
        "Identify which dish the leftover food comes from. "
        f"Choose exactly one label from this stall's menu: {', '.join(menu)}. "
        f'Use "{OTHER}" if the food does not match any of them or the photo shows no food. '
        "Set confidence between 0 and 1."
    )
    data_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
    response = _get_client().responses.create(
        model=config.VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url, "detail": "low"},
                ],
            }
        ],
        text={"format": {"type": "json_schema", "name": "dish_label", "schema": schema, "strict": True}},
    )
    data = json.loads(response.output_text)
    dish = data["dish"] if data["dish"] in labels else OTHER
    confidence = max(0.0, min(1.0, float(data["confidence"])))
    return Classification(dish=dish, confidence=round(confidence, 2), classified_by="openai")
