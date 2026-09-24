"""A small, zod-compatible request validator.

The Express server validated every request with zod v4, and the frontend reads
the resulting 422 ``details`` — ``[{path, code, message}]`` — to put a message
under the right field (client/src/lib/api.js, toFormError). Pydantic's error
shapes and semantics differ in ways the UI would notice (trim-before-min,
strict objects that name the unknown key, custom per-field messages, defaults
applied only to missing keys), so this module reproduces the subset of zod the
schemas use, with zod's issue codes and default English messages.

Usage mirrors zod::

    body = obj({
        "title": string().trim().min(1, "Give the kit a name").max(200),
        "folderId": uuid().nullable().optional(),
    })
    data = body.parse(payload)   # raises ValidationError

``MISSING`` stands for JavaScript's ``undefined`` (an absent key). Optional
keys that are absent are left out of the parsed output, as zod does.
"""

import copy
import json
import re

from .js import is_integer, is_number, js_trim


class _Missing:
    def __repr__(self):
        return "MISSING"

    def __bool__(self):
        return False


MISSING = _Missing()


class ValidationError(Exception):
    def __init__(self, issues):
        super().__init__("Request validation failed")
        self.issues = issues

    def details(self):
        return [
            {"path": ".".join(str(part) for part in issue["path"]), "code": issue["code"], "message": issue["message"]}
            for issue in self.issues
        ]


def _received(value):
    if value is MISSING:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "NaN" if value != value else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _stringify(value):
    return json.dumps(value, ensure_ascii=False)


class _Ctx:
    def __init__(self):
        self.issues = []

    def add(self, path, code, message):
        self.issues.append({"path": list(path), "code": code, "message": message})

    def invalid_type(self, path, expected, value):
        self.add(path, "invalid_type", f"Invalid input: expected {expected}, received {_received(value)}")


class Schema:
    def parse(self, value):
        ctx = _Ctx()
        out = self._run(value, [], ctx)
        if ctx.issues:
            raise ValidationError(ctx.issues)
        return out

    def safe_parse(self, value):
        try:
            return True, self.parse(value)
        except ValidationError as err:
            return False, err

    def _run(self, value, path, ctx):  # pragma: no cover - abstract
        raise NotImplementedError

    # --- wrappers ---------------------------------------------------------
    def optional(self):
        return _Optional(self)

    def nullable(self):
        return _Nullable(self)

    def default(self, value):
        return _Default(self, value)

    def refine(self, check, message="Invalid input", path=None):
        return _Refine(self, check, message, path or [])

    def transform(self, fn):
        return _Transform(self, fn)

    def pipe(self, other):
        return _Pipe(self, other)


class _Optional(Schema):
    def __init__(self, inner):
        self.inner = inner

    def _run(self, value, path, ctx):
        if value is MISSING:
            return MISSING
        return self.inner._run(value, path, ctx)


class _Nullable(Schema):
    def __init__(self, inner):
        self.inner = inner

    def _run(self, value, path, ctx):
        if value is None:
            return None
        return self.inner._run(value, path, ctx)


class _Default(Schema):
    def __init__(self, inner, value):
        self.inner = inner
        self.value = value

    def _run(self, value, path, ctx):
        if value is MISSING:
            return copy.deepcopy(self.value)
        return self.inner._run(value, path, ctx)


class _Refine(Schema):
    def __init__(self, inner, check, message, extra_path):
        self.inner, self.check, self.message, self.extra_path = inner, check, message, extra_path

    def _run(self, value, path, ctx):
        before = len(ctx.issues)
        out = self.inner._run(value, path, ctx)
        if len(ctx.issues) == before and out is not MISSING and not self.check(out):
            ctx.add(path + self.extra_path, "custom", self.message)
        return out


class _Transform(Schema):
    def __init__(self, inner, fn):
        self.inner, self.fn = inner, fn

    def _run(self, value, path, ctx):
        before = len(ctx.issues)
        out = self.inner._run(value, path, ctx)
        if len(ctx.issues) == before and out is not MISSING:
            return self.fn(out)
        return out


class _Pipe(Schema):
    def __init__(self, first, second):
        self.first, self.second = first, second

    def _run(self, value, path, ctx):
        before = len(ctx.issues)
        out = self.first._run(value, path, ctx)
        if len(ctx.issues) != before:
            return out
        return self.second._run(out, path, ctx)


class preprocess(Schema):
    def __init__(self, fn, inner):
        self.fn, self.inner = fn, inner

    def _run(self, value, path, ctx):
        return self.inner._run(self.fn(value), path, ctx)


# --- primitives -----------------------------------------------------------

# zod v4's RFC 9562 UUID pattern (versions 1-8, plus the nil and max UUIDs).
_UUID = re.compile(
    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
    r"|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$"
)
_EMAIL = re.compile(
    r"^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$"
)
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z$")


class string(Schema):
    def __init__(self):
        self.checks = []

    def _with(self, check):
        clone = string()
        clone.checks = [*self.checks, check]
        return clone

    def trim(self):
        return self._with(("map", js_trim))

    def lower(self):
        return self._with(("map", str.lower))

    def upper(self):
        return self._with(("map", str.upper))

    def min(self, n, message=None):
        return self._with(("check", lambda v: len(v) >= n, "too_small",
                           message or f"Too small: expected string to have >={n} characters"))

    def max(self, n, message=None):
        return self._with(("check", lambda v: len(v) <= n, "too_big",
                           message or f"Too big: expected string to have <={n} characters"))

    def format(self, pattern, message):
        return self._with(("check", lambda v: bool(pattern.match(v)), "invalid_format", message))

    def _run(self, value, path, ctx):
        if not isinstance(value, str):
            ctx.invalid_type(path, "string", value)
            return value
        for check in self.checks:
            if check[0] == "map":
                value = check[1](value)
            elif not check[1](value):
                ctx.add(path, check[2], check[3])
        return value


def uuid(message=None):
    return string().format(_UUID, message or "Invalid UUID")


def email(message=None):
    return string().format(_EMAIL, message or "Invalid email address")


def iso_datetime(message=None):
    return string().format(_ISO_DATETIME, message or "Invalid ISO datetime")


class number(Schema):
    def __init__(self, coerce=False):
        self.coerce = coerce
        self.checks = []

    def _with(self, check):
        clone = number(self.coerce)
        clone.checks = [*self.checks, check]
        return clone

    def int(self):
        return self._with(("int",))

    def min(self, n, message=None):
        return self._with(("check", lambda v: v >= n, "too_small", message or f"Too small: expected number to be >={n}"))

    def max(self, n, message=None):
        return self._with(("check", lambda v: v <= n, "too_big", message or f"Too big: expected number to be <={n}"))

    def positive(self):
        return self._with(("check", lambda v: v > 0, "too_small", "Too small: expected number to be >0"))

    def nonnegative(self):
        return self.min(0)

    @staticmethod
    def _coerce(value):
        """Number(value)."""
        if is_number(value):
            return value
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return 0
        if isinstance(value, str):
            text = value.strip()
            if text == "":
                return 0
            try:
                return float(text) if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", text) else float("nan")
            except ValueError:
                return float("nan")
        return float("nan")

    def _run(self, value, path, ctx):
        if self.coerce:
            value = self._coerce(value)
        if not is_number(value) or value != value:
            ctx.invalid_type(path, "number", value)
            return value
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        for check in self.checks:
            if check[0] == "int":
                if not is_integer(value):
                    ctx.invalid_type(path, "int", value)
                    return value
            elif not check[1](value):
                ctx.add(path, check[2], check[3])
        return value


class boolean(Schema):
    def _run(self, value, path, ctx):
        if not isinstance(value, bool):
            ctx.invalid_type(path, "boolean", value)
        return value


class null_value(Schema):
    """z.null()."""

    def _run(self, value, path, ctx):
        if value is not None:
            ctx.invalid_type(path, "null", value)
        return value


class enum(Schema):
    def __init__(self, values):
        self.values = list(values)

    def _run(self, value, path, ctx):
        if not isinstance(value, str) or value not in self.values:
            ctx.add(path, "invalid_value",
                    "Invalid option: expected one of " + "|".join(_stringify(v) for v in self.values))
        return value


class literal(Schema):
    def __init__(self, value):
        self.value = value

    def _run(self, value, path, ctx):
        if value != self.value or type(value) is not type(self.value):
            ctx.add(path, "invalid_value", f"Invalid input: expected {_stringify(self.value)}")
        return value


# --- composites -----------------------------------------------------------


class array(Schema):
    def __init__(self, item):
        self.item = item
        self.checks = []

    def _with(self, check):
        clone = array(self.item)
        clone.checks = [*self.checks, check]
        return clone

    def min(self, n):
        return self._with((lambda v: len(v) >= n, "too_small", f"Too small: expected array to have >={n} items"))

    def max(self, n):
        return self._with((lambda v: len(v) <= n, "too_big", f"Too big: expected array to have <={n} items"))

    def _run(self, value, path, ctx):
        if not isinstance(value, list):
            ctx.invalid_type(path, "array", value)
            return value
        out = [self.item._run(item, [*path, index], ctx) for index, item in enumerate(value)]
        for check, code, message in self.checks:
            if not check(out):
                ctx.add(path, code, message)
        return out


class obj(Schema):
    """z.object (strips unknown keys) or, with strict=True, z.strictObject."""

    def __init__(self, shape, strict=False):
        self.shape = shape
        self.is_strict = strict

    def _run(self, value, path, ctx):
        if not isinstance(value, dict):
            ctx.invalid_type(path, "object", value)
            return value
        out = {}
        for key, schema in self.shape.items():
            parsed = schema._run(value.get(key, MISSING), [*path, key], ctx)
            if parsed is not MISSING:
                out[key] = parsed
        if self.is_strict:
            unknown = [key for key in value if key not in self.shape]
            if unknown:
                noun = "keys" if len(unknown) > 1 else "key"
                ctx.add(path, "unrecognized_keys",
                        f"Unrecognized {noun}: " + ", ".join(_stringify(k) for k in unknown))
        return out


def strict_obj(shape):
    return obj(shape, strict=True)


class record(Schema):
    def __init__(self, key, value):
        self.key, self.value = key, value

    def _run(self, value, path, ctx):
        if not isinstance(value, dict):
            ctx.invalid_type(path, "record", value)
            return value
        out = {}
        for key, item in value.items():
            key_ctx = _Ctx()
            parsed_key = self.key._run(key, [], key_ctx)
            if key_ctx.issues:
                ctx.add([*path, key], "invalid_key", "Invalid key in record")
                continue
            out[parsed_key] = self.value._run(item, [*path, key], ctx)
        return out


class union(Schema):
    def __init__(self, options):
        self.options = options

    def _run(self, value, path, ctx):
        for option in self.options:
            trial = _Ctx()
            out = option._run(value, path, trial)
            if not trial.issues:
                return out
        ctx.add(path, "invalid_union", "Invalid input")
        return value


class discriminated_union(Schema):
    def __init__(self, key, options):
        self.key = key
        self.options = options  # {discriminator value: schema}

    def _run(self, value, path, ctx):
        if not isinstance(value, dict):
            ctx.invalid_type(path, "object", value)
            return value
        option = self.options.get(value.get(self.key)) if isinstance(value.get(self.key), str) else None
        if option is None:
            ctx.add([*path, self.key], "invalid_union", "Invalid input")
            return value
        return option._run(value, path, ctx)


class any_value(Schema):
    def _run(self, value, path, ctx):
        return value
