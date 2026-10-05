"""Small fixed dialect expressions, independent of all user-controlled SQL text."""
from sqlalchemy import Float, Integer
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class SecondsBetween(FunctionElement):
    type = Float()
    inherit_cache = True


@compiles(SecondsBetween, 'mysql')
def mysql_seconds(element, compiler, **kw):
    start, end = [compiler.process(c, **kw) for c in element.clauses]
    return f'(TIMESTAMPDIFF(MICROSECOND, {start}, {end}) / 1000000.0)'


@compiles(SecondsBetween, 'sqlite')
def sqlite_seconds(element, compiler, **kw):
    start, end = [compiler.process(c, **kw) for c in element.clauses]
    return f'((julianday({end}) - julianday({start})) * 86400.0)'


class MondayWeekday(FunctionElement):
    type = Integer()
    inherit_cache = True


@compiles(MondayWeekday, 'mysql')
def mysql_weekday(element, compiler, **kw):
    return f'WEEKDAY({compiler.process(list(element.clauses)[0], **kw)})'


@compiles(MondayWeekday, 'sqlite')
def sqlite_weekday(element, compiler, **kw):
    column = compiler.process(list(element.clauses)[0], **kw)
    return f"((CAST(strftime('%w', {column}) AS INTEGER) + 6) % 7)"
