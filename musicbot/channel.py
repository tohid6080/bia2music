"""اتصال به کانال. در مرحله اول فقط عملیات «خواندنی» (getMe/getChat/getChatMember) انجام می‌شود.
هیچ متدی برای ارسال پست به کانال وجود ندارد؛ انتشار در مرحله سوم و فقط با تأیید مدیر اضافه می‌شود."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from telegram import Bot
from telegram.error import BadRequest, Forbidden, TelegramError

_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")
_NUMERIC_RE = re.compile(r"^-100\d{5,}$")
_LINK_RE = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z][A-Za-z0-9_]{4,31})/?$", re.IGNORECASE)


class InvalidChannelRef(ValueError):
    pass


def normalize_channel_ref(text: str) -> str:
    """ورودی‌های مجاز: @username ، لینک t.me/username ، یا شناسه عددی -100..."""
    t = (text or "").strip()
    if not t:
        raise InvalidChannelRef("empty")
    m = _LINK_RE.match(t)
    if m:
        return "@" + m.group(1)
    if _USERNAME_RE.match(t):
        return t
    if _NUMERIC_RE.match(t):
        return t
    if re.match(r"^[A-Za-z][A-Za-z0-9_]{4,31}$", t):
        return "@" + t
    raise InvalidChannelRef(t)


@dataclass
class ChannelStatus:
    ok: bool                       # کانال پیدا شد
    title: Optional[str] = None
    username: Optional[str] = None
    member_count: Optional[int] = None
    bot_is_admin: bool = False
    can_post: bool = False
    can_invite: bool = False
    can_edit: bool = False
    error_fa: Optional[str] = None


class ChannelService:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def member_count(self, channel_ref: Optional[str]) -> Optional[int]:
        """تعداد اعضا (فقط‌خواندنی)؛ None اگر در دسترس نبود."""
        if not channel_ref:
            return None
        try:
            return await self._bot.get_chat_member_count(channel_ref)
        except TelegramError:
            return None

    async def check(self, channel_ref: str) -> ChannelStatus:
        try:
            chat = await self._bot.get_chat(channel_ref)
        except Forbidden:
            return ChannelStatus(False, error_fa="ربات به این کانال دسترسی ندارد. ابتدا ربات را به کانال اضافه و ادمین کنید.")
        except BadRequest:
            return ChannelStatus(False, error_fa="کانال پیدا نشد. شناسه یا لینک را بررسی کنید (کانال باید وجود داشته باشد).")
        except TelegramError:
            return ChannelStatus(False, error_fa="ارتباط با تلگرام برقرار نشد. کمی بعد دوباره تلاش کنید.")

        if getattr(chat, "type", None) != "channel":
            return ChannelStatus(False, error_fa="این شناسه مربوط به یک کانال نیست.")

        status = ChannelStatus(True, title=chat.title, username=chat.username)
        try:
            status.member_count = await self._bot.get_chat_member_count(chat.id)
        except TelegramError:
            pass
        try:
            me = await self._bot.get_me()
            member = await self._bot.get_chat_member(chat.id, me.id)
            if member.status == "creator":
                status.bot_is_admin, status.can_post, status.can_invite, status.can_edit = True, True, True, True
            elif member.status == "administrator":
                status.bot_is_admin = True
                status.can_post = bool(getattr(member, "can_post_messages", False))
                status.can_invite = bool(getattr(member, "can_invite_users", False))
                status.can_edit = bool(getattr(member, "can_edit_messages", False))
        except TelegramError:
            status.error_fa = "وضعیت دسترسی ربات در کانال قابل بررسی نبود."
        return status
