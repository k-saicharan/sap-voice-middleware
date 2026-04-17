from typing import Optional

from pydantic import BaseModel


class RecognitionResult(BaseModel):
    transcribed_text: str
    matched_command: str
    mapped_value: str
    text_confidence: float
    speaker_confidence: Optional[float] = None
    overall_confidence: float
    worker_id: Optional[str] = None
    processing_ms: int


class EnrollmentStatus(BaseModel):
    worker_id: str
    status: str
    sample_count: int
    ready_to_finalize: bool
    last_transcription: Optional[str] = None
