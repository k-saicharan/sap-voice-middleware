from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_async_session
from app.models.worker import WorkerProfile
from app.schemas.recognition import RecognitionResult
from app.services import recognition as recognition_svc
from app.services.command import fuzzy_match_command

router = APIRouter(tags=["recognition"])


# --- WearHF intent JSON constants (demo boundary layer) -----------------------
# The demo's Mock WearHF Layer posts a mocked Android intent JSON directly to
# the /recognize endpoint instead of raw audio. This lets the existing
# RecognitionService + CommandService stay untouched while the offline
# Whisper.cpp transcription happens upstream in the WearHF mock.
_WEARHF_ACTION = "com.realwear.wearhf.intent.action.SPEECH_EVENT"
_WEARHF_TEXT_KEY = "com.realwear.wearhf.intent.extra.ORIGINAL_COMMAND"
_WEARHF_COMMAND_KEY = "com.realwear.wearhf.intent.extra.COMMAND"


def _looks_like_wearhf_intent(body: dict) -> bool:
    return isinstance(body, dict) and body.get("action") == _WEARHF_ACTION


def _result_from_wearhf_intent(body: dict, worker_id: Optional[str], worker: Optional[WorkerProfile] = None) -> RecognitionResult:
    import time

    start = time.monotonic()
    text = (body.get("extras") or {}).get(_WEARHF_TEXT_KEY, "") or ""
    # In a real SPEECH_EVENT, WearHF provides the matched command, but we want our middleware to do the matching
    # based on what Whisper heard (ORIGINAL_COMMAND). We will use the ORIGINAL_COMMAND for fuzzy matching to simulate
    # how it works when we bypass the WearHF grammar engine and use Whisper.
    matched_command, text_confidence = fuzzy_match_command(text)
    from app.services.command import SAP_COMMANDS

    if matched_command.startswith("QUANTITY_"):
        mapped_value = matched_command.split("_", 1)[1]
    else:
        variants = SAP_COMMANDS.get(matched_command, [])
        mapped_value = variants[0].upper() if variants else matched_command

    # Identity simulation for JSON/Intent path
    speaker_confidence = None
    if worker:
        if worker.enrollment_status == "complete":
            # If the user has a fingerprint, we simulate a 98% match 
            # (In a real system, the orchestrator would have sent the audio bytes)
            speaker_confidence = 0.9832
        else:
            # Not enrolled
            speaker_confidence = None

    processing_ms = int((time.monotonic() - start) * 1000)
    return RecognitionResult(
        transcribed_text=text,
        matched_command=matched_command,
        mapped_value=mapped_value,
        text_confidence=round(text_confidence, 4),
        speaker_confidence=speaker_confidence,
        overall_confidence=round(text_confidence, 4),
        worker_id=worker_id,
        processing_ms=processing_ms,
    )


@router.post("/recognize", response_model=RecognitionResult)
async def recognize_any(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        body = await request.json()
        if _looks_like_wearhf_intent(body):
            return _result_from_wearhf_intent(body, worker_id=None, worker=None)
        raise HTTPException(status_code=400, detail="Unsupported JSON payload")

    form = await request.form()
    audio = form.get("audio")
    if audio is None or not isinstance(audio, UploadFile):
        raise HTTPException(status_code=422, detail="audio file required")

    audio_bytes = await audio.read()
    audio_content_type = audio.content_type or "audio/webm"
    return await recognition_svc.recognize_command(
        audio_bytes=audio_bytes,
        content_type=audio_content_type,
        worker_id=None,
        worker=None,
    )


@router.post("/workers/{worker_id}/recognize", response_model=RecognitionResult)
async def recognize_for_worker(
    worker_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        body = await request.json()
        if _looks_like_wearhf_intent(body):
            return _result_from_wearhf_intent(body, worker_id=worker_id, worker=worker)
        raise HTTPException(status_code=400, detail="Unsupported JSON payload")

    form = await request.form()
    audio = form.get("audio")
    if audio is None or not isinstance(audio, UploadFile):
        raise HTTPException(status_code=422, detail="audio file required")

    audio_bytes = await audio.read()
    audio_content_type = audio.content_type or "audio/webm"
    return await recognition_svc.recognize_command(
        audio_bytes=audio_bytes,
        content_type=audio_content_type,
        worker_id=worker_id,
        worker=worker,
        session=session,
    )
