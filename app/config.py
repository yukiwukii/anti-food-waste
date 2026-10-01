import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# The project's .env wins over variables already in the shell, so a stale exported key can't shadow it.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

DATA_DIR = Path(os.environ.get("LEFTOVER_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATABASE_URL = os.environ.get("LEFTOVER_DATABASE_URL", f"sqlite:///{DATA_DIR / 'leftover.db'}")
IMAGE_DIR = DATA_DIR / "images"

# "auto": use OpenAI vision when a photo is uploaded and OPENAI_API_KEY is set,
# falling back to the device label if the call fails. "off": never call OpenAI.
CLASSIFIER = os.environ.get("LEFTOVER_CLASSIFIER", "auto")
VISION_MODEL = os.environ.get("LEFTOVER_VISION_MODEL", "gpt-5.4-mini")

SEED_DEMO = os.environ.get("LEFTOVER_SEED_DEMO", "1") == "1"
MAX_IMAGE_BYTES = 5 * 1024 * 1024

TZ = ZoneInfo("Asia/Singapore")


def now() -> datetime:
    """Current local time in Singapore, stored naive so SQLite round-trips it unchanged."""
    return datetime.now(TZ).replace(tzinfo=None)
