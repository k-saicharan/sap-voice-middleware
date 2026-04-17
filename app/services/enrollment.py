import asyncio
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import aiofiles
from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.enrollment import EnrollmentSample
from app.models.worker import WorkerProfile

_executor = ThreadPoolExecutor(max_workers=2)


async def save_recording(
    worker_id: str,
    audio_bytes: bytes,
    content_type: str,
    duration_ms: Optional[int],
    session: AsyncSession,
) -> EnrollmentSample:
    if duration_ms is not None:
        min_ms = settings.ENROLLMENT_MIN_DURATION_SECONDS * 1000
        if duration_ms < min_ms:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Recording too short: {duration_ms}ms (minimum {min_ms}ms)",
            )
        if duration_ms > 120_000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recording too long (maximum 120 seconds)",
            )

    ext = _ext_for_content_type(content_type)
    worker_dir = os.path.join(settings.AUDIO_STORAGE_PATH, worker_id)
    os.makedirs(worker_dir, exist_ok=True)
    file_path = os.path.join(worker_dir, f"{uuid.uuid4()}{ext}")

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(audio_bytes)

    sample = EnrollmentSample(
        worker_id=worker_id,
        audio_path=file_path,
        duration_ms=duration_ms,
    )
    session.add(sample)
    await session.commit()
    await session.refresh(sample)
    return sample


async def finalize_enrollment(worker_id: str, session: AsyncSession) -> WorkerProfile:
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")
    if not worker.gdpr_consent:
        raise HTTPException(status_code=400, detail="GDPR consent required before enrollment")

    result = await session.exec(
        select(EnrollmentSample)
        .where(EnrollmentSample.worker_id == worker_id)
        .where(EnrollmentSample.audio_deleted == False)  # noqa: E712
    )
    samples = result.all()
    if not samples:
        raise HTTPException(status_code=400, detail="No recordings found to finalize")

    audio_paths = [s.audio_path for s in samples if os.path.exists(s.audio_path)]
    if not audio_paths:
        raise HTTPException(status_code=400, detail="Audio files not found on disk")

    embedding = await asyncio.get_event_loop().run_in_executor(
        _executor, _compute_embedding_sync, audio_paths
    )

    worker.embedding = json.dumps(embedding)
    worker.enrollment_status = "complete"
    worker.updated_at = datetime.utcnow()

    now = datetime.utcnow()
    for sample in samples:
        try:
            if os.path.exists(sample.audio_path):
                os.remove(sample.audio_path)
        except OSError:
            pass
        sample.audio_deleted = True
        sample.audio_deleted_at = now

    await session.commit()
    await session.refresh(worker)
    return worker


async def delete_enrollment_data(worker_id: str, session: AsyncSession) -> None:
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {worker_id} not found")

    result = await session.exec(
        select(EnrollmentSample).where(EnrollmentSample.worker_id == worker_id)
    )
    samples = result.all()
    now = datetime.utcnow()
    for sample in samples:
        if not sample.audio_deleted and os.path.exists(sample.audio_path):
            try:
                os.remove(sample.audio_path)
            except OSError:
                pass
            sample.audio_deleted = True
            sample.audio_deleted_at = now

    worker.embedding = None
    worker.enrollment_status = "none"
    worker.updated_at = datetime.utcnow()
    await session.commit()


def _compute_embedding_sync(audio_paths: list[str]) -> list[float]:
    """CPU-bound embedding computation — runs in thread pool."""
    model_type = settings.EMBEDDING_MODEL

    if model_type == "mock":
        import random
        vec = [random.gauss(0, 1) for _ in range(512)]
        norm = sum(x ** 2 for x in vec) ** 0.5
        return [x / norm for x in vec]

    if model_type == "speechbrain":
        return _embed_speechbrain(audio_paths)

    if model_type == "pyannote":
        return _embed_pyannote(audio_paths)

    raise ValueError(f"Unknown EMBEDDING_MODEL: {model_type}")


def _embed_speechbrain(audio_paths: list[str]) -> list[float]:
    import numpy as np
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    embeddings = []
    for path in audio_paths:
        signal, sr = torchaudio.load(path)
        if sr != 16000:
            signal = torchaudio.functional.resample(signal, sr, 16000)
        emb = classifier.encode_batch(signal)
        embeddings.append(emb.squeeze().detach().numpy())

    mean_emb = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(mean_emb)
    if norm > 0:
        mean_emb = mean_emb / norm
    return mean_emb.tolist()


def _embed_pyannote(audio_paths: list[str]) -> list[float]:
    import numpy as np
    from pyannote.audio import Model, Inference

    model = Model.from_pretrained(
        "pyannote/embedding",
        use_auth_token=settings.HUGGINGFACE_TOKEN,
    )
    inference = Inference(model, window="whole")
    embeddings = [inference(p) for p in audio_paths]
    mean_emb = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(mean_emb)
    if norm > 0:
        mean_emb = mean_emb / norm
    return mean_emb.tolist()


def _ext_for_content_type(content_type: str) -> str:
    ct = content_type.split(";")[0].strip().lower()
    mapping = {
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/mp4": ".mp4",
        "audio/mpeg": ".mp3",
        "audio/x-wav": ".wav",
    }
    return mapping.get(ct, ".webm")
