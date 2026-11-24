from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
jwt_manager = JWTManager()
# Sin límite global; los endpoints sensibles declaran el suyo.
limiter = Limiter(key_func=get_remote_address, default_limits=[])
