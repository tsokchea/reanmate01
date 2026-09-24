"""Production entry point for a WSGI server.

    gunicorn --worker-class gthread --workers 1 --threads 16 --bind 0.0.0.0:$PORT wsgi:app

One worker process on purpose: rate-limit buckets, tutor stream buffers and
the background job queue live in process memory, exactly as they did in the
single Node process. Scale with threads, not workers, until that state moves
into Postgres.
"""

from app import create_app

app = create_app()
