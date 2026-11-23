"""Entry point for gunicorn: `gunicorn examprep.wsgi:app`."""
from .app import create_app

app = create_app()
