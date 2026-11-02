import logging
import time

from sqlalchemy import select

from b2m.core import tokens
from b2m.db import models as M
from tests.conftest import ADMIN, TOKEN, init_data, login


def test_login_creates_user_and_prefs(client, db):
    body, h = login(client, uid=42, first="Ali", lang="fa")
    assert body["user"]["language"] == "fa" and body["user"]["is_admin"] is False and body["user"]["points"] == 0
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert db.scalar(select(M.User).where(M.User.telegram_id == 42)).first_name == "Ali"
    assert db.get(M.UserPreference, body["user"]["id"]).match_opt_in is False          # Music Match: پیش‌فرض عدم عضویت
    assert client.get("/api/me", headers=h).json()["first_name"] == "Ali"


def test_login_is_idempotent_and_keeps_language_choice(client, db):
    b1, h = login(client, uid=42, lang="fa")
    assert client.patch("/api/me", json={"language": "en"}, headers=h).json()["language"] == "en"
    b2, _ = login(client, uid=42, lang="fa", first="Ali2")
    assert b1["user"]["id"] == b2["user"]["id"] and b2["user"]["language"] == "en" and b2["user"]["first_name"] == "Ali2"
    assert len(db.scalars(select(M.User)).all()) == 1


def test_language_from_telegram_on_signup(client):
    assert login(client, uid=1, lang="en")[0]["user"]["language"] == "en"
    assert login(client, uid=2, lang="fa-IR")[0]["user"]["language"] == "fa"
    assert login(client, uid=3, lang=None)[0]["user"]["language"] == "fa"                # پیش‌فرض تنظیمات


def test_admin_only_by_admin_user_id(client, db):
    assert login(client, uid=ADMIN)[0]["user"]["is_admin"] is True
    assert db.scalar(select(M.Admin).join(M.User).where(M.User.telegram_id == ADMIN)).role == "owner"
    assert login(client, uid=ADMIN + 1)[0]["user"]["is_admin"] is False


def test_bad_auth_rejected_and_logged_without_payload(client, db, caplog):
    caplog.set_level(logging.DEBUG)
    raw = init_data(token="1:WRONG")
    r = client.post("/api/auth/telegram", json={"init_data": raw})
    assert r.status_code == 401 and r.json() == {"error": "invalid_init_data"}
    assert "hash=" not in caplog.text and raw[:40] not in caplog.text and "Ali" not in caplog.text
    row = db.scalar(select(M.ActivityLog).where(M.ActivityLog.action == "auth_failed"))
    assert row.detail == {"reason": "bad_signature"} and raw not in str(row.detail)


def test_bots_rejected(client):
    import json

    from b2m.core.initdata import sign

    u = json.dumps({"id": 9, "first_name": "B", "is_bot": True})
    raw = sign({"auth_date": str(int(time.time())), "user": u}, TOKEN)
    assert client.post("/api/auth/telegram", json={"init_data": raw}).status_code == 401


def test_request_validation(client):
    for body in ({}, {"init_data": ""}, {"init_data": "x", "extra": 1}, {"init_data": "x" * 9000}, {"init_data": 5}):
        r = client.post("/api/auth/telegram", json=body)
        assert r.status_code == 422 and r.json() == {"error": "invalid_request"}


def test_protected_endpoints_need_valid_token(client, settings):
    for path in ("/api/me", "/api/home"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer junk"}).status_code == 401
        assert client.get(path, headers={"Authorization": "Basic abc"}).status_code == 401
    forged, _ = tokens.issue(1, "other-secret-" + "y" * 40, 10)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired, _ = tokens.issue(1, settings.jwt_secret, -5)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    _, h = login(client)
    client.request("DELETE", "/api/me", json={"confirm": True}, headers=h)
    assert client.get("/api/me", headers=h).status_code == 401                          # توکن کاربر حذف‌شده بی‌اثر است


def test_auth_rate_limit(settings):
    from b2m.core.config import load_settings
    from b2m.db.base import Base
    from b2m.db.session import make_engine
    from b2m.main import create_app
    from fastapi.testclient import TestClient
    from tests.conftest import env

    st = load_settings(env(AUTH_RATE_PER_MINUTE="3"))
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    c = TestClient(create_app(st, eng))
    codes = [c.post("/api/auth/telegram", json={"init_data": "bad"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_delete_account_removes_personal_data(client, db):
    b, h = login(client, uid=50)
    uid = b["user"]["id"]
    db.add(M.UserPoint(user_id=uid, points=5, reason="t", ref_key="k1"))
    db.commit()
    assert client.request("DELETE", "/api/me", json={}, headers=h).status_code == 422             # تأیید صریح لازم است
    assert client.request("DELETE", "/api/me", json={"confirm": True}, headers=h).status_code == 204
    db.expire_all()
    assert db.get(M.User, uid) is None and db.get(M.UserPreference, uid) is None
    assert db.scalar(select(M.UserPoint).where(M.UserPoint.user_id == uid)) is None
    log = db.scalar(select(M.ActivityLog).where(M.ActivityLog.action == "account_deleted"))
    assert log.user_id is None
    assert all(l.user_id != uid for l in db.scalars(select(M.ActivityLog)))             # لاگ‌های قبلی کاربر نیز بی‌هویت شدند
    b2, _ = login(client, uid=50)                                                      # ثبت‌نام دوباره ممکن است
    assert b2["user"]["created_at"]


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.json()["status"] == "ok" and r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


def test_token_with_wrong_issuer_or_alg_rejected(settings):
    import jwt as pyjwt

    from b2m.core.timeutil import utcnow
    from datetime import timedelta

    now = utcnow()
    claims = {"sub": "1", "iat": now, "exp": now + timedelta(minutes=5)}
    assert tokens.verify(pyjwt.encode({**claims, "iss": "someone-else"}, settings.jwt_secret, algorithm="HS256"), settings.jwt_secret) is None
    assert tokens.verify(pyjwt.encode({**claims, "iss": "bia2music"}, settings.jwt_secret, algorithm="HS256"), settings.jwt_secret) == 1
    assert tokens.verify(pyjwt.encode({**claims, "iss": "bia2music"}, settings.jwt_secret, algorithm="HS512"), settings.jwt_secret) is None
    assert tokens.verify(pyjwt.encode({"sub": "1", "iss": "bia2music"}, settings.jwt_secret, algorithm="HS256"), settings.jwt_secret) is None     # بدون exp
