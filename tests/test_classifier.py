import json
from types import SimpleNamespace

from app import classifier, config


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
    fake = use_fake(monkeypatch, {"dish": "Prata", "confidence": 0.91})
    result = classifier.classify(b"jpeg-bytes", "image/jpeg", ["Briyani", "Prata"], device_label="Briyani")
    assert (result.dish, result.confidence, result.classified_by) == ("Prata", 0.91, "openai")
    call = fake.calls[0]
    image = call["input"][0]["content"][1]
    assert image["image_url"].startswith("data:image/jpeg;base64,")
    assert call["text"]["format"]["schema"]["properties"]["dish"]["enum"] == ["Briyani", "Prata", "other"]


def test_openai_failure_falls_back_to_device_label(monkeypatch):
    use_fake(monkeypatch, {"dish": "Prata", "confidence": 0.9})

    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(classifier, "_get_client", boom)
    result = classifier.classify(b"x", "image/jpeg", ["Prata"], device_label="Prata")
    assert result.classified_by == "device"
    assert "network down" in result.error


def test_no_api_key_skips_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = classifier.classify(b"x", "image/jpeg", ["Prata"])
    assert (result.dish, result.classified_by) == (None, "none")
