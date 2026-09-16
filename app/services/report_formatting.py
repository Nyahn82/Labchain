"""Deterministic printable snapshots, independent of future master-data edits."""
from fastapi import HTTPException


def printable_name(person):
    return ' '.join(' '.join(getattr(person, field, None).split()) for field in
                    ('first_name', 'middle_name', 'last_name', 'suffix')
                    if getattr(person, field, None) and getattr(person, field).strip())


def full_years(birth_date, day):
    if birth_date is None:
        return None
    if birth_date > day:
        raise HTTPException(409, 'Birth date is later than report generation date.')
    return day.year - birth_date.year - ((day.month, day.day) < (birth_date.month, birth_date.day))


def decimal_text(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def printable_range(reference, result_type):
    if reference is None:
        return None
    if result_type != 'NUMERIC':
        return reference.qualitative_normal
    low, high = reference.normal_low, reference.normal_high
    if low is not None and high is not None:
        return f'{decimal_text(low)} - {decimal_text(high)}'
    if high is not None:
        return f'<= {decimal_text(high)}'
    if low is not None:
        return f'>= {decimal_text(low)}'
    return None
