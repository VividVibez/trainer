"""Shared extension instances.

Kept separate from the app factory so models and seed scripts can import
`db` without triggering a circular import on `app`.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
