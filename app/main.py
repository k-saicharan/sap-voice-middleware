import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel import Field, Session, SQLModel, create_engine, select

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

sqlite_url = "sqlite:///./voice_profiles.db"
engine = create_engine(sqlite_url, echo=False)


def get_session():
    with Session(engine) as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WorkerProfile(SQLModel, table=True):
    __tablename__ = "worker_profiles"

    worker_id: str = Field(primary_key=True)
    locale: str
    mappings: str = Field(default="{}")   # JSON string: {"DEZ": "10", ...}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProfileCreate(SQLModel):
    locale: str
    mappings: Dict[str, str]


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SAP Voice Profile Middleware",
    description=(
        "Per-worker speech_word_mapping service for the TeamViewer Frontline "
        "xPick + RealWear + SAP EWM stack. Called by the Frontline Connector "
        "at QR login to inject dialect/phonetic variant configs into the "
        "active xPick workflow."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints — static routes BEFORE parameterised routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "sap-voice-middleware"}


@app.get("/workers/", response_model=List[Dict[str, Any]])
def list_profiles(session: Session = Depends(get_session)):
    """List all worker profiles (admin use)."""
    profiles = session.exec(select(WorkerProfile)).all()
    return [_to_response(p) for p in profiles]


@app.post("/seed/demo")
def seed_demo(session: Session = Depends(get_session)):
    """Load three demo workers for dev/testing."""
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
        existing = session.get(WorkerProfile, d["worker_id"])
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
    session.commit()
    return {"seeded": len(demos), "worker_ids": [d["worker_id"] for d in demos]}


# ---------------------------------------------------------------------------
# Per-worker endpoints
# ---------------------------------------------------------------------------

@app.post("/workers/{worker_id}/profile", response_model=Dict[str, Any])
def upsert_profile(
    worker_id: str,
    body: ProfileCreate,
    session: Session = Depends(get_session),
):
    """Create or update a worker's phonetic mapping profile."""
    profile = session.get(WorkerProfile, worker_id)
    if profile:
        profile.locale = body.locale
        profile.mappings = json.dumps(body.mappings)
        profile.updated_at = datetime.utcnow()
    else:
        profile = WorkerProfile(
            worker_id=worker_id,
            locale=body.locale,
            mappings=json.dumps(body.mappings),
        )
        session.add(profile)
    session.commit()
    session.refresh(profile)
    return _to_response(profile)


@app.get("/workers/{worker_id}/profile", response_model=Dict[str, Any])
def fetch_profile(worker_id: str, session: Session = Depends(get_session)):
    """
    Called by the Frontline Connector at QR login.
    Returns speech_word_mapping in the shape the xPick Workflow Engine expects.
    """
    profile = session.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile found for worker_id={worker_id}",
        )
    return _to_response(profile)


@app.delete("/workers/{worker_id}/profile")
def delete_profile(worker_id: str, session: Session = Depends(get_session)):
    """Delete a worker's profile."""
    profile = session.get(WorkerProfile, worker_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile found for worker_id={worker_id}",
        )
    session.delete(profile)
    session.commit()
    return {"deleted": worker_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(profile: WorkerProfile) -> Dict[str, Any]:
    """
    Serialize a WorkerProfile into the Frontline Connector response shape.

    speech_word_mapping is returned as a list of {spoken, mapped} objects
    so the Frontline Connector can directly pass it to xPick's
    speech_word_mapping workflow action.
    """
    mappings: Dict[str, str] = json.loads(profile.mappings or "{}")
    return {
        "worker_id": profile.worker_id,
        "locale": profile.locale,
        "speech_word_mapping": [
            {"spoken": spoken, "mapped": mapped}
            for spoken, mapped in mappings.items()
        ],
        "updated_at": profile.updated_at.isoformat(),
    }
