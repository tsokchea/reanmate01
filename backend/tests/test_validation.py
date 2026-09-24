"""The 422 contract: the zod-compatible validator produces the paths and messages the UI renders."""

import pytest

from app.utils.schema import MISSING, ValidationError
from app.validation import schemas as s


def details(schema, value):
    with pytest.raises(ValidationError) as err:
        schema.parse(value)
    return err.value.details()


def test_register_messages_the_form_renders():
    issues = details(s.register_schema, {"fullName": " ", "password": "short", "role": "student"})
    by_path = {i["path"]: i for i in issues}
    assert by_path["fullName"]["message"] == "Enter your name"
    assert by_path["password"] == {"path": "password", "code": "too_small", "message": "Use at least 8 characters"}


def test_register_needs_email_or_phone():
    issues = details(s.register_schema, {"fullName": "A", "password": "longenough", "role": "student", "phone": ""})
    assert issues == [{"path": "email", "code": "custom", "message": "Provide an email address or a phone number"}]


def test_register_normalises_email_and_phone():
    parsed = s.register_schema.parse({"fullName": " Sok ", "email": " Sok@Example.COM ", "phone": "012-345 (678)",
                                      "password": "longenough", "role": "teacher"})
    assert parsed == {"fullName": "Sok", "email": "sok@example.com", "phone": "012345678",
                      "password": "longenough", "role": "teacher"}
    assert details(s.register_schema, {"fullName": "A", "email": "nope", "password": "longenough",
                                       "role": "student"})[0]["message"] == "Enter a valid email address"


def test_strict_objects_name_the_unknown_key():
    issues = details(s.survey_schema, {"answers": {"improvFirst": "remember"}})
    assert issues == [{"path": "answers", "code": "unrecognized_keys", "message": 'Unrecognized key: "improvFirst"'}]


def test_defaults_and_missing_keys():
    assert s.survey_schema.parse({}) == {"answers": {}, "skipped": False, "complete": False}
    # Optional keys that are absent stay absent (the PATCH "at least one field" refine relies on it).
    assert details(s.update_kit_schema, {}) == [{"path": "", "code": "custom",
                                                 "message": "Send at least one field to update"}]
    assert s.update_kit_schema.parse({"folderId": None}) == {"folderId": None}


def test_undefined_body_is_invalid_type():
    assert details(s.login_schema, MISSING) == [
        {"path": "", "code": "invalid_type", "message": "Invalid input: expected object, received undefined"}]


def test_uuid_enum_and_number_messages():
    assert details(s.kit_id_params, {"kitId": "nope"})[0] == {"path": "kitId", "code": "invalid_format",
                                                               "message": "Not a valid id"}
    assert details(s.summarize_body, {"language": "fr"})[0]["message"] == 'Invalid option: expected one of "km"|"en"'
    assert details(s.review_flashcard_body, {"quality": 7})[0] == {
        "path": "quality", "code": "too_big", "message": "Too big: expected number to be <=5"}
    assert details(s.review_flashcard_body, {"quality": 2.5})[0]["message"] == \
        "Invalid input: expected int, received number"


def test_coerced_query_numbers():
    assert s.due_flashcards_query.parse({}) == {"limit": 20}
    assert s.due_flashcards_query.parse({"limit": "5"}) == {"limit": 5}
    assert details(s.due_flashcards_query, {"limit": "abc"})[0]["message"] == \
        "Invalid input: expected number, received NaN"


def test_discriminated_union_and_nested_paths():
    assert s.create_source_schema.parse({"kind": "topic", "title": " Cells "}) == {"kind": "topic", "title": "Cells"}
    assert details(s.create_source_schema, {"kind": "pdf"})[0] == {"path": "kind", "code": "invalid_union",
                                                                   "message": "Invalid input"}
    issues = details(s.create_lesson_body, {"weekNumber": 1, "title": "L", "items": [{"title": ""}]})
    assert issues[0]["path"] == "items.0.title"


def test_join_code_uppercased_and_record_keys():
    assert s.join_class_body.parse({"code": " ab12cd "}) == {"code": "AB12CD"}
    issues = details(s.save_submission_body, {"answers": {"not-a-uuid": 1}})
    assert issues[0] == {"path": "answers.not-a-uuid", "code": "invalid_key", "message": "Invalid key in record"}
