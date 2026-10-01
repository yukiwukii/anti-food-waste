import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("LEFTOVER_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.environ.get("LEFTOVER_DATABASE_URL", f"sqlite:///{DATA_DIR / 'leftover.db'}")
IMAGE_DIR = DATA_DIR / "images"

# "auto": use Claude vision when a photo is uploaded, fall back to the device label if the call fails.
# "off": never call Claude.
CLASSIFIER = os.environ.get("LEFTOVER_CLASSIFIER", "auto")
CLAUDE_MODEL = os.environ.get("LEFTOVER_CLAUDE_MODEL", "claude-opus-5-5")

SEED_DEMO = os.environ.get("LEFTOVER_SEED_DEMO", "1") == "1"
MAX_IMAGE_BYTES = 5 * 1024 * 1024

TZ = ZoneInfo("Asia/Singapore")


def now() -> datetime:
    """Current local time in Singapore, stored naive so SQLite round-trips it unchanged."""
    return datetime.now(TZ).replace(tzinfo=None)
