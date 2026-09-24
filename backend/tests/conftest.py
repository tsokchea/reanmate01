"""Test configuration: a throwaway SQLite database and upload folder per test run.

The environment is set before anything from ``app`` is imported, because
configuration is read once at import time.
"""

import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="reanmate-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db").replace("\\", "/")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long"
os.environ.pop("OPENAI_API_KEY", None)  # always the mock provider under test

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from app import create_app
    from app.extensions import close_connection
    from scripts.migrate import run_migrations

    run_migrations()
    close_connection()
    application = create_app()
    application.testing = True
    yield application
    close_connection()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
