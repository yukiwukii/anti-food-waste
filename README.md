# Leftover Scale

Smart food-waste bins for NTU's North Spine and South Spine food courts. Each bin has a weighing scale and a camera. Every item of food that goes in is weighed, photographed, and logged against the stall it came from. Vendors use the data to see their real daily demand and cook less surplus. The bin is then emptied into a compost bin.

## What it does

- **Bin API**: the bin posts each weigh-in (stall, customer plate or vendor end-of-day, weight, optional photo) to the server. The server stores it in SQLite and refuses weigh-ins when the bin is full.
- **Live bin camera**: the Live bin page streams from a webcam. Each weigh-in captures a frame, and OpenAI vision (`gpt-6-luna` by default) decides whether it is food waste, estimates the edible share of the weight (rice versus bones or broth), names the dish from the stall's menu, and splits the edible weight across the stall's ingredients. Select a row in the log to see the photo, the split, the model's reasoning, its raw output and the prompt. If there is no photo, no API key, or the call fails, the full weight counts and is split by the dish's recipe.
- **Menus**: each stall has ingredients (cooked ÷ raw weight ratio, S$ per raw kg) and menu items (cooked grams of each ingredient per portion). A vendor can photograph their menu and AI drafts the whole thing; the vendor checks the estimates and saves. Every stall starts with an example menu with made-up recipes.
- **Vendor insights**:
  - *Cook less*: average weekday leftover of each ingredient at closing, minus a buffer of half a standard deviation, in raw and cooked kg and S$.
  - *Serve less*: average grams of each ingredient left on customer plates, with a smaller suggested serving.
  - A chart of food thrown away at closing by ingredient, including today so far. The tab refreshes every 5 seconds.
- **Compost tracking**: staff record each time a bin is emptied into compost. The page shows the total food diverted from the trash.
- **Web dashboard** at `/`, with Live bin, Vendor insights, and Compost tabs.

On first start the server adds 14 days of demo history (fixed random seed, marked as demo in the database), so the insights have data to show. The window always ends yesterday: if the server starts on a later day, it moves the demo history forward. The "Reset demo data" button does the same on demand. Real weigh-ins are never touched. Turn demo data off with `LEFTOVER_SEED_DEMO=0`.

## Run it

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

To turn on photo recognition, put your OpenAI API key in a `.env` file in the project folder (it is git-ignored):

```
OPENAI_API_KEY=sk-...
```

The `.env` value overrides an `OPENAI_API_KEY` already exported in your shell. Restart the server after changing it.

The browser asks for camera permission the first time. Browsers only allow the live camera on `localhost` or HTTPS, so open the app on the laptop at `http://localhost:8000`. Other devices on the network (`--host 0.0.0.0`, then `http://<your-laptop-ip>:8000`) can still use the "Or upload a photo" field, which opens the camera on a phone.

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
docker run -p 8000:8000 -v leftover-data:/data -e OPENAI_API_KEY leftover-scale
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
| GET / PUT | `/api/stalls/{stall_id}/menu` | Read or replace a stall's ingredients and menu items |
| POST | `/api/stalls/{stall_id}/menu/scan` | Read a menu photo into a draft menu (not saved) |
| GET | `/api/stalls/{stall_id}/insights` | Daily leftovers by ingredient, cook-less and serve-less advice, and today's figures |
| POST | `/api/demo/reset` | Regenerate demo history ending yesterday; real data is kept |

Interactive API docs: http://127.0.0.1:8000/docs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LEFTOVER_DATA_DIR` | `./data` | Database and photo storage |
| `LEFTOVER_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL |
| `OPENAI_API_KEY` | none | Turns on photo recognition |
| `LEFTOVER_CLASSIFIER` | `auto` | `auto` uses OpenAI when a photo is attached and a key is set; `off` never calls OpenAI |
| `LEFTOVER_VISION_MODEL` | `gpt-6-luna` | OpenAI model for dish recognition |
| `LEFTOVER_SEED_DEMO` | `1` | Add 14 days of demo history to an empty database |

## Limitations

- Takeaway meals never reach the bin, so customer plate waste is only partly captured. The prep suggestion uses vendor end-of-day leftovers, which are captured in full.
- Ingredient splits, edible shares, and menu weights read from photos are model estimates. Vendors should check the menu draft before saving it.
- Clean plates never reach the bin, so serve-less averages are higher than the true average per customer.
- There is no login. Run it on a trusted network.
