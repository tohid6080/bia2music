from alembic import context
from sqlalchemy import create_engine

from b2m.core.config import load_settings
from b2m.db import models  # noqa: F401
from b2m.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    return context.config.attributes.get("url") or load_settings(require_bot_token=False).database_url


def run() -> None:
    url = _url()
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    from b2m.db.session import make_engine

    engine = make_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
