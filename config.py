
import os


class Config:
    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        "dev-only-not-for-production"
    )

    SQLALCHEMY_DATABASE_URI = (
        os.getenv("DATABASE_URL")
        or os.getenv("DB_URL_DEV")
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JSON_SORT_KEYS = False

    TOKEN_MAX_AGE = 3600

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_timeout": 10,
        "connect_args": {
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
        }
    }


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False

    @staticmethod
    def validate():
        if not os.getenv("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY es obligatorio en producción."
            )
