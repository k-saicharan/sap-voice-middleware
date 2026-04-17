from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import get_async_session
from app.models.worker import WorkerProfile
from app.schemas.worker import ProfileResponse
from app.services.command import CALIBRATION_PASSAGE

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, session: AsyncSession = Depends(get_async_session)):
    result = await session.exec(select(WorkerProfile))
    workers = [ProfileResponse.from_model(w).to_dict() for w in result.all()]
    return templates.TemplateResponse("workers.html", {"request": request, "workers": workers})


@router.get("/workers/{worker_id}/enroll", response_class=HTMLResponse)
async def enroll_page(
    worker_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
):
    worker = await session.get(WorkerProfile, worker_id)
    if not worker:
        return HTMLResponse(f"<h3>Worker {worker_id} not found</h3>", status_code=404)
    return templates.TemplateResponse("enroll.html", {
        "request": request,
        "worker_id": worker_id,
        "passage": CALIBRATION_PASSAGE,
        "gdpr_consent": worker.gdpr_consent,
        "enrollment_status": worker.enrollment_status,
    })


@router.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request, session: AsyncSession = Depends(get_async_session)):
    result = await session.exec(
        select(WorkerProfile).where(WorkerProfile.enrollment_status == "complete")
    )
    enrolled = result.all()
    return templates.TemplateResponse("demo.html", {
        "request": request,
        "enrolled_workers": enrolled,
    })
