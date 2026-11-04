import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-not-for-production")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "mysql:///local.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False
