import os
import tempfile

# Point the app at a throwaway database before it is imported.
os.environ["LEFTOVER_DATA_DIR"] = tempfile.mkdtemp(prefix="leftover-test-")
os.environ["LEFTOVER_CLASSIFIER"] = "off"
os.environ["LEFTOVER_SEED_DEMO"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
