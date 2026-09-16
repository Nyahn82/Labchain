from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import administration, laboratory, patients, physicians, referring_facilities, staff, workflow, results, reporting
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.verification import router as verification_router
from app.config import settings


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.get("/", response_class=FileResponse, include_in_schema=False)
def landing_page():
    return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")


@app.get("/api/v1/")
def root():
    return {
        "message": "RHU LabChain backend is running",
        "node_id": settings.node_id,
        "node_name": settings.node_name,
    }


app.include_router(
    health_router,
    prefix="/api/v1",
    tags=["System"],
)
app.include_router(
    auth_router,
    prefix="/api/v1",
    tags=["Authentication"],
)

for identity_router in (patients.router, staff.router, physicians.router, referring_facilities.router, administration.router):
    app.include_router(identity_router, prefix="/api/v1")

app.include_router(laboratory.router, prefix="/api/v1")

app.include_router(workflow.router, prefix="/api/v1")

app.include_router(results.router, prefix="/api/v1")

app.include_router(reporting.router, prefix="/api/v1")

app.include_router(verification_router, prefix="/api/v1")
