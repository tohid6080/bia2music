import json
import time

import pytest
from fastapi.testclient import TestClient

from b2m.core.config import load_settings
from b2m.core.initdata import sign
from b2m.db import models as M  # noqa: F401
from b2m.db.base import Base
from b2m.db.session import make_engine, make_session_factory
from b2m.main import create_app

TOKEN = "123456789:TEST_TOKEN_NOT_REAL_xxxxxxxxxxxxxxxxxxx"
ADMIN = 777001


def env(**over):
    base = {"APP_ENV": "test", "BOT_TOKEN": TOKEN, "ADMIN_USER_ID": str(ADMIN), "JWT_SECRET": "x" * 48, "DATABASE_URL": "sqlite://",
            "WEBAPP_URL": "https://example.test", "SERVE_WEBAPP": "0"}
    base.update(over)
    return base


def init_data(uid=42, first="Ali", lang="fa", username="ali_u", token=TOKEN, auth_date=None, **extra):
    user = {"id": uid, "first_name": first, "username": username, "language_code": lang}
    f = {"auth_date": str(int(time.time()) if auth_date is None else auth_date), "query_id": "AAA", "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False)}
    f.update(extra)
    return sign(f, token)


@pytest.fixture
def settings():
    return load_settings(env())


@pytest.fixture
def app(settings):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return create_app(settings, engine)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def db(app):
    with app.state.session_factory() as s:
        yield s


def login(client, **kw):
    r = client.post("/api/auth/telegram", json={"init_data": init_data(**kw)})
    assert r.status_code == 200, r.text
    return r.json(), {"Authorization": "Bearer " + r.json()["access_token"]}
