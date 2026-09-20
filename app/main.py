from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import administration, laboratory, patients, physicians, referring_facilities, staff, workflow, results, reporting
from app.api import patient_activation, patient_portal, mfa
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.verification import router as verification_router
from app.config import settings


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_BUILD_DIR = FRONTEND_DIR / "dist"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.get("/", response_class=FileResponse, include_in_schema=False)
def landing_page():
    # Nginx serves production builds. Keep direct backend previews functional
    # without ever returning the uncompiled Vite source entry point.
    built_index = FRONTEND_BUILD_DIR / "index.html"
    entry = built_index if built_index.is_file() else FRONTEND_DIR / "static" / "backend-landing.html"
    return FileResponse(entry, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/assets/{asset_path:path}", response_class=FileResponse, include_in_schema=False)
def frontend_asset(asset_path: str):
    asset_root = (FRONTEND_BUILD_DIR / "assets").resolve()
    candidate = (asset_root / asset_path).resolve()
    if not candidate.is_relative_to(asset_root) or not candidate.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(candidate, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


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

app.include_router(patient_activation.router, prefix="/api/v1")
app.include_router(patient_portal.router, prefix="/api/v1")

app.include_router(mfa.router, prefix="/api/v1")
