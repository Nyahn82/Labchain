"""Automatic-code contracts for laboratory master resources."""

import pytest

from pydantic import ValidationError

from app.schemas.laboratory import (
    DepartmentCreate, DepartmentPatch, DepartmentResponse,
    TestCreate as LabTestCreate,
    TestPatch as LabTestPatch,
    TestResponse as LabTestResponse,
    PanelCreate, PanelPatch, PanelResponse,
)

from app.schemas.workflow import (
    ReasonCreate, ReasonPatch, ReasonResponse,
)

from app.schemas.reporting import (
    TemplateCreate, TemplatePatch, TemplateResponse,
)


RESOURCES = [
    (
        DepartmentCreate,
        DepartmentPatch,
        DepartmentResponse,
        "department_code",
        {"department_name": "Synthetic Department"},
    ),
    (
        LabTestCreate,
        LabTestPatch,
        LabTestResponse,
        "test_code",
        {
            "test_name": "Synthetic Test",
            "department_id": 1,
            "result_type": "NUMERIC",
        },
    ),
    (
        PanelCreate,
        PanelPatch,
        PanelResponse,
        "panel_code",
        {"panel_name": "Synthetic Panel"},
    ),
    (
        ReasonCreate,
        ReasonPatch,
        ReasonResponse,
        "reason_code",
        {"reason_name": "Synthetic Reason"},
    ),
    (
        TemplateCreate,
        TemplatePatch,
        TemplateResponse,
        "template_code",
        {"template_name": "Synthetic Template"},
    ),
]


@pytest.mark.parametrize(
    "create,patch,response,code_field,payload",
    RESOURCES,
)
def test_create_does_not_require_code(
    create, patch, response, code_field, payload
):
    item = create.model_validate(payload)
    assert code_field not in item.model_dump()


@pytest.mark.parametrize(
    "create,patch,response,code_field,payload",
    RESOURCES,
)
def test_create_rejects_manual_code(
    create, patch, response, code_field, payload
):
    with pytest.raises(ValidationError) as exc:
        create.model_validate({
            **payload,
            code_field: "MANUAL-001",
        })

    assert any(
        error["type"] == "extra_forbidden"
        for error in exc.value.errors()
    )


@pytest.mark.parametrize(
    "create,patch,response,code_field,payload",
    RESOURCES,
)
def test_patch_rejects_code_changes(
    create, patch, response, code_field, payload
):
    with pytest.raises(ValidationError) as exc:
        patch.model_validate({
            code_field: "CHANGED-001",
        })

    assert any(
        error["type"] == "extra_forbidden"
        for error in exc.value.errors()
    )


@pytest.mark.parametrize(
    "create,patch,response,code_field,payload",
    RESOURCES,
)
def test_response_retains_code(
    create, patch, response, code_field, payload
):
    assert code_field in response.model_fields
    assert response.model_fields[code_field].is_required()
