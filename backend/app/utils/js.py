"""Small JavaScript-semantics helpers.

The Node services leaned on a few JS behaviours that Python spells
differently; keeping them here stops a silent drift in results. The obvious
one is rounding: Python's round() is banker's rounding (round(2.5) == 2),
Math.round is half-up (Math.round(2.5) === 3), and mastery percentages are
computed with it.
"""

import math
import re
import time
import unicodedata


# String.prototype.trim's set: WhiteSpace plus LineTerminator, which (unlike
# Python's str.strip) includes the byte-order mark.
_JS_WHITESPACE = " \t\n\v\f\r                 　﻿"


def js_trim(value):
    return value.strip(_JS_WHITESPACE)


def parse_float(value):
    """Number.parseFloat: the longest leading decimal literal, else NaN."""
    match = re.match(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)", str(value) if value is not None else "")
    return float(match.group(1)) if match else float("nan")


def js_round(value):
    """Math.round: half-way cases round towards +infinity."""
    return math.floor(value + 0.5)


def now_ms():
    """Date.now()."""
    return int(time.time() * 1000)


def parse_int(value, default=None):
    """Number.parseInt(value, 10): leading digits, else ``default`` (JS NaN)."""
    match = re.match(r"^\s*([+-]?\d+)", str(value) if value is not None else "")
    return int(match.group(1)) if match else default


def is_integer(value):
    """Number.isInteger — booleans are not numbers in JS."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_option(value):
    """value.normalize('NFKC').trim().replace(/\\s+/g, ' ').toLocaleLowerCase('und')"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).lower()


def js_string(value):
    """String(value) for the primitive types a JSON body can carry."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
