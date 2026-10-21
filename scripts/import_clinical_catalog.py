"""Controlled maintenance CLI. Preview by default; apply an exact reviewed fingerprint.

Run using the application configuration only after writer exclusion and verified backup.
No clinical activation, schema changes or identity bootstrap occurs here.
"""
import argparse
import json
from app.database import SessionLocal
from app.services import starter_catalog_service as importer
from app.services.clinical_catalog_service import load_catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply-fingerprint')
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.apply_fingerprint:
            result = importer.import_catalog(db, importer.ImportRequest(
                fingerprint=args.apply_fingerprint, acknowledge_inactive_review=True),
                None, None, catalog=load_catalog())
        else:
            plan = importer.preview(db, catalog=load_catalog())
            result = {k: plan[k] for k in ('version','fingerprint','inventory','create_count','preserved_count','conflicts','notice')}
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
