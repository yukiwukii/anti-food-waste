# Leftover Scale

Smart food-waste bins for NTU's North Spine and South Spine food courts. Each bin has a weighing scale and a camera. Every item of food that goes in is weighed, photographed, and logged against the stall it came from. Vendors use the data to see their real daily demand and cook less surplus. The bin is then emptied into a compost bin.

## What it does

- **Bin API**: the bin posts each weigh-in (stall, customer plate or vendor end-of-day, weight, optional photo) to the server. The server stores it in SQLite and refuses weigh-ins when the bin is full.
- **Dish recognition**: if a photo is attached, Claude (`claude-opus-5-5`) picks the dish from that stall's menu. If there is no photo, no API key, or the call fails, the server keeps the label sent by the device and still saves the weigh-in.
- **Vendor insights**: vendors enter how many portions they cooked each day. Unsold food weighed at closing gives unsold portions, so portions sold = cooked − unsold. The suggested weekday prep is average sales plus half a standard deviation. The page also shows the daily and monthly savings.
- **Compost tracking**: staff record each time a bin is emptied into compost. The page shows the total food diverted from the trash.
- **Web dashboard** at `/`, with Live bin, Vendor insights, Compost, and Proposal tabs.

On first start the server adds 14 days of demo history (fixed random seed, marked `classified_by="seed"`), so the insights have data to show. Turn this off with `LEFTOVER_SEED_DEMO=0`.

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

To turn on photo recognition, set an Anthropic API key before starting the server:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

To show it on phones in the same Wi-Fi network, start with `--host 0.0.0.0` and open `http://<your-laptop-ip>:8000`. On a phone, the photo field opens the camera.

### Simulate a bin from the terminal

With the server running:

```bash
uv run python scripts/simulate_bin.py --bin NS-01 --count 20       # lunch-time customer plates
uv run python scripts/simulate_bin.py --bin SS-01 --closing        # vendors dump unsold food
uv run python scripts/simulate_bin.py --bin NS-01 --stall cr --photo plate.jpg
```

### Docker

```bash
docker build -t leftover-scale .
docker run -p 8000:8000 -v leftover-data:/data -e ANTHROPIC_API_KEY leftover-scale
```

### Tests

```bash
uv run pytest
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Server status, today's date, whether photo recognition is on |
| GET | `/api/locations` | Food courts with their bins and stalls |
| GET | `/api/bins/{bin_id}` | Current load and fill % |
| POST | `/api/bins/{bin_id}/drops` | Weigh-in (multipart form: `stall_id`, `source`, `weight_kg`, optional `dish`, optional `image`) |
| GET | `/api/drops` | Weigh-ins, filter by `day`, `bin_id`, `stall_id` |
| GET | `/api/drops/{id}/image` | Photo for a weigh-in |
| POST | `/api/bins/{bin_id}/transfers` | Empty the bin into compost |
| GET | `/api/compost` | Totals, bins, and recent transfers |
| PUT | `/api/stalls/{stall_id}/prep` | Portions cooked on a day (`{"day": "2026-10-01", "portions": 180}`) |
| GET | `/api/stalls/{stall_id}/insights` | Daily history, prep suggestion, and today's figures |

Interactive API docs: http://127.0.0.1:8000/docs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LEFTOVER_DATA_DIR` | `./data` | Database and photo storage |
| `LEFTOVER_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL |
| `LEFTOVER_CLASSIFIER` | `auto` | `auto` uses Claude when a photo is attached; `off` never calls Claude |
| `LEFTOVER_CLAUDE_MODEL` | `claude-opus-5-5` | Model for dish recognition |
| `LEFTOVER_SEED_DEMO` | `1` | Add 14 days of demo history to an empty database |

## Limitations

- Takeaway meals never reach the bin, so customer plate waste is only partly captured. The prep suggestion uses vendor end-of-day leftovers, which are captured in full.
- Vendors must enter portions cooked each day. Without that, the server cannot work out portions sold.
- There is no login. Run it on a trusted network.
