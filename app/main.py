from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware
from app.core.database import init_db
from app.routes import workers as workers_router
from app.routes import enrollment as enrollment_router
from app.routes import recognition as recognition_router
from app.routes import dashboard as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="SAP Voice Profile Middleware",
        description=(
            "Per-worker voice enrollment and speaker-adapted recognition for the "
            "RealWear + TeamViewer Frontline xPick + SAP EWM warehouse picking stack. "
            "Workers enroll by reading a calibration passage; the system builds a speaker "
            "profile used to improve command recognition accuracy at the middleware layer. "
            "SAP EWM is never modified."
        ),
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(workers_router.router)
    app.include_router(enrollment_router.router)
    app.include_router(recognition_router.router)
    app.include_router(dashboard_router.router)

    return app


app = create_app()
