from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from musicbot.ai import create_provider, create_recognizer
from musicbot.channel import ChannelService
from musicbot.config import load_settings
from musicbot.context import KEY, AppContext
from musicbot.db import Database, Repositories

TOKEN = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
ADMIN = 1001


def make_env(**over):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "ADMIN_USER_ID": str(ADMIN), "CHANNEL_ID": "@bia2music1395"}
    env.update(over)
    return env


@pytest.fixture
def settings():
    return load_settings(make_env(), load_dotenv_file=False)


@pytest.fixture
def db():
    d = Database(":memory:")
    d.migrate()
    yield d
    d.close()


@pytest.fixture
def repos(db):
    r = Repositories(db)
    r.admins.ensure_owner(ADMIN)
    return r


class FakeBot:
    """ربات جعلی که همه فراخوانی‌ها را ثبت می‌کند تا بتوان «فقط‌خواندنی بودن» را بررسی کرد."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(id=-100123, type="channel", title="Bia2Music", username="bia2music1395")
        self.member = SimpleNamespace(status="administrator", can_post_messages=True, can_invite_users=True)

    async def get_chat(self, ref):
        self.calls.append("get_chat")
        if isinstance(self.chat, Exception):
            raise self.chat
        return self.chat

    async def get_chat_member_count(self, chat_id):
        self.calls.append("get_chat_member_count")
        return 22

    async def get_me(self):
        self.calls.append("get_me")
        return SimpleNamespace(id=777, username="testbot")

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append("get_chat_member")
        return self.member


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def app_ctx(settings, repos, bot):
    return AppContext(settings, repos, create_provider(settings), create_recognizer(settings), ChannelService(bot))


def make_update(user_id=ADMIN, text=None, data=None, chat_type="private", audio=None, document=None, from_audio=False):
    """Update جعلی. برای callback، query.edit_message_text ثبت می‌شود."""
    msg = MagicMock()
    msg.text = text
    msg.audio = audio
    msg.document = document
    msg.reply_text = AsyncMock()
    query = None
    if data is not None:
        query = MagicMock()
        query.data = data
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        # from_audio: دکمه از زیر پیام صوتی (پیش‌نمایش) زده شده است
        query.message = SimpleNamespace(audio=object() if from_audio else None, reply_text=AsyncMock())
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username="u", first_name="U", language_code="fa"),
        effective_chat=SimpleNamespace(id=user_id, type=chat_type),
        effective_message=msg,
        callback_query=query,
    )


def make_context(app_ctx, data=b"audio-bytes"):
    tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=tg_file)
    bot.send_audio = AsyncMock(return_value=SimpleNamespace(message_id=55))
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    bot.send_invoice = AsyncMock()
    bot.refund_star_payment = AsyncMock(return_value=True)
    bot.send_document = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.create_chat_invite_link = AsyncMock(return_value=SimpleNamespace(invite_link="https://t.me/+AbC123"))
    bot.revoke_chat_invite_link = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.get_chat_member_count = AsyncMock(return_value=40)
    application = SimpleNamespace(bot_data={KEY: app_ctx}, bot=bot)
    return SimpleNamespace(application=application, user_data={}, bot=bot, error=None)
