import json
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_async_session
from app.core.security import verify_api_key
from app.models.worker import WorkerProfile
from app.schemas.worker import ProfileCreate, ProfileResponse

router = APIRouter(tags=["workers"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "sap-voice-middleware"}


@router.get("/workers/", response_model=List[Dict[str, Any]])
async def list_profiles(session: AsyncSession = Depends(get_async_session)):
    result = await session.exec(select(WorkerProfile))
    profiles = result.all()
    return [ProfileResponse.from_model(p).to_dict() for p in profiles]


@router.post("/seed/demo")
async def seed_demo(session: AsyncSession = Depends(get_async_session)):
    demos = [
        {
            "worker_id": "PIC_PT_001",
            "locale": "pt-PT",
            "mappings": {"DEZ": "10", "QUINZE": "15", "UM": "1", "DOIS": "2"},
        },
        {
            "worker_id": "PIC_HI_002",
            "locale": "hi-IN",
            "mappings": {"SAAT": "7", "TEEN": "3", "AGLA": "NEXT", "EK": "1"},
        },
        {
            "worker_id": "PIC_PL_003",
            "locale": "pl-PL",
            "mappings": {"DZIESIEC": "10", "PIETNASCIE": "15", "ZERO": "0"},
        },
    ]
    for d in demos:
        existing = await session.get(WorkerProfile, d["worker_id"])
        if existing:
            existing.locale = d["locale"]
            existing.mappings = json.dumps(d["mappings"])
            existing.updated_at = datetime.utcnow()
        else:
            session.add(WorkerProfile(
                worker_id=d["worker_id"],
                locale=d["locale"],
                mappings=json.dumps(d["mappings"]),
            ))
    await session.commit()
    return {"seeded": len(demos), "worker_ids": [d["worker_id"] for d in demos]}


@router.post("/workers/{worker_id}/profile", response_model=Dict[str, Any])
async def upsert_profile(
    worker_id: str,
    body: ProfileCreate,
    session: AsyncSession = Depends(get_async_session),
    _: str = Depends(verify_api_key),
):
    profile = await session.get(WorkerProfile, worker_id)
    if profile:
        profile.locale = body.locale
        profile.mappings = json.dumps(body.mappings)
        if body.gdpr_consent and not profile.gdpr_consent:
            profile.gdpr_consent = True
            profile.gdpr_consent_at = datetime.utcnow()
        profile.updated_at = datetime.utcnow()
    else:
        profile = WorkerProfile(
            worker_id=worker_id,
            locale=body.locale,
            mappings=json.dumps(body.mappings),
            gdpr_consent=body.gdpr_consent,
            gdpr_consent_at=datetime.utcnow() if body.gdpr_consent else None,
        )
        session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return ProfileResponse.from_model(profile).to_dict()


@router.get("/workers/{worker_id}/profile", response_model=Dict[str, Any])
async def fetch_profile(worker_id: str, session: AsyncSession = Depends(get_async_session)):
    profile = await session.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile found for worker_id={worker_id}",
        )
    return ProfileResponse.from_model(profile).to_dict()


@router.delete("/workers/{worker_id}/profile")
async def delete_profile(
    worker_id: str,
    session: AsyncSession = Depends(get_async_session),
    _: str = Depends(verify_api_key),
):
    profile = await session.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile found for worker_id={worker_id}",
        )
    await session.delete(profile)
    await session.commit()
    return {"deleted": worker_id}
