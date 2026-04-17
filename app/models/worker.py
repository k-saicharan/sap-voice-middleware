from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class WorkerProfile(SQLModel, table=True):
    __tablename__ = "worker_profiles"

    worker_id: str = Field(primary_key=True)
    locale: str
    mappings: str = Field(default="{}")

    gdpr_consent: bool = Field(default=False)
    gdpr_consent_at: Optional[datetime] = Field(default=None)
    enrollment_status: str = Field(default="none")  # none | in_progress | complete
    embedding: Optional[str] = Field(default=None)  # JSON array of 512 floats

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
