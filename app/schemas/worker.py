import json
from typing import Any, Dict, List

from pydantic import BaseModel

from app.models.worker import WorkerProfile


class ProfileCreate(BaseModel):
    locale: str
    mappings: Dict[str, str]
    gdpr_consent: bool = False


class ProfileResponse(BaseModel):
    worker_id: str
    locale: str
    speech_word_mapping: List[Dict[str, str]]
    enrollment_status: str
    updated_at: str

    @classmethod
    def from_model(cls, profile: WorkerProfile) -> "ProfileResponse":
        mappings: Dict[str, str] = json.loads(profile.mappings or "{}")
        return cls(
            worker_id=profile.worker_id,
            locale=profile.locale,
            speech_word_mapping=[
                {"spoken": spoken, "mapped": mapped}
                for spoken, mapped in mappings.items()
            ],
            enrollment_status=profile.enrollment_status,
            updated_at=profile.updated_at.isoformat(),
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
