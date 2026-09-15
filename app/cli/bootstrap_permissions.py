"""Idempotently add missing permissions without altering existing metadata/grants."""

import sys
from sqlalchemy.exc import SQLAlchemyError
from app.database import SessionLocal
from app.services.permission_catalog import ensure_permissions


def main():
    try:
        with SessionLocal.begin() as db:
            created = ensure_permissions(db)
    except SQLAlchemyError:
        print('Permission bootstrap failed. Check database availability and migrations, then retry.', file=sys.stderr)
        raise SystemExit(1) from None
    print(f'Permissions ready; created {len(created)} permission(s).')


if __name__ == '__main__':
    main()
