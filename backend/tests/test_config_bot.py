import pytest

from b2m.core.config import ConfigError, load_settings
from tests.conftest import ADMIN, env


def test_config_errors_are_clear():
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        load_settings(env(BOT_TOKEN=""))
    with pytest.raises(ConfigError, match="https"):
        load_settings(env(WEBAPP_URL="http://example.com"))
    with pytest.raises(ConfigError, match="JWT_SECRET"):
        load_settings(env(APP_ENV="production", JWT_SECRET=""))
    with pytest.raises(ConfigError, match="۳۲"):
        load_settings(env(APP_ENV="production", JWT_SECRET="short"))
    with pytest.raises(ConfigError, match="ADMIN_USER_ID"):
        load_settings(env(ADMIN_USER_ID="@name"))
    with pytest.raises(ConfigError):
        load_settings(env(APP_ENV="staging"))
    assert load_settings(env(DATABASE_URL="postgres://u:p@h/db")).database_url.startswith("postgresql+psycopg://")


def test_dev_generates_temporary_jwt_secret():
    st = load_settings(env(JWT_SECRET="", APP_ENV="development"))
    assert len(st.jwt_secret) >= 32


# ---------- ربات ----------
from types import SimpleNamespace
from unittest.mock import AsyncMock

from b2m.bot import app as bot


def upd(uid, chat_type="private", lang="fa"):
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid, language_code=lang), effective_chat=SimpleNamespace(type=chat_type), effective_message=msg), msg


def ctx(settings):
    from b2m.db.base import Base
    from b2m.db.session import make_engine, make_session_factory

    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings, "sf": make_session_factory(eng)}))


async def test_start_has_webapp_button():
    st = load_settings(env())
    u, msg = upd(5)
    await bot.start(u, ctx(st))
    kb = msg.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert kb.web_app.url == "https://example.test" and "Bia2Music" in msg.reply_text.call_args.args[0]


async def test_start_english_and_group_and_no_url():
    st = load_settings(env())
    u, msg = upd(5, lang="en")
    await bot.start(u, ctx(st))
    assert "Welcome" in msg.reply_text.call_args.args[0]
    u, msg = upd(5, chat_type="group")
    await bot.start(u, ctx(st))
    assert "reply_markup" not in msg.reply_text.call_args.kwargs
    u, msg = upd(5)
    await bot.start(u, ctx(load_settings(env(WEBAPP_URL=""))))
    assert "WEBAPP_URL" in msg.reply_text.call_args.args[0] and "reply_markup" not in msg.reply_text.call_args.kwargs


async def test_admin_command_only_for_admin():
    st = load_settings(env())
    c = ctx(st)
    u, msg = upd(ADMIN + 1)
    await bot.admin(u, c)
    assert "فقط برای مدیر" in msg.reply_text.call_args.args[0]
    u, msg = upd(ADMIN)
    await bot.admin(u, c)
    assert "آمار Bia2Music" in msg.reply_text.call_args.args[0]


def test_no_secret_logging_config():
    import inspect

    from b2m.bot import __main__ as m

    assert 'getLogger("httpx").setLevel(logging.WARNING)' in inspect.getsource(m)
