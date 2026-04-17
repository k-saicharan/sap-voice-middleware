import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_seed_demo(client):
    r = await client.post("/seed/demo")
    assert r.status_code == 200
    data = r.json()
    assert data["seeded"] == 3
    assert "PIC_PT_001" in data["worker_ids"]


@pytest.mark.asyncio
async def test_list_workers(client):
    await client.post("/seed/demo")
    r = await client.get("/workers/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 3


@pytest.mark.asyncio
async def test_upsert_and_fetch_profile(client):
    r = await client.post(
        "/workers/TEST_001/profile",
        json={"locale": "en-GB", "mappings": {"YEAH": "CONFIRM"}, "gdpr_consent": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["worker_id"] == "TEST_001"
    assert body["enrollment_status"] == "none"
    assert {"spoken": "YEAH", "mapped": "CONFIRM"} in body["speech_word_mapping"]

    r2 = await client.get("/workers/TEST_001/profile")
    assert r2.status_code == 200
    assert r2.json()["worker_id"] == "TEST_001"


@pytest.mark.asyncio
async def test_fetch_missing_profile(client):
    r = await client.get("/workers/DOES_NOT_EXIST/profile")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_profile(client):
    await client.post(
        "/workers/DEL_001/profile",
        json={"locale": "en-US", "mappings": {}, "gdpr_consent": False},
    )
    r = await client.delete("/workers/DEL_001/profile")
    assert r.status_code == 200
    assert r.json()["deleted"] == "DEL_001"

    r2 = await client.get("/workers/DEL_001/profile")
    assert r2.status_code == 404
