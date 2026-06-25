"""Application configuration."""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # trainer.db lives in the project root (~/trainer/trainer.db on the Pi)
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "trainer.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
