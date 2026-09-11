from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.config import settings


router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "application": settings.app_name,
        "node_id": settings.node_id,
        "node_name": settings.node_name,
    }


@router.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "ready",
            "mysql": {
                "connected": True,
                "database": settings.db_name,
            },
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable",
        ) from None
