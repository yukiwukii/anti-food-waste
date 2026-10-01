"""Identify the dish in a bin camera photo with Claude vision.

The bin always has a fallback: if there is no photo, Claude is switched off, or the call fails,
we keep whatever label the device sent (or none). A failed classification never blocks a weigh-in.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from . import config

log = logging.getLogger(__name__)

OTHER = "other"

_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=1, timeout=30.0)
    return _client


def claude_credentials_found() -> bool:
    """Best-effort check so the UI can say whether photo recognition will work."""
    if any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
        return True
    return (Path.home() / ".config" / "anthropic").is_dir()


@dataclass
class Classification:
    dish: Optional[str]
    confidence: Optional[float]
    classified_by: str


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
    if not image or config.CLASSIFIER == "off":
        return fallback
    try:
        return _classify_with_claude(image, media_type or "image/jpeg", menu)
    except Exception as exc:  # network, auth, refusal, bad JSON: keep the weigh-in, lose the label
        log.warning("Claude classification failed, using device label: %s", exc)
        return fallback


def _classify_with_claude(image: bytes, media_type: str, menu: list[str]) -> Classification:
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
    response = _get_client().beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to classify the image")
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    dish = data["dish"] if data["dish"] in labels else OTHER
    confidence = max(0.0, min(1.0, float(data["confidence"])))
    return Classification(dish=dish, confidence=round(confidence, 2), classified_by="claude")
