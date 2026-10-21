import os
import tempfile
from pathlib import Path

state_root = Path(tempfile.mkdtemp(prefix="cinedub-tests-"))
os.environ["CINEDUB_DATABASE_URL"] = f"sqlite:///{state_root / 'test.db'}"
os.environ["CINEDUB_STORAGE_ROOT"] = str(state_root / "storage")
os.environ["CINEDUB_TRANSLATOR"] = "fake"
os.environ["CINEDUB_TRANSCRIBER"] = "fake"
os.environ["CINEDUB_DIARIZER"] = "fake"
os.environ["CINEDUB_VOICE_SYNTHESIZER"] = "fake"

import httpx  # noqa: E402
import pytest  # noqa: E402
from cinedub_api.database import Base, SessionLocal, engine  # noqa: E402
from cinedub_api.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session():
    with SessionLocal() as database_session:
        yield database_session
