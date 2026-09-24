"""JSON output that matches what Express's res.json() produced.

The frontend was written against JSON.stringify of node-postgres rows, so a few
details matter beyond "valid JSON":

- Dates are ISO-8601 in UTC with millisecond precision: 2026-09-24T03:15:00.123Z
- Integral floats print as integers (JS has one number type: 3, not 3.0)
- Keys whose value is ``UNDEFINED`` are omitted, as JSON.stringify drops
  ``undefined`` — used where the Node code read a column the row did not have
- Key order is preserved, never sorted
"""

import datetime as dt
import decimal
import json
import math
import uuid

from flask.json.provider import DefaultJSONProvider


class _Undefined:
    """JavaScript's ``undefined``: a value that disappears from JSON objects."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self):
        return False

    def __repr__(self):
        return "UNDEFINED"


UNDEFINED = _Undefined()


def iso(value):
    """Date.prototype.toISOString()."""
    if value.tzinfo is None:
        value = value.astimezone()  # node-pg reads zone-less values as local time
    value = value.astimezone(dt.timezone.utc)
    return f"{value:%Y-%m-%dT%H:%M:%S}.{value.microsecond // 1000:03d}Z"


def to_jsonable(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value) if value.is_integer() and abs(value) < 2**53 else value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items() if v is not UNDEFINED}
    if isinstance(value, (list, tuple)):
        return [None if item is UNDEFINED else to_jsonable(item) for item in value]
    if isinstance(value, dt.datetime):
        return iso(value)
    if isinstance(value, dt.date):
        return iso(dt.datetime(value.year, value.month, value.day))
    if isinstance(value, decimal.Decimal):
        return to_jsonable(float(value))
    if isinstance(value, uuid.UUID):
        return str(value)
    if value is UNDEFINED:
        return None
    return str(value)


def dumps(value):
    return json.dumps(to_jsonable(value), ensure_ascii=False, separators=(",", ":"))


class ExpressJSONProvider(DefaultJSONProvider):
    sort_keys = False
    ensure_ascii = False
    compact = True

    def dumps(self, obj, **kwargs):
        return dumps(obj)
