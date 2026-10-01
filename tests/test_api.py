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


def test_insights_from_seeded_history(client):
    data = client.get("/api/stalls/cr/insights").json()
    assert len(data["history"]) == 14
    s = data["suggestion"]
    assert s["suggested_prep"] < s["avg_prepared"]
    assert s["portions_saved_per_day"] > 0


def test_prep_upsert_shows_in_today(client):
    today = client.get("/api/health").json()["today"]
    assert client.put("/api/stalls/mv/prep", json={"day": today, "portions": 200}).status_code == 200
    assert client.put("/api/stalls/mv/prep", json={"day": today, "portions": 230}).status_code == 200
    assert client.get("/api/stalls/mv/insights").json()["today"]["prepared"] == 230


def test_compost_summary_counts_seeded_transfers(client):
    c = client.get("/api/compost").json()
    assert c["transfers"] >= 28  # 14 days x 2 bins
    assert c["diverted_kg"] > 0


def test_not_waste_drop_is_left_out_of_insights(client, monkeypatch):
    from app import main
    from app.classifier import Classification

    monkeypatch.setattr(
        main, "classify",
        lambda *a, **k: Classification("Ramen", 0.8, "openai", is_waste=False, waste_note="Only broth."),
    )
    before = client.get("/api/stalls/jp/insights").json()["today"]
    r = client.post(
        "/api/bins/SS-01/drops",
        data={"stall_id": "jp", "source": "vendor", "weight_kg": "2.0"},
        files={"image": ("bowl.png", b"\x89PNG fake", "image/png")},
    )
    assert r.status_code == 201
    assert r.json()["drop"]["is_waste"] is False
    after = client.get("/api/stalls/jp/insights").json()["today"]
    assert after["unsold_kg"] == before["unsold_kg"]
    assert after["not_waste_drops"] == before["not_waste_drops"] + 1
    # The broth is still physically in the bin.
    assert client.get("/api/bins/SS-01").json()["load_kg"] >= 2.0
    client.post("/api/bins/SS-01/transfers")
