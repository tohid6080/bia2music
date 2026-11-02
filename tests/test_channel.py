import pytest
from telegram.error import BadRequest, Forbidden

from musicbot.channel import InvalidChannelRef, normalize_channel_ref

@pytest.mark.parametrize("raw,exp", [
    ("@bia2music1395", "@bia2music1395"),
    ("https://t.me/bia2music1395", "@bia2music1395"),
    ("t.me/bia2music1395/", "@bia2music1395"),
    ("bia2music1395", "@bia2music1395"),
    ("-1001234567890", "-1001234567890"),
])
def test_normalize(raw, exp):
    assert normalize_channel_ref(raw) == exp


@pytest.mark.parametrize("raw", ["", "  ", "https://t.me/+AbCdEf", "@ab", "سلام", "12345", "https://evil.com/bia2music1395"])
def test_normalize_invalid(raw):
    with pytest.raises(InvalidChannelRef):
        normalize_channel_ref(raw)


async def test_check_ok_and_read_only(app_ctx, bot):
    st = await app_ctx.channel.check("@bia2music1395")
    assert st.ok and st.bot_is_admin and st.can_post and st.member_count == 22
    assert set(bot.calls) <= {"get_chat", "get_chat_member_count", "get_me", "get_chat_member"}


async def test_check_not_admin(app_ctx, bot):
    bot.member.status = "member"
    st = await app_ctx.channel.check("@x12345")
    assert st.ok and not st.bot_is_admin and not st.can_post


async def test_check_admin_without_post(app_ctx, bot):
    bot.member.can_post_messages = False
    st = await app_ctx.channel.check("@x12345")
    assert st.bot_is_admin and not st.can_post


async def test_check_errors(app_ctx, bot):
    bot.chat = BadRequest("Chat not found")
    assert not (await app_ctx.channel.check("@x12345")).ok
    bot.chat = Forbidden("no")
    assert not (await app_ctx.channel.check("@x12345")).ok


async def test_not_a_channel(app_ctx, bot):
    bot.chat.type = "supergroup"
    assert not (await app_ctx.channel.check("@x12345")).ok
