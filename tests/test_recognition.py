import pytest


@pytest.mark.asyncio
async def test_recognize_any(client, sample_audio, monkeypatch):
    from app.services import recognition as rec_svc

    async def mock_transcribe(audio_bytes, content_type):
        return "confirm"

    monkeypatch.setattr(rec_svc, "_transcribe", mock_transcribe)

    r = await client.post(
        "/recognize",
        files={"audio": ("cmd.webm", sample_audio, "audio/webm")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["matched_command"] == "CONFIRM"
    assert data["text_confidence"] > 0.5
    assert data["speaker_confidence"] is None


@pytest.mark.asyncio
async def test_recognize_for_enrolled_worker(client, sample_audio, monkeypatch):
    from app.services import recognition as rec_svc

    async def mock_transcribe(audio_bytes, content_type):
        return "ten"

    monkeypatch.setattr(rec_svc, "_transcribe", mock_transcribe)

    # Create and enroll a worker first
    await client.post(
        "/workers/REC_W01/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": True},
    )
    await client.post(
        "/workers/REC_W01/enroll/recording",
        files={"audio": ("test.webm", sample_audio, "audio/webm")},
        data={"duration_ms": "15000"},
    )
    await client.post("/workers/REC_W01/enroll/finalize")

    r = await client.post(
        "/workers/REC_W01/recognize",
        files={"audio": ("cmd.webm", sample_audio, "audio/webm")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["matched_command"] == "QUANTITY_10"
    assert data["speaker_confidence"] is not None
    assert data["worker_id"] == "REC_W01"


@pytest.mark.asyncio
async def test_recognize_unknown_worker(client, sample_audio):
    r = await client.post(
        "/workers/NONEXISTENT/recognize",
        files={"audio": ("cmd.webm", sample_audio, "audio/webm")},
    )
    assert r.status_code == 404
