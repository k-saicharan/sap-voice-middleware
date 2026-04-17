from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_async_session
from app.models.worker import WorkerProfile
from app.schemas.recognition import RecognitionResult
from app.services import recognition as recognition_svc

router = APIRouter(tags=["recognition"])


@router.post("/recognize", response_model=RecognitionResult)
async def recognize_any(
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session),
):
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"
    return await recognition_svc.recognize_command(
        audio_bytes=audio_bytes,
        content_type=content_type,
        worker_id=None,
        worker=None,
    )


@router.post("/workers/{worker_id}/recognize", response_model=RecognitionResult)
async def recognize_for_worker(
    worker_id: str,
    audio: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session),
):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"
    return await recognition_svc.recognize_command(
        audio_bytes=audio_bytes,
        content_type=content_type,
        worker_id=worker_id,
        worker=worker,
    )
