import logging
from logging.config import fileConfig
from flask import current_app
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
fileConfig(config.config_file_name) if config.config_file_name and config.get_section("loggers") else None

def get_engine():
    return current_app.extensions["migrate"].db.engine

def get_metadata():
    return current_app.extensions["migrate"].db.metadata

def run_migrations_offline():
    context.configure(url=str(get_engine().url), target_metadata=get_metadata(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=get_metadata(), compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
