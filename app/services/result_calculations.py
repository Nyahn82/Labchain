"""Decimal-only result validation and configured flags; never medical diagnoses."""

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
import re

from fastapi import HTTPException

_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')


def age_at_date(birth_date: date | None, as_of_date: date) -> Decimal | None:
    """Elapsed whole days / 365.2425, with 40-digit precision and no age rounding."""
    if birth_date is None:
        return None
    days = (as_of_date - birth_date).days
    if days < 0:
        raise HTTPException(422, 'Birth date is later than the laboratory order date.')
    with localcontext() as context:
        context.prec = 40
        return Decimal(days) / Decimal('365.2425')


def parse_numeric_value(result_type: str, result_value: str) -> Decimal | None:
    if not isinstance(result_value, str) or not result_value.strip() or len(result_value.strip()) > 100:
        raise HTTPException(422, 'A non-empty result value of at most 100 characters is required.')
    if result_type in {'TEXT', 'POS_NEG'}:
        return None
    if result_type != 'NUMERIC':
        raise HTTPException(409, 'Invalid configured result type.')
    value = result_value.strip()
    if not _DECIMAL_TEXT.fullmatch(value):
        raise HTTPException(422, 'NUMERIC results require a finite decimal representation.')
    try:
        with localcontext() as context:
            context.prec = 40
            number = Decimal(value)
            if not number.is_finite() or number.copy_abs() > Decimal('999999999.999'):
                raise InvalidOperation
            stored = number.quantize(Decimal('0.001'))
            if stored != number:
                raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise HTTPException(422, 'Numeric result must fit DECIMAL(12,3) without rounding.') from None
    return stored


def calculate_result_flag(result_type, result_value, numeric_value, reference_range):
    if reference_range is None:
        return None
    if result_type == 'NUMERIC':
        for bound, flag, below in (
            ('critical_low', 'CRITICAL_LOW', True), ('critical_high', 'CRITICAL_HIGH', False),
            ('normal_low', 'LOW', True), ('normal_high', 'HIGH', False),
        ):
            threshold = getattr(reference_range, bound)
            if threshold is not None and (numeric_value < threshold if below else numeric_value > threshold):
                return flag
        return 'NORMAL' if reference_range.normal_low is not None or reference_range.normal_high is not None else None
    if reference_range.qualitative_normal is None:
        return None
    return 'NORMAL' if result_value.strip().casefold() == reference_range.qualitative_normal.strip().casefold() else 'ABNORMAL'
