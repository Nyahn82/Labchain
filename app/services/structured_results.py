"""Validate bounded entered observations. Never infer susceptibility or diagnoses."""
import json
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from app.schemas.catalog_configuration import ResultSchema


def validate(schema, result_value, values, *, complete=False):
    if values is not None and (not isinstance(values, dict) or len(json.dumps(values)) > 24000):
        raise HTTPException(422, 'Structured results must be a bounded object (24 KB maximum).')
    if not schema:
        if values:
            raise HTTPException(422, 'This examination has no configured structured fields.')
        return
    config = ResultSchema.model_validate(schema)
    values = values or {}
    allowed = {f.key for f in config.fields if f.key != 'result_value'}
    if config.susceptibility:
        allowed.add('susceptibility')
    if set(values) - allowed:
        raise HTTPException(422, 'Unconfigured result fields are not allowed.')
    for field in config.fields:
        value = result_value if field.key == 'result_value' else values.get(field.key)
        if value is None or value == '':
            if complete and field.required:
                raise HTTPException(422, f'{field.label} is required before review.')
            continue
        if not isinstance(value, str) or len(value) > 1000 or not value.strip():
            raise HTTPException(422, f'{field.label} requires bounded text.')
        if field.kind == 'choice' and value not in field.choices:
            raise HTTPException(422, f'{field.label} is not a configured option.')
        if field.kind == 'number':
            try:
                number = Decimal(value)
                if not number.is_finite() or abs(number) > Decimal('999999999.999'):
                    raise InvalidOperation
            except InvalidOperation:
                raise HTTPException(422, f'{field.label} requires a finite decimal.') from None
    rows = values.get('susceptibility', [])
    if not isinstance(rows, list) or len(rows) > 80:
        raise HTTPException(422, 'At most 80 susceptibility observations are allowed.')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'organism', 'antimicrobial', 'measurement', 'unit', 'interpretation', 'method', 'standard'}:
            raise HTTPException(422, 'Susceptibility requires organism, antimicrobial, measured result, unit, interpretation, method and standard/version.')
        if any(not isinstance(v, str) or not v.strip() or len(v) > 120 for v in row.values()):
            raise HTTPException(422, 'Complete each susceptibility observation with bounded text.')
        if row['interpretation'] not in {'S', 'I', 'R', 'SDD', 'NS', 'NOT_INTERPRETED'}:
            raise HTTPException(422, 'Unrecognized susceptibility interpretation; no automatic interpretation is performed.')
        key = (row['organism'].casefold(), row['antimicrobial'].casefold())
        if key in seen:
            raise HTTPException(422, 'Duplicate organism/antimicrobial observation.')
        seen.add(key)


def presentation(schema, values):
    if not schema or not values:
        return []
    config = ResultSchema.model_validate(schema)
    lines = [f'{f.label}: {values[f.key]}' + (f' {f.unit}' if f.unit else '')
             for f in config.fields if f.key in values]
    for row in values.get('susceptibility', []):
        lines.append(' | '.join(f'{key}: {value}' for key, value in row.items()))
    return lines
