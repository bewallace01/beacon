"""Programmatic alembic upgrade.

Called from FastAPI startup so the backend container brings the schema up to
head every time it boots. Uses the same alembic.ini that the alembic CLI
would use.
"""
import os

from alembic import command
from alembic.config import Config


def _config() -> Config:
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    return cfg


def upgrade_to_head() -> None:
    command.upgrade(_config(), "head")
