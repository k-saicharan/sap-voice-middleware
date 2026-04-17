from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class EnrollmentSample(SQLModel, table=True):
    __tablename__ = "enrollment_samples"

    id: Optional[int] = Field(default=None, primary_key=True)
    worker_id: str = Field(foreign_key="worker_profiles.worker_id", index=True)
    audio_path: str
    duration_ms: Optional[int] = Field(default=None)
    transcribed_text: Optional[str] = Field(default=None)
    audio_deleted: bool = Field(default=False)
    audio_deleted_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
