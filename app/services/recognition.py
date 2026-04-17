import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.worker import WorkerProfile
from app.schemas.recognition import RecognitionResult
from app.services.command import SAP_COMMANDS, fuzzy_match_command

_executor = ThreadPoolExecutor(max_workers=2)


async def recognize_command(
    audio_bytes: bytes,
    content_type: str,
    worker_id: Optional[str],
    worker: Optional[WorkerProfile],
) -> RecognitionResult:
    start = time.monotonic()

    transcribed = await _transcribe(audio_bytes, content_type)
    matched_command, text_confidence = fuzzy_match_command(transcribed)
    mapped_value = _canonical_value(matched_command)

    speaker_confidence: Optional[float] = None
    if worker and worker.embedding:
        speaker_confidence = await asyncio.get_event_loop().run_in_executor(
            _executor,
            _cosine_similarity_sync,
            audio_bytes,
            content_type,
            worker.embedding,
        )

    if speaker_confidence is not None:
        overall_confidence = 0.6 * text_confidence + 0.4 * speaker_confidence
    else:
        overall_confidence = text_confidence

    processing_ms = int((time.monotonic() - start) * 1000)

    return RecognitionResult(
        transcribed_text=transcribed,
        matched_command=matched_command,
        mapped_value=mapped_value,
        text_confidence=round(text_confidence, 4),
        speaker_confidence=round(speaker_confidence, 4) if speaker_confidence is not None else None,
        overall_confidence=round(overall_confidence, 4),
        worker_id=worker_id,
        processing_ms=processing_ms,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def _transcribe(audio_bytes: bytes, content_type: str) -> str:
    if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "test-key-not-real":
        return ""

    ext = content_type.split(";")[0].strip().split("/")[-1] or "webm"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            files={"file": (f"audio.{ext}", audio_bytes, content_type)},
            data={"model": "whisper-large-v3-turbo", "language": "en"},
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()


def _cosine_similarity_sync(
    audio_bytes: bytes,
    content_type: str,
    stored_embedding_json: str,
) -> float:
    import numpy as np

    stored = np.array(json.loads(stored_embedding_json), dtype=np.float32)
    input_emb = _compute_input_embedding(audio_bytes, content_type)
    if input_emb is None:
        return 0.0

    similarity = float(np.dot(stored, input_emb) / (np.linalg.norm(stored) * np.linalg.norm(input_emb) + 1e-8))
    return max(0.0, min(1.0, (similarity + 1.0) / 2.0))


def _compute_input_embedding(audio_bytes: bytes, content_type: str) -> Optional[list]:
    model_type = settings.EMBEDDING_MODEL

    if model_type == "mock":
        import random
        vec = [random.gauss(0, 1) for _ in range(512)]
        norm = sum(x ** 2 for x in vec) ** 0.5
        return [x / norm for x in vec]

    if model_type == "speechbrain":
        return _embed_input_speechbrain(audio_bytes, content_type)

    if model_type == "pyannote":
        return _embed_input_pyannote(audio_bytes, content_type)

    return None


def _embed_input_speechbrain(audio_bytes: bytes, content_type: str):
    import io
    import numpy as np
    import torchaudio
    from speechbrain.inference.speaker import EncoderClassifier

    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    signal, sr = torchaudio.load(io.BytesIO(audio_bytes))
    if sr != 16000:
        signal = torchaudio.functional.resample(signal, sr, 16000)
    emb = classifier.encode_batch(signal).squeeze().detach().numpy()
    norm = np.linalg.norm(emb)
    return (emb / norm).tolist() if norm > 0 else emb.tolist()


def _embed_input_pyannote(audio_bytes: bytes, content_type: str):
    import io
    import numpy as np
    from pyannote.audio import Model, Inference

    model = Model.from_pretrained(
        "pyannote/embedding",
        use_auth_token=settings.HUGGINGFACE_TOKEN,
    )
    inference = Inference(model, window="whole")
    emb = inference({"waveform": io.BytesIO(audio_bytes), "sample_rate": 16000})
    norm = np.linalg.norm(emb)
    return (emb / norm).tolist() if norm > 0 else emb.tolist()


def _canonical_value(command_key: str) -> str:
    if command_key.startswith("QUANTITY_"):
        return command_key.split("_", 1)[1]
    variants = SAP_COMMANDS.get(command_key, [])
    return variants[0].upper() if variants else command_key
