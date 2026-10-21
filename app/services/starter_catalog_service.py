"""Preview and additive import into existing laboratory tables; never a startup seed.

All new records are inactive. Existing records and their relationships are
preserved. The authorized request owns one transaction, counters and audit included.
"""
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import inspect, select

from app.models import (AuditLog, CodeSequence, LabDepartment, PanelSection, PanelTest, SampleType,
                        TestCatalog, TestPanel, TestSampleType)
from app.schemas import laboratory as schemas
from app.schemas.identity import Input
from app.schemas.catalog_configuration import ResultSchema
from app.services.code_generation_service import allocate_code
from app.services.identity_service import audit, mutation
from app.services.laboratory_service import retry_deadlocks

CATALOG_PATH = Path(__file__).resolve().parents[1] / 'data' / 'philippine_laboratory_catalog.json'
REVIEW_NOTICE = ('All new records remain inactive. Qualified laboratory personnel must approve '
                 'facility capability, specimen SOPs, reporting format, units, methodology, '
                 'reference applicability and panel composition before clinical use. '
                 'Existing records and relationships are preserved, not clinically endorsed.')


def normalized(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value)
                           if not unicodedata.combining(c)).casefold().split())


class Definition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(pattern=r'^[a-z][a-z0-9_]*$', max_length=40)
    name: str = Field(min_length=1, max_length=150)
    aliases: list[str] = Field(default_factory=list)


class NamedDefinition(Definition):
    description: str
    specimen_code: str | None = None
    collection_guidance: dict | None = None


class TestDefinition(Definition):
    suggested_unit: str | None = None
    service_tier: Literal['ROUTINE', 'GENERAL', 'SPECIALIZED', 'REFERRAL_ONLY'] | None = None
    restricted_workflow: str | None = None
    result_schema: ResultSchema | None = None
    department: str
    samples: list[str] = Field(min_length=1)
    result_type: Literal['NUMERIC', 'TEXT', 'POS_NEG']
    sources: list[str] = Field(min_length=1)
    review_note: str
    reference_policy: str


class PanelDefinition(NamedDefinition):
    sections: dict[str, list[str]] = Field(default_factory=dict)
    department: str
    tests: list[str] = Field(min_length=1)


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str
    url: HttpUrl


class Catalog(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str
    sources: dict[str, Source]
    departments: list[NamedDefinition]
    samples: list[NamedDefinition]
    tests: list[TestDefinition]
    panels: list[PanelDefinition]

    @model_validator(mode='after')
    def integrity(self):
        for kind in KINDS:
            definitions = getattr(self, kind)
            keys, names = set(), set()
            for item in definitions:
                aliases = [normalized(v) for v in [item.name, *item.aliases]]
                if item.key in keys or not all(aliases) or len(set(aliases)) != len(aliases) or names.intersection(aliases):
                    raise ValueError('Duplicate or ambiguous catalog definition.')
                keys.add(item.key)
                names.update(aliases)
        departments = {v.key for v in self.departments}
        samples = {v.key for v in self.samples}
        tests = {v.key for v in self.tests}
        for item in self.departments:
            schemas.DepartmentCreate(department_name=item.name, description=item.description, is_active=False)
        for item in self.samples:
            schemas.SampleTypeCreate(sample_name=item.name, description=item.description, collection_guidance=item.collection_guidance, is_active=False)
        for item in self.tests:
            if item.department not in departments or not set(item.samples) <= samples or not set(item.sources) <= self.sources.keys() or len(set(item.samples)) != len(item.samples):
                raise ValueError('Invalid test relationships or sources.')
            schemas.TestCreate(test_name=item.name, department_id=1, result_type=item.result_type, result_schema=item.result_schema, is_active=False)
        for item in self.panels:
            if item.department not in departments or not set(item.tests) <= tests or len(set(item.tests)) != len(item.tests):
                raise ValueError('Invalid panel composition.')
            section_tests = [key for members in item.sections.values() for key in members]
            if len(section_tests) != len(set(section_tests)) or not set(section_tests) <= set(item.tests):
                raise ValueError('Invalid or duplicate panel section membership.')
            for name in item.sections:
                schemas.SectionCreate(section_name=name, sort_order=0)
            schemas.PanelCreate(panel_name=item.name, description=item.description, is_active=False)
        return self


class ImportRequest(Input):
    fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    acknowledge_inactive_review: Literal[True]


# Dependency order; no independent alternative catalog or new identifier namespace.
KINDS = {
    'departments': (LabDepartment, 'department_name', 'department_code', 'DEPARTMENT'),
    'samples': (SampleType, 'sample_name', None, None),
    'tests': (TestCatalog, 'test_name', 'test_code', 'TEST'),
    'panels': (TestPanel, 'panel_name', 'panel_code', 'PANEL'),
}


def load_catalog():
    return Catalog.model_validate_json(CATALOG_PATH.read_text())


def preview(db, *, lock=False, catalog=None):
    catalog = catalog or load_catalog()
    rows, snapshot = {}, {}
    # Current locking reads during import, even if auth opened an older snapshot.
    for kind, (model, name, code, sequence) in KINDS.items():
        query = select(model).order_by(inspect(model).primary_key[0])
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        rows[kind] = list(db.scalars(query))
        snapshot[kind] = [{c.key: getattr(row, c.key) for c in inspect(model).columns} for row in rows[kind]]
    # Audit evidence is only a duplicate-prevention guard, never an instruction
    # to recreate or overwrite an entry renamed/removed after an earlier import.
    history = {}
    history_query = select(AuditLog.entity_type, AuditLog.record_id, AuditLog.new_value).where(
        AuditLog.action == 'STARTER_CATALOG_CREATE')
    if lock:
        history_query = history_query.with_for_update(read=True)
    for entity, record_id, evidence in db.execute(history_query):
        if isinstance(evidence, dict):
            history.setdefault((entity, evidence.get('catalog_key')), set()).add(record_id)
    items, conflicts, matches = [], [], {}
    for kind, (model, name, code, sequence) in KINDS.items():
        for definition in getattr(catalog, kind):
            aliases = {normalized(v) for v in [definition.name, *definition.aliases]}
            found = [r for r in rows[kind] if normalized(getattr(r, name)) in aliases]
            identity = (kind, definition.key)
            match = found[0] if len(found) == 1 else None
            matches[identity] = match
            previous = history.get((model.__tablename__, definition.key), set())
            current_id = inspect(match).identity[0] if match is not None else None
            if previous and previous != {current_id}:
                conflicts.append(f'{kind}: {definition.name}: a previous import was renamed, removed or remapped; manual reconciliation required.')
            if len(found) > 1:
                conflicts.append(f'{kind}: {definition.name}: multiple existing name/alias matches; resolve manually.')
            if kind in {'tests', 'panels'}:
                other = 'panels' if kind == 'tests' else 'tests'
                other_name = KINDS[other][1]
                if any(normalized(getattr(r, other_name)) in aliases for r in rows[other]):
                    conflicts.append(f'{kind}: {definition.name}: existing aggregate/individual name collision; review manually.')
                if match is not None:
                    department = matches.get(('departments', definition.department))
                    if department is None or match.department_id != department.department_id:
                        conflicts.append(f'{kind}: {definition.name}: existing department differs; no automatic remapping.')
                    if kind == 'tests' and match.result_type != definition.result_type:
                        conflicts.append(f'tests: {definition.name}: existing result type differs; no automatic conversion.')
            items.append(dict(kind=kind, key=definition.key, name=definition.name,
                              action='PRESERVE' if match is not None else 'CREATE_INACTIVE',
                              record_id=inspect(match).identity[0] if match is not None else None,
                              code=getattr(match, code) if match is not None and code else None,
                              definition=definition.model_dump()))
    digest = hashlib.sha256(json.dumps({'catalog': catalog.model_dump(mode='json'), 'state': snapshot},
                                      sort_keys=True, default=str).encode()).hexdigest()
    return dict(version=catalog.version, fingerprint=digest, notice=REVIEW_NOTICE,
                sources={k: v.model_dump(mode='json') for k, v in catalog.sources.items()},
                inventory={kind: len(getattr(catalog, kind)) for kind in KINDS},
                create_count=sum(i['action'] == 'CREATE_INACTIVE' for i in items),
                preserved_count=sum(i['action'] == 'PRESERVE' for i in items),
                conflicts=conflicts, items=items)


@retry_deadlocks
def import_catalog(db, payload: ImportRequest, actor_id, ip_address, *, catalog=None):
    with mutation(db):
        # Serialize importers before their snapshot reads. No counter is changed
        # until the complete preview, conflicts and fingerprint are validated.
        keys = sorted(v[3] for v in KINDS.values() if v[3])
        sequences = list(db.scalars(select(CodeSequence).where(CodeSequence.sequence_key.in_(keys))
                                  .order_by(CodeSequence.sequence_key).with_for_update()))
        if len(sequences) != len(keys):
            raise HTTPException(409, 'Required automatic code sequences are not configured.')
        plan = preview(db, lock=True, catalog=catalog)
        if plan['conflicts']:
            raise HTTPException(409, 'Catalog mappings require manual review; preview the conflicts.')
        if payload.fingerprint != plan['fingerprint']:
            raise HTTPException(409, 'Catalog changed after preview. Review a fresh preview before importing.')
        ids, created = {}, []
        for item in plan['items']:
            kind, definition = item['kind'], item['definition']
            model, name_field, code_field, sequence = KINDS[kind]
            if item['action'] == 'PRESERVE':
                ids[kind, item['key']] = item['record_id']
                continue
            values = {name_field: item['name'], 'is_active': False}
            if code_field:
                values[code_field] = allocate_code(db, sequence)
            if kind in {'departments', 'samples', 'panels'}:
                values['description'] = definition['description']
            if kind in {'tests', 'panels'}:
                values['department_id'] = ids['departments', definition['department']]
            if kind == 'tests':
                values.update(result_type=definition['result_type'], default_unit=None, methodology=None)
            expanded = plan['version'].startswith('ph-clinical-')
            if expanded and kind == 'samples':
                values.update(specimen_code=definition['specimen_code'], collection_guidance=definition['collection_guidance'])
            if expanded and kind in {'tests', 'panels'}:
                values.update(facility_status='UNREVIEWED', catalog_metadata={
                    'version': plan['version'], 'key': item['key'],
                    'review_status': 'GENERAL_INFORMATION_ONLY_FACILITY_REVIEW_REQUIRED',
                    **{k: definition.get(k) for k in ['sources', 'review_note', 'reference_policy', 'service_tier', 'restricted_workflow']}})
            if expanded and kind in {'tests', 'panels'}:
                values['catalog_metadata']['source_references'] = [plan['sources'][key] for key in definition.get('sources', [])]
                values['catalog_metadata']['reviewed_on'] = '2026-10-21'
            if expanded and kind == 'tests':
                values.update(default_unit=definition.get('suggested_unit'), result_schema=definition.get('result_schema'),
                              aliases='; '.join(definition.get('aliases', [])) or None)
            record = model(**values)
            db.add(record)
            db.flush()
            record_id = inspect(record).identity[0]
            ids[kind, item['key']] = record_id
            if kind == 'tests':
                db.add_all(TestSampleType(test_id=record_id, sample_type_id=ids['samples', key], is_default=False)
                           for key in definition['samples'])
            elif kind == 'panels':
                section_ids = {}
                for position, (label, keys) in enumerate(definition.get('sections', {}).items(), 1):
                    section = PanelSection(panel_id=record_id, section_name=label, sort_order=position, is_active=False)
                    db.add(section); db.flush()
                    section_ids.update({key: section.section_id for key in keys})
                db.add_all(PanelTest(panel_id=record_id, test_id=ids['tests', key], sort_order=position,
                                     is_required=True, section_id=section_ids.get(key))
                           for position, key in enumerate(definition['tests'], 1))
            audit(db, actor_id, 'STARTER_CATALOG_CREATE', model.__tablename__, record_id, ip_address,
                  new={'catalog_version': plan['version'], 'catalog_key': item['key'], 'is_active': False})
            created.append({'kind': kind, 'name': item['name'], 'record_id': record_id,
                            'code': getattr(record, code_field) if code_field else None})
        db.flush()
        result = dict(version=plan['version'], created=created, preserved_count=plan['preserved_count'], notice=REVIEW_NOTICE,
                      inserted=len(created), updated=0, skipped=plan['preserved_count'], rejected=0)
    return result
