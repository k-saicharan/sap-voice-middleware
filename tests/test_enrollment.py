import pytest


@pytest.mark.asyncio
async def test_get_passage(client):
    await client.post(
        "/workers/ENROLL_001/profile",
        json={"locale": "en-GB", "mappings": {}, "gdpr_consent": True},
    )
    r = await client.get("/workers/ENROLL_001/enroll/passage")
    assert r.status_code == 200
    data = r.json()
    assert "passage" in data
    assert len(data["passage"]) > 50


@pytest.mark.asyncio
async def test_upload_recording_requires_gdpr_consent(client, sample_audio):
    await client.post(
        "/workers/NOGDPR_001/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": False},
    )
    r = await client.post(
        "/workers/NOGDPR_001/enroll/recording",
        files={"audio": ("test.webm", sample_audio, "audio/webm")},
        data={"duration_ms": "5000"},
    )
    assert r.status_code == 400
    assert "GDPR" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_recording_success(client, sample_audio):
    await client.post(
        "/workers/ENROLL_002/profile",
        json={"locale": "en-GB", "mappings": {}, "gdpr_consent": True},
    )
    r = await client.post(
        "/workers/ENROLL_002/enroll/recording",
        files={"audio": ("test.webm", sample_audio, "audio/webm")},
        data={"duration_ms": "15000"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"


@pytest.mark.asyncio
async def test_enrollment_status(client):
    await client.post(
        "/workers/ENROLL_003/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": True},
    )
    r = await client.get("/workers/ENROLL_003/enroll/status")
    assert r.status_code == 200
    data = r.json()
    assert data["worker_id"] == "ENROLL_003"
    assert data["status"] in ("none", "in_progress", "complete")


@pytest.mark.asyncio
async def test_finalize_enrollment(client, sample_audio):
    await client.post(
        "/workers/ENROLL_FIN/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": True},
    )
    await client.post(
        "/workers/ENROLL_FIN/enroll/recording",
        files={"audio": ("test.webm", sample_audio, "audio/webm")},
        data={"duration_ms": "15000"},
    )
    r = await client.post("/workers/ENROLL_FIN/enroll/finalize")
    assert r.status_code == 200
    assert r.json()["enrollment_status"] == "complete"


@pytest.mark.asyncio
async def test_delete_enrollment_data(client, sample_audio):
    await client.post(
        "/workers/ENROLL_DEL/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": True},
    )
    await client.post(
        "/workers/ENROLL_DEL/enroll/recording",
        files={"audio": ("test.webm", sample_audio, "audio/webm")},
        data={"duration_ms": "15000"},
    )
    await client.post("/workers/ENROLL_DEL/enroll/finalize")
    r = await client.delete("/workers/ENROLL_DEL/enroll/data")
    assert r.status_code == 200
    status = await client.get("/workers/ENROLL_DEL/enroll/status")
    assert status.json()["status"] == "none"
