import json
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from b2m.core.initdata import InitDataError, validate_init_data
from tests.conftest import TOKEN, init_data

AGE = 3600


def code(fn):
    with pytest.raises(InitDataError) as e:
        fn()
    return e.value.code


def test_valid_roundtrip():
    u = validate_init_data(init_data(uid=5, first="سارا", lang="fa"), TOKEN, AGE)
    assert (u.id, u.first_name, u.username, u.language_code) == (5, "سارا", "ali_u", "fa")


def test_known_vector():
    """بردار مستقل: با پیاده‌سازی مرجع (hmac دستی) ساخته شده، نه با تابع sign پروژه."""
    import hashlib
    import hmac

    fields = {"auth_date": "1700000000", "user": '{"id":1,"first_name":"A"}'}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    assert validate_init_data(urlencode({**fields, "hash": h}), TOKEN, 10**9, now=1700000100).id == 1


def test_tampered_fields_rejected():
    raw = init_data(uid=42)
    pairs = dict(parse_qsl(raw))
    pairs["user"] = json.dumps({"id": 999, "first_name": "Evil"})
    assert code(lambda: validate_init_data(urlencode(pairs), TOKEN, AGE)) == "bad_signature"


def test_wrong_token_and_missing_hash_and_garbage():
    assert code(lambda: validate_init_data(init_data(), "999:OTHER", AGE)) == "bad_signature"
    no_hash = urlencode({k: v for k, v in parse_qsl(init_data()) if k != "hash"})
    assert code(lambda: validate_init_data(no_hash, TOKEN, AGE)) == "missing_hash"
    for bad in ("", "x", "a=1&a=2&hash=00", "%%%", "k" * 9000, None, 5):
        assert code(lambda b=bad: validate_init_data(b, TOKEN, AGE)) in ("malformed", "missing_hash")


def test_duplicate_fields_rejected():
    assert code(lambda: validate_init_data(init_data() + "&auth_date=1", TOKEN, AGE)) == "malformed"


def test_expiry_and_future():
    assert code(lambda: validate_init_data(init_data(auth_date=int(time.time()) - 7200), TOKEN, AGE)) == "expired"
    assert code(lambda: validate_init_data(init_data(auth_date=int(time.time()) + 3600), TOKEN, AGE)) == "auth_date_in_future"
    assert validate_init_data(init_data(auth_date=int(time.time()) - 3000), TOKEN, AGE)


def test_user_field_validation():
    for user in ('{"first_name":"x"}', "notjson", '{"id":"12"}', '{"id":-4}', '{"id":true}', "[]"):
        from b2m.core.initdata import sign

        raw = sign({"auth_date": str(int(time.time())), "user": user}, TOKEN)
        assert code(lambda r=raw: validate_init_data(r, TOKEN, AGE)) == "no_user"


def test_error_never_echoes_input():
    secretish = "SECRET_PAYLOAD_VALUE"
    try:
        validate_init_data(f"user={secretish}&hash=abc", TOKEN, AGE)
    except InitDataError as e:
        assert secretish not in str(e) and secretish not in repr(e.args)
