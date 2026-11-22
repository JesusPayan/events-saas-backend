"""Punto de entrada WSGI para producción (gunicorn wsgi:app).

No usar `flask run` ni `main.py` en producción.
"""
from app import create_app

app = create_app()
