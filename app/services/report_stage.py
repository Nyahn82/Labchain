"""Derived signing stages shared by dashboard and report drilldowns."""
from sqlalchemy import exists, select
from app.models import LabReport, ReportSignatory


def signing_stages():
    assigned = exists(select(ReportSignatory.report_signatory_id).where(ReportSignatory.report_id == LabReport.report_id))
    unsigned = exists(select(ReportSignatory.report_signatory_id).where(
        ReportSignatory.report_id == LabReport.report_id, ReportSignatory.signed_at.is_(None)))
    generated = LabReport.report_status == 'GENERATED'
    return {'unassigned': generated & ~assigned,
            'awaiting_signature': generated & assigned & unsigned,
            'awaiting_approval': generated & assigned & ~unsigned}
