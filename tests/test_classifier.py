import json
from types import SimpleNamespace

from app import classifier, config

MENU1 = {"ingredients": [{"name": "White rice"}, {"name": "Roast chicken"}],
         "items": [{"name": "Roasted chicken rice", "recipe": [{"ingredient": "White rice", "grams": 250}, {"ingredient": "Roast chicken", "grams": 110}]}]}
MENU2 = {"ingredients": [{"name": "Briyani rice"}, {"name": "Prata"}, {"name": "Dal curry"}],
         "items": [{"name": "Briyani", "recipe": [{"ingredient": "Briyani rice", "grams": 300}]},
                   {"name": "Prata", "recipe": [{"ingredient": "Prata", "grams": 160}, {"ingredient": "Dal curry", "grams": 120}]}]}


class FakeResponses:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(self.payload))


def use_fake(monkeypatch, payload):
    fake = FakeResponses(payload)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(config, "CLASSIFIER", "auto")
    monkeypatch.setattr(classifier, "_get_client", lambda: SimpleNamespace(responses=fake))
    return fake


def test_photo_is_sent_to_openai_with_menu_labels(monkeypatch):
    fake = use_fake(monkeypatch, {"reasoning": "One half prata, all edible.", "observation": "Half a prata.", "is_food_waste": True, "edible_fraction": 1.0, "dish": "Prata", "confidence": 0.91, "ingredients": [{"name": "Prata", "share": 3}, {"name": "other", "share": 1}]})
    result = classifier.classify(b"jpeg-bytes", "image/jpeg", MENU2, device_label="Briyani")
    assert (result.dish, result.confidence, result.classified_by) == ("Prata", 0.91, "openai")
    assert result.is_waste
    assert result.reasoning == "One half prata, all edible."
    assert json.loads(result.raw_output)["dish"] == "Prata"
    assert "edible_fraction" in result.prompt
    call = fake.calls[0]
    image = call["input"][0]["content"][1]
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    props = call["text"]["format"]["schema"]["properties"]
    assert props["dish"]["enum"] == ["Briyani", "Prata", "other"]
    assert props["ingredients"]["items"]["properties"]["name"]["enum"] == ["Briyani rice", "Prata", "Dal curry", "other"]
    assert result.ingredients == [("Prata", 0.75), ("Unidentified", 0.25)]


def test_bones_only_is_not_waste(monkeypatch):
    use_fake(monkeypatch, {"reasoning": "Bones only.", "observation": "Only chicken bones.", "is_food_waste": False, "edible_fraction": 0.4, "dish": "Roasted chicken rice", "confidence": 0.7, "ingredients": []})
    result = classifier.classify(b"x", "image/jpeg", MENU1)
    assert not result.is_waste
    assert result.waste_note == "Only chicken bones."
    assert result.edible_fraction == 0.0  # "not waste" wins over a stray fraction


def test_mixed_plate_keeps_edible_fraction(monkeypatch):
    use_fake(monkeypatch, {"reasoning": "Rice ~60%, bones ~40%.", "observation": "Rice with chicken bones.", "is_food_waste": True, "edible_fraction": 0.6, "dish": "Roasted chicken rice", "confidence": 0.8, "ingredients": []})
    result = classifier.classify(b"x", "image/jpeg", MENU1)
    assert result.is_waste and result.edible_fraction == 0.6
    assert result.ingredients == [("White rice", 250 / 360), ("Roast chicken", 110 / 360)]  # no split given: recipe


def test_openai_failure_falls_back_to_device_label(monkeypatch):
    use_fake(monkeypatch, {"dish": "Prata", "confidence": 0.9})

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(classifier, "_get_client", boom)
    result = classifier.classify(b"x", "image/jpeg", MENU2, device_label="Prata")
    assert result.classified_by == "device"
    assert "network down" in result.error
    assert result.ingredients == [("Prata", 160 / 280), ("Dal curry", 120 / 280)]
    assert result.is_waste  # unknown counts as waste


def test_no_api_key_skips_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = classifier.classify(b"x", "image/jpeg", MENU2)
    assert (result.dish, result.classified_by) == (None, "none")
