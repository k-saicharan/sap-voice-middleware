import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_voice.db")
os.environ.setdefault("API_KEYS", "")
os.environ.setdefault("GROQ_API_KEY", "test-key-not-real")
os.environ.setdefault("EMBEDDING_MODEL", "mock")
os.environ.setdefault("AUDIO_STORAGE_PATH", "/tmp/test-audio")
os.environ.setdefault("ENROLLMENT_MIN_DURATION_SECONDS", "1")


@pytest_asyncio.fixture(scope="session")
async def client():
    from app.main import create_app
    from app.core.database import init_db

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await init_db()
        yield ac


@pytest.fixture
def sample_audio() -> bytes:
    # 44-byte minimal valid WAV (empty PCM, valid header)
    return (
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
        b"\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00"
        b"\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
