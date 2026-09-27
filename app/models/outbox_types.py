"""Portable declarations with precise MySQL outbox storage."""
from sqlalchemy import CHAR, DateTime, Integer, BigInteger
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

UUID_TYPE = CHAR(36).with_variant(mysql.CHAR(36, charset='ascii', collation='ascii_bin'), 'mysql')
TIME_TYPE = DateTime().with_variant(mysql.DATETIME(fsp=6), 'mysql')
UINT_TYPE = Integer().with_variant(mysql.INTEGER(unsigned=True), 'mysql')
UBIGINT_TYPE = BigInteger().with_variant(mysql.BIGINT(unsigned=True), 'mysql')


class CurrentTimestamp6(FunctionElement):
    type = DateTime()
    inherit_cache = True


@compiles(CurrentTimestamp6)
def timestamp_default(element, compiler, **kw):
    return 'CURRENT_TIMESTAMP(6)'


@compiles(CurrentTimestamp6, 'sqlite')
def sqlite_timestamp_default(element, compiler, **kw):
    return 'CURRENT_TIMESTAMP'
