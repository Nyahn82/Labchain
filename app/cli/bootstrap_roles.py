"""Idempotently add missing core roles without changing existing roles or users."""

import sys

from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.services.rbac_service import ensure_core_roles


def main() -> None:
    try:
        with SessionLocal.begin() as db:
            created = ensure_core_roles(db)
    except SQLAlchemyError:
        print("Role bootstrap failed. Check database availability and migrations, then retry.", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Core roles ready; created {len(created)} role(s).")


if __name__ == "__main__":
    main()
