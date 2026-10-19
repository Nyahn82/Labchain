"""Additional historical display context; no live clinical lookup during PDF rendering."""
import base64
from io import BytesIO

from PIL import Image

from app.config import settings
from app.models import LabDepartment, OrderPanel, SampleType, Specimen, Staff, TestCatalog, TestPanel
from app.schemas.reporting import FacilityResponse, TemplateResponse
from app.services.laboratory_service import related
from app.services.report_formatting import printable_name
from app.services.report_storage import ArtifactUnavailable, read_private


def stamp(value):
    return value.isoformat() if value is not None else None


def logo_snapshot(path):
    """Only configured private local PNG/JPEG assets; never URLs or absolute paths."""
    if not settings.report_logo_dir or not path:
        return None
    try:
        data = read_private(settings.report_logo_dir, path)
        with Image.open(BytesIO(data)) as source:
            if source.format not in {'PNG', 'JPEG'} or source.width * source.height > 4_000_000:
                return None
            source.thumbnail((400, 200))
            output = BytesIO()
            source.convert('RGB').save(output, format='PNG')
        return base64.b64encode(output.getvalue()).decode('ascii')
    except (ArtifactUnavailable, OSError, ValueError, Image.DecompressionBombError):
        return None


def capture_presentation(db, order, sources, facility, template):
    results = {}
    for item, result in sources:
        test = related(db, TestCatalog, item.test_id)
        department = related(db, LabDepartment, test.department_id) if test.department_id else None
        panel = related(db, OrderPanel, item.order_panel_id) if item.order_panel_id else None
        catalog_panel = related(db, TestPanel, panel.panel_id) if panel else None
        specimen = related(db, Specimen, result.specimen_id) if result.specimen_id else None
        results[str(result.result_item_id)] = {
            'department': department.department_name if department else None,
            'panel': catalog_panel.panel_name if catalog_panel else None,
            'methodology': test.methodology, 'remarks': result.remarks,
            'verified_at': stamp(result.verified_at),
            'specimen_code': specimen.specimen_code if specimen else None,
            'sample_type': related(db, SampleType, specimen.sample_type_id).sample_name if specimen else None,
            'collected_at': stamp(specimen.collected_at) if specimen else None,
            'received_at': stamp(specimen.received_at) if specimen else None,
        }
    return {
        'renderer': 2,
        'facility': FacilityResponse.model_validate(facility).model_dump(mode='json', exclude={'logo_path'}),
        'logo_png': logo_snapshot(facility.logo_path),
        'template': TemplateResponse.model_validate(template).model_dump(mode='json') if template else None,
        'order_code': order.order_code, 'order_date': stamp(order.order_date),
        'priority': order.priority, 'results': results, 'signatories': {},
    }


def capture_signatory(db, assignment, profile):
    staff = related(db, Staff, profile.staff_id)
    return {'name': printable_name(staff), 'designation': staff.position_title,
            'capacity': assignment.signatory_type, 'license': profile.license_number_snapshot,
            'signed_at': stamp(assignment.signed_at)}
