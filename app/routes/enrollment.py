from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_async_session
from app.core.security import verify_api_key
from app.models.enrollment import EnrollmentSample
from app.models.worker import WorkerProfile
from app.schemas.recognition import EnrollmentStatus
from app.services import enrollment as enrollment_svc
from app.services.command import CALIBRATION_PASSAGE

router = APIRouter(prefix="/workers", tags=["enrollment"])


@router.get("/{worker_id}/enroll/passage")
async def get_passage(worker_id: str, session: AsyncSession = Depends(get_async_session)):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    return {"worker_id": worker_id, "passage": CALIBRATION_PASSAGE}


@router.post("/{worker_id}/enroll/recording", response_model=Dict[str, Any])
async def upload_recording(
    worker_id: str,
    audio: UploadFile = File(...),
    duration_ms: int = Form(default=None),
    session: AsyncSession = Depends(get_async_session),
    _: str = Depends(verify_api_key),
):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    if not worker.gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GDPR consent required. Set gdpr_consent=true via POST /workers/{id}/profile",
        )

    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"

    sample = await enrollment_svc.save_recording(
        worker_id=worker_id,
        audio_bytes=audio_bytes,
        content_type=content_type,
        duration_ms=duration_ms,
        session=session,
    )

    worker.enrollment_status = "in_progress"
    from datetime import datetime
    worker.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "sample_id": sample.id,
        "worker_id": worker_id,
        "status": "recorded",
        "message": "Recording saved. Call /enroll/finalize to compute voice profile.",
    }


@router.post("/{worker_id}/enroll/finalize", response_model=Dict[str, Any])
async def finalize(
    worker_id: str,
    session: AsyncSession = Depends(get_async_session),
    _: str = Depends(verify_api_key),
):
    worker = await enrollment_svc.finalize_enrollment(worker_id, session)
    return {
        "worker_id": worker_id,
        "enrollment_status": worker.enrollment_status,
        "message": "Voice profile computed. Audio deleted per GDPR policy.",
    }


@router.get("/{worker_id}/enroll/status", response_model=EnrollmentStatus)
async def enrollment_status(
    worker_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    result = await session.exec(
        select(EnrollmentSample)
        .where(EnrollmentSample.worker_id == worker_id)
        .where(EnrollmentSample.audio_deleted == False)  # noqa: E712
    )
    samples = result.all()

    last_transcription = None
    if samples:
        last = max(samples, key=lambda s: s.created_at)
        last_transcription = last.transcribed_text

    return EnrollmentStatus(
        worker_id=worker_id,
        status=worker.enrollment_status,
        sample_count=len(samples),
        ready_to_finalize=len(samples) > 0,
        last_transcription=last_transcription,
    )


@router.delete("/{worker_id}/enroll/data")
async def delete_enrollment_data(
    worker_id: str,
    session: AsyncSession = Depends(get_async_session),
    _: str = Depends(verify_api_key),
):
    await enrollment_svc.delete_enrollment_data(worker_id, session)
    return {"worker_id": worker_id, "message": "Enrollment data deleted per GDPR right-to-erasure"}
