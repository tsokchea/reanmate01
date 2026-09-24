"""Request schemas for the admin console and the self-service password change.

Bodies that change access (accounts, roles, limits, settings) are strict: an
unknown key is a 422, never silently dropped — so a client cannot slip a
``role`` or ``status`` past a form that does not offer it.
"""

import re

from ..utils.schema import (
    MISSING,
    array,
    boolean,
    enum,
    iso_datetime,
    number,
    obj,
    preprocess,
    strict_obj,
    string,
    uuid,
)
from .schemas import MIN_PASSWORD, _email, _optional_phone

_PERMISSION_KEY = string().trim().format(re.compile(r"^[a-z]+\.[a-z_]+$"), "Not a valid permission")
_PERMISSIONS = array(_PERMISSION_KEY).max(100)
_PASSWORD = string().min(MIN_PASSWORD, f"Use at least {MIN_PASSWORD} characters").max(200)
_NAME = string().trim().min(1, "Enter a name").max(120)

# Blank query values mean "no filter", the same as leaving them out.
_blank_to_missing = lambda schema: preprocess(  # noqa: E731
    lambda value: MISSING if isinstance(value, str) and value.strip() == "" else value, schema)

_PAGING = {
    "page": _blank_to_missing(number(coerce=True).int().min(1).max(100_000).optional()),
    "pageSize": _blank_to_missing(number(coerce=True).int().min(1).max(100).optional()),
    "q": _blank_to_missing(string().trim().max(200).optional()),
}

# --- params ------------------------------------------------------------------------------

user_params = obj({"userId": uuid("Not a valid id")})
role_params = obj({"roleId": uuid("Not a valid id")})
source_params = obj({"sourceId": uuid("Not a valid id")})
assignment_params = obj({"assignmentId": uuid("Not a valid id")})
flashcard_set_params = obj({"setId": uuid("Not a valid id")})

# --- queries -----------------------------------------------------------------------------

page_query = obj(dict(_PAGING))

users_query = obj({
    **_PAGING,
    "tab": _blank_to_missing(enum(["all", "students", "teachers", "admins", "disabled"]).default("all")),
    "status": _blank_to_missing(enum(["active", "disabled"]).optional()),
    "sort": _blank_to_missing(enum(["created", "name", "lastLogin", "aiUsage"]).optional()),
})

usage_query = obj({
    **_PAGING,
    "kind": _blank_to_missing(enum(["student", "teacher", "admin", "super_admin"]).optional()),
})

series_query = obj({"range": _blank_to_missing(enum(["today", "7d", "30d", "90d"]).default("7d"))})

content_query = obj({
    **_PAGING,
    "kind": _blank_to_missing(enum(["pdf", "image", "youtube", "link", "topic", "text", "document"]).optional()),
})

audit_query = obj({
    **_PAGING,
    "from": _blank_to_missing(iso_datetime().optional()),
    "to": _blank_to_missing(iso_datetime().optional()),
    "actor": _blank_to_missing(string().trim().max(200).optional()),
    "actorId": _blank_to_missing(uuid("Not a valid id").optional()),
    "action": _blank_to_missing(string().trim().format(re.compile(r"^[A-Z_]{1,64}$"), "Not a valid action").optional()),
    "target": _blank_to_missing(string().trim().max(200).optional()),
    "targetId": _blank_to_missing(uuid("Not a valid id").optional()),
})

# --- limits ------------------------------------------------------------------------------

# null clears an account override (inherit the role default) or, on a role, means "no limit".
_LIMIT = number().int().min(0).max(10**15).nullable().optional()

limits_body = strict_obj({
    field: _LIMIT for field in (
        "dailyAiTokens", "monthlyAiTokens", "dailyPdfUploads", "monthlyPdfUploads", "dailyAssignments",
        "monthlyAssignments", "dailyFlashcards", "monthlyFlashcards", "dailyTutorMessages", "monthlyTutorMessages",
        "dailyFileStorageBytes", "monthlyFileStorageBytes",
    )
})

# --- accounts ----------------------------------------------------------------------------

create_user_body = strict_obj({
    "fullName": _NAME,
    "email": _email.optional(),
    "phone": _optional_phone,
    "role": enum(["student", "teacher"]),
    "temporaryPassword": _PASSWORD.optional(),
    "locale": enum(["km", "en"]).optional(),
}).refine(lambda data: bool(data.get("email") or data.get("phone")),
          "Provide an email address or a phone number", ["email"])

update_user_body = strict_obj({
    "fullName": _NAME.optional(),
    "email": _email.optional(),
    "phone": _optional_phone,
    "role": enum(["student", "teacher"]).optional(),
})

create_admin_body = strict_obj({
    "fullName": _NAME,
    "email": _email,
    "temporaryPassword": _PASSWORD.optional(),
    "roleId": uuid("Choose a role"),
    "status": enum(["active", "disabled"]).default("active"),
    "permissions": _PERMISSIONS.default([]),
    "limits": limits_body.optional(),
    "locale": enum(["km", "en"]).optional(),
})

update_admin_body = strict_obj({
    "fullName": _NAME.optional(),
    "email": _email.optional(),
    "roleId": uuid("Choose a role").optional(),
    "permissions": _PERMISSIONS.optional(),
})

# --- roles -------------------------------------------------------------------------------

_ROLE_KEY = string().trim().upper().format(re.compile(r"^[A-Z][A-Z0-9_]{1,63}$"),
                                           "Use capital letters, digits and underscores")

create_role_body = strict_obj({
    "name": string().trim().min(1, "Give the role a name").max(80),
    "key": _ROLE_KEY.optional(),
    "description": string().trim().max(300).nullable().optional(),
    "permissions": _PERMISSIONS.default([]),
})

update_role_body = strict_obj({
    "name": string().trim().min(1, "Give the role a name").max(80).optional(),
    "description": string().trim().max(300).nullable().optional(),
    "permissions": _PERMISSIONS.optional(),
})

# --- settings ----------------------------------------------------------------------------

settings_body = strict_obj({
    "usageLimitsEnabled": boolean().optional(),
    "signupsEnabled": boolean().optional(),
})

# --- self service ------------------------------------------------------------------------

change_password_body = obj({
    "currentPassword": string().min(1, "Enter your current password"),
    "newPassword": _PASSWORD,
})
