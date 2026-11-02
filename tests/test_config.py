import pytest

from musicbot.config import ConfigError, load_settings
from tests.conftest import make_env


def test_valid_settings():
    s = load_settings(make_env(), load_dotenv_file=False)
    assert s.admin_user_id == 1001 and s.timezone == "Asia/Tehran" and s.ai_provider == "none"
    assert "AAAA" not in repr(s)  # توکن در repr نمی‌آید


@pytest.mark.parametrize("over,frag", [
    ({"TELEGRAM_BOT_TOKEN": ""}, "TELEGRAM_BOT_TOKEN"),
    ({"TELEGRAM_BOT_TOKEN": "put-token-here"}, "فرمت"),
    ({"ADMIN_USER_ID": ""}, "ADMIN_USER_ID"),
    ({"ADMIN_USER_ID": "abc"}, "عدد"),
    ({"ADMIN_USER_ID": "-5"}, "مثبت"),
    ({"TIMEZONE": "Mars/Base"}, "TIMEZONE"),
    ({"LOG_LEVEL": "LOUD"}, "LOG_LEVEL"),
])
def test_invalid(over, frag):
    with pytest.raises(ConfigError) as e:
        load_settings(make_env(**over), load_dotenv_file=False)
    assert frag in str(e.value)


def test_error_never_leaks_token():
    with pytest.raises(ConfigError) as e:
        load_settings(make_env(ADMIN_USER_ID="x"), load_dotenv_file=False)
    assert "AAAA" not in str(e.value)
