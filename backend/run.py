"""Development entry point: ``python run.py``.

Uses Flask's threaded development server, which streams the tutor's SSE
responses as they are produced. For production use wsgi.py with gunicorn
(see README.md).
"""

import os

from app import create_app
from app.config import config

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"[server] ReanMate API listening on http://localhost:{config.PORT} ({config.NODE_ENV})")
    print(f"[server] CORS origins: {', '.join(config.CORS_ORIGINS)}")
    app.run(host=host, port=config.PORT, debug=config.NODE_ENV != "production", threaded=True, use_reloader=True)
