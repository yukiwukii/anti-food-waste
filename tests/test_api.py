def drop(client, bin_id="NS-01", **fields):
    data = {"stall_id": "cr", "source": "plate", "weight_kg": "0.150", **fields}
    return client.post(f"/api/bins/{bin_id}/drops", data=data)


def test_locations_have_bins_and_stalls(client):
    locs = {l["id"]: l for l in client.get("/api/locations").json()}
    assert set(locs) == {"NS", "SS"}
    assert [b["id"] for b in locs["NS"]["bins"]] == ["NS-01"]
    assert "Chicken Rice" in [s["name"] for s in locs["NS"]["stalls"]]


def test_drop_adds_to_bin_load_and_transfer_empties_it(client):
    before = client.get("/api/bins/NS-01").json()["load_kg"]
    r = drop(client, dish="Roasted chicken rice")
    assert r.status_code == 201
    body = r.json()
    assert body["drop"]["dish"] == "Roasted chicken rice"
    assert body["drop"]["classified_by"] == "device"
    assert abs(body["bin_load_kg"] - (before + 0.15)) < 1e-6

    t = client.post("/api/bins/NS-01/transfers")
    assert t.status_code == 201
    assert client.get("/api/bins/NS-01").json()["load_kg"] == 0
    assert client.post("/api/bins/NS-01/transfers").status_code == 409


def test_drop_rejects_stall_from_other_location(client):
    r = drop(client, bin_id="SS-01", stall_id="cr")
    assert r.status_code == 422


def test_drop_rejects_dish_not_on_menu(client):
    assert drop(client, dish="Pizza").status_code == 422


def test_drop_rejects_bad_weight(client):
    assert drop(client, weight_kg="0").status_code == 422
    assert drop(client, weight_kg="30").status_code == 422


def test_full_bin_is_refused(client):
    for _ in range(8):
        assert drop(client, source="vendor", weight_kg="5").status_code == 201
    r = drop(client, source="vendor", weight_kg="5")
    assert r.status_code == 409
    client.post("/api/bins/NS-01/transfers")


def test_photo_without_classifier_is_stored(client):
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = client.post(
        "/api/bins/NS-01/drops",
        data={"stall_id": "cr", "source": "plate", "weight_kg": "0.1"},
        files={"image": ("plate.png", png, "image/png")},
    )
    assert r.status_code == 201
    d = r.json()["drop"]
    assert d["classified_by"] == "none"
    assert client.get(d["image_url"]).content == png
    client.post("/api/bins/NS-01/transfers")




def test_compost_summary_counts_seeded_transfers(client):
    c = client.get("/api/compost").json()
    assert c["transfers"] >= 28  # 14 days x 2 bins
    assert c["diverted_kg"] > 0


def fake_classify(**kw):
    from app.classifier import Classification

    return lambda *a, **k: Classification(**kw)


def test_insights_from_seeded_history(client):
    data = client.get("/api/stalls/cr/insights").json()
    assert len(data["days"]) == 15  # 14 demo days + today
    assert all(d["demo"] for d in data["days"][:-1])
    assert data["days"][-1]["partial"]
    assert data["menu_is_example"]
    assert data["ingredient_order"][:2] == ["White rice", "Roast chicken"]
    assert data["cook_less"] and data["cook_less"][0]["cut_raw_kg"] > 0
    assert data["serve_less"] and data["serve_less"][0]["ingredient"] == "White rice"
    assert data["totals"]["sgd_per_month"] > 0


def test_device_label_splits_by_recipe(client):
    r = client.post("/api/bins/NS-01/drops", data={"stall_id": "cr", "source": "vendor", "weight_kg": "3.9", "dish": "Roasted chicken rice"})
    parts = {p["ingredient"]: p["waste_kg"] for p in r.json()["drop"]["ingredients"]}
    assert parts == {"White rice": 2.5, "Roast chicken": 1.1, "Cucumber": 0.3}  # 250:110:30
    today = client.get("/api/stalls/cr/insights").json()["today"]
    assert today["unsold"]["White rice"] >= 2.5
    client.post("/api/bins/NS-01/transfers")


def test_photo_split_feeds_today_by_ingredient(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "classify", fake_classify(
        dish="Chicken katsu don", confidence=0.9, classified_by="openai", is_waste=True, edible_fraction=0.5,
        ingredients=[("Japanese rice", 1.0)], waste_note="A tray of rice.", reasoning="Only rice.",
        prompt="PROMPT", raw_output="{}", model="gpt-test",
    ))
    before = client.get("/api/stalls/jp/insights").json()["today"]["unsold"].get("Japanese rice", 0)
    r = client.post("/api/bins/SS-01/drops", data={"stall_id": "jp", "source": "vendor", "weight_kg": "4.0"},
                    files={"image": ("tray.png", b"\x89PNG fake", "image/png")})
    d = r.json()["drop"]
    assert d["waste_kg"] == 2.0 and d["ingredients"] == [{"ingredient": "Japanese rice", "share": 1.0, "waste_kg": 2.0}]
    after = client.get("/api/stalls/jp/insights").json()["today"]["unsold"]["Japanese rice"]
    assert round(after - before, 3) == 2.0
    detail = client.get(f"/api/drops/{d['id']}").json()
    assert detail["model_reasoning"] == "Only rice." and detail["ingredients"][0]["ingredient"] == "Japanese rice"
    client.post("/api/bins/SS-01/transfers")


def test_not_waste_adds_no_ingredients(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "classify", fake_classify(
        dish="Ramen", confidence=0.8, classified_by="openai", is_waste=False, edible_fraction=0.0, waste_note="Only broth.",
    ))
    r = client.post("/api/bins/SS-01/drops", data={"stall_id": "jp", "source": "vendor", "weight_kg": "2.0"},
                    files={"image": ("bowl.png", b"\x89PNG fake", "image/png")})
    assert r.json()["drop"]["ingredients"] == []
    client.post("/api/bins/SS-01/transfers")


def test_menu_round_trip_and_validation(client):
    menu = client.get("/api/stalls/bm/menu").json()
    assert menu["is_example"] and menu["items"][0]["name"] == "Ban mian soup"
    menu["items"].append({"name": "Fishball noodles", "recipe": [{"ingredient": "Ban mian noodles", "grams": 200}]})
    saved = client.put("/api/stalls/bm/menu", json={"ingredients": menu["ingredients"], "items": menu["items"]}).json()
    assert not saved["is_example"] and saved["items"][-1]["name"] == "Fishball noodles"
    stall = next(s for l in client.get("/api/locations").json() for s in l["stalls"] if s["id"] == "bm")
    assert "Fishball noodles" in stall["menu"]
    bad = {"ingredients": menu["ingredients"], "items": [{"name": "X", "recipe": [{"ingredient": "Caviar", "grams": 10}]}]}
    assert client.put("/api/stalls/bm/menu", json=bad).status_code == 422


def test_menu_scan_returns_draft_without_saving(client, monkeypatch):
    from app import main

    draft = {"notes": "", "ingredients": [{"name": "Rice", "cooked_per_raw": 2.5, "cost_per_raw_kg": 2}],
             "items": [{"name": "Plain rice", "recipe": [{"ingredient": "Rice", "grams": 250}]}], "model": "gpt-test"}
    monkeypatch.setattr(main, "scan_menu", lambda data, media_type: draft)
    r = client.post("/api/stalls/ml/menu/scan", files={"image": ("menu.jpg", b"jpeg", "image/jpeg")})
    assert r.json()["items"][0]["name"] == "Plain rice"
    assert client.get("/api/stalls/ml/menu").json()["items"][0]["name"] == "Mala xiang guo"


def test_demo_reset_keeps_real_data(client):
    r = client.post("/api/bins/SS-01/drops", data={"stall_id": "bm", "source": "plate", "weight_kg": "0.2"})
    real_id = r.json()["drop"]["id"]
    assert client.post("/api/demo/reset").status_code == 200
    assert len(client.get("/api/stalls/bm/insights").json()["days"]) == 15
    assert client.get(f"/api/drops/{real_id}").status_code == 200
    client.post("/api/bins/SS-01/transfers")
