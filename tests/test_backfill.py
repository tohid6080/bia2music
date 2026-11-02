import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from musicbot.handlers import backfill as bh, menu, settings as sh
from musicbot.promo_backfill import BackfillStats, PromoBackfill
from musicbot.publishing.captions import PostOptions, post_markup
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, ready_song, txt

REF = "@bia2music1395"
MARKUP = post_markup(PostOptions(button_url="https://t.me/Tohidmusic_bot"))


class EditBot:
    def __init__(self, errors=None):
        self.calls, self.errors = [], errors or {}

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        self.calls.append((chat_id, message_id, reply_markup))
        err = self.errors.get(message_id)
        if isinstance(err, list):
            if err:
                raise err.pop(0)
        elif err:
            raise err


def published(repos, n, start_msg=100):
    ids = []
    for i in range(n):
        sid = repos.songs.create(title=f"t{i}", artist="a", telegram_file_id="F", file_unique_id=f"u{start_msg + i}")
        repos.songs.update(sid, status="published", caption=f"کپشن {i}")
        repos.db.execute("UPDATE songs SET channel_message_id=? WHERE id=?", (start_msg + i, sid))
        ids.append(sid)
    return ids


def runner(repos, bot, markup=MARKUP, sleeps=None):
    async def sl(x):
        if sleeps is not None:
            sleeps.append(x)
    return PromoBackfill(bot, repos, REF, markup, pace=0, sleep=sl)


async def go(r, mode="apply", limit=None, stop=None):
    st = BackfillStats()
    err = await r.run(mode, limit, st, stop or asyncio.Event())
    return err, st


async def test_apply_only_markup_to_published_posts(repos):
    ids = published(repos, 3)
    draft = repos.songs.create(title="d", artist="x", telegram_file_id="F", file_unique_id="ud")       # منتشرنشده
    before = {i: dict(repos.songs.get(i)) for i in ids}
    bot = EditBot()
    err, st = await go(runner(repos, bot))
    assert err is None and (st.scanned, st.done) == (3, 3)
    assert sorted(m for _, m, _ in bot.calls) == [100, 101, 102] and [m for _, m, _ in bot.calls] == [102, 101, 100]    # جدیدترین اول
    assert all(c == REF and isinstance(mk, InlineKeyboardMarkup) and mk.inline_keyboard[0][0].url == "https://t.me/Tohidmusic_bot" for c, _, mk in bot.calls)
    assert all(repos.songs.get(i) == before[i] for i in ids) and repos.songs.get(draft)["status"] == "draft"          # دیتابیس آهنگ‌ها دست‌نخورده
    assert repos.songs.promo_counts() == {"eligible": 3, "applied": 3, "skipped": 0}
    n = len(bot.calls)
    err, st = await go(runner(repos, bot))
    assert len(bot.calls) == n and st.scanned == 0                                                                    # دوباره اعمال نمی‌شود


async def test_not_modified_and_uneditable(repos):
    published(repos, 3)
    bot = EditBot({102: BadRequest("Bad Request: message is not modified"), 101: BadRequest("Bad Request: message to edit not found")})
    err, st = await go(runner(repos, bot))
    assert err is None and (st.done, st.already, st.skipped, st.errors) == (1, 1, 1, 0)
    assert repos.songs.promo_counts() == {"eligible": 3, "applied": 2, "skipped": 1}
    n = len(bot.calls)
    await go(runner(repos, bot))
    assert len(bot.calls) == n                                                                                          # رد‌شده دوباره امتحان نمی‌شود
    repos.songs.promo_reset_skipped()
    bot.errors = {}
    await go(runner(repos, bot))
    assert len(bot.calls) == n + 1


async def test_retry_after_and_network_errors_no_infinite_loop(repos):
    published(repos, 3)
    sleeps = []
    bot = EditBot({102: [RetryAfter(3)], 100: TimedOut("t")})
    err, st = await go(runner(repos, bot, sleeps=sleeps))
    assert err is None and (st.done, st.errors) == (2, 1) and 4.0 in sleeps
    assert len(bot.calls) < 20                                                                                          # حلقه‌ی بی‌پایان نشد
    assert repos.songs.promo_counts()["applied"] == 2                                                                   # خطادار علامت نخورد
    bot.errors = {}
    err, st = await go(runner(repos, bot))
    assert st.done == 1 and repos.songs.promo_counts()["applied"] == 3                                                  # دور بعد کامل شد


async def test_fatal_errors(repos):
    published(repos, 2)
    err, st = await go(runner(repos, EditBot({101: Forbidden("no")})))
    assert "Edit messages of others" in err and st.done == 0 and repos.songs.promo_counts()["applied"] == 0
    err, st = await go(runner(repos, EditBot({101: BadRequest("Chat not found")})))
    assert "نپذیرفت" in err
    err, st = await go(runner(repos, EditBot(), markup=None))
    assert "خاموش" in err and st.scanned == 0


async def test_limit_one_then_continue_and_stop(repos):
    published(repos, 5)
    bot = EditBot()
    err, st = await go(runner(repos, bot), limit=1)
    assert st.done == 1 and [m for _, m, _ in bot.calls] == [104]                                                       # فقط جدیدترین
    stop = asyncio.Event()
    stopper = EditBot()
    real = stopper.edit_message_reply_markup

    async def edit(chat_id, message_id, reply_markup=None):
        await real(chat_id, message_id, reply_markup)
        if len(stopper.calls) == 2:
            stop.set()                                                                                                  # بعد از دو پست توقف
    stopper.edit_message_reply_markup = edit
    st2 = BackfillStats()
    await runner(repos, stopper).run("apply", None, st2, stop)
    assert st2.scanned == 2 and repos.songs.promo_counts()["applied"] == 1 + 2                                          # ۱ آزمایشی + ۲
    await go(runner(repos, bot))
    assert repos.songs.promo_counts()["applied"] == 5 and len(bot.calls) == 1 + 2                                       # ادامه از همان‌جا؛ تکراری نیست


async def test_remove_mode_only_applied(repos):
    published(repos, 3)
    bot = EditBot()
    await go(runner(repos, bot), limit=2)                                                                                # ۲ تا اعمال شد
    bot.calls.clear()
    err, st = await go(runner(repos, bot), mode="remove")
    assert st.done == 2 and sorted(m for _, m, _ in bot.calls) == [101, 102] and all(mk is None for _, _, mk in bot.calls)
    assert repos.songs.promo_counts()["applied"] == 0
    err, st = await go(runner(repos, bot), mode="remove")
    assert st.scanned == 0


# ---------- رابط ربات ----------
@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(bh, "PACE", 0)


def ctx_with_bot(app_ctx, errors=None):
    app_ctx.bot_username = "Tohidmusic_bot"
    c = make_context(app_ctx)
    eb = EditBot(errors)
    eb.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    eb.edit_message_text = AsyncMock()
    c.bot = eb
    c.application.bot = eb
    return c, eb


async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    await (bh.backfill_callback if data.startswith("b:") else (sh.settings_callback if data.startswith("s:") else menu.menu_callback))(u, c)
    return u


async def test_menu_is_honest_and_counts(app_ctx):
    published(app_ctx.repos, 4)
    c, _ = ctx_with_bot(app_ctx)
    u = await click(c, "m:settings")
    assert "b:menu" in cbs(u)
    t = txt(await click(c, "b:menu"))
    assert "<b>4</b>" in t and "فقط <b>دکمه‌ی لینک</b>" in t and "اعمال نمی‌شود" in t and "جایگزین می‌شود" in t and "Edit messages of others" in t
    assert {"b:t", "b:a", "b:rm"} <= cbs(await click(c, "b:menu"))


async def test_precheck_blocks(app_ctx, bot):
    published(app_ctx.repos, 2)
    c, eb = ctx_with_bot(app_ctx)
    app_ctx.repos.settings.set("promo_button", "0")
    assert "خاموش" in txt(await click(c, "b:t"))
    app_ctx.repos.settings.set("promo_button", "1")
    bot.member.status = "member"
    assert "ادمین باشد" in txt(await click(c, "b:t"))
    bot.member.status = "administrator"
    object.__setattr__(app_ctx.settings, "channel_id", None)
    assert "تنظیم نشده" in txt(await click(c, "b:t"))
    assert eb.calls == [] and "promo_job" not in c.application.bot_data
    app_ctx.bot_username = None
    object.__setattr__(app_ctx.settings, "channel_id", REF)
    assert "نام کاربری ربات" in txt(await click(c, "b:a")) or "خاموش" in txt(await click(c, "b:a"))


async def test_test_one_then_confirm_all_then_remove(app_ctx):
    r = app_ctx.repos
    published(r, 25)
    c, eb = ctx_with_bot(app_ctx)
    await click(c, "b:t")
    job = c.application.bot_data["promo_job"]
    await job.task
    assert job.stats.done == 1 and [m for _, m, _ in eb.calls] == [124]
    assert "کانال را باز کنید" in eb.edit_message_text.call_args.args[0] and "پایان" in eb.edit_message_text.call_args.args[0]
    u = await click(c, "b:a")
    assert "24 پست" in txt(u) and "دقیقه" in txt(u) and "b:goa" in cbs(u) and len(eb.calls) == 1                         # تا تأیید دوم هیچ تغییری نیست
    await click(c, "b:goa")
    await c.application.bot_data["promo_job"].task
    assert r.songs.promo_counts()["applied"] == 25 and len(eb.calls) == 25
    assert "پستی برای این کار نمانده" in txt(await click(c, "b:a"))
    u = await click(c, "b:rm")
    assert "برداشتن دکمه از 25 پست" in txt(u) and "b:gor" in cbs(u)
    await click(c, "b:gor")
    await c.application.bot_data["promo_job"].task
    assert r.songs.promo_counts()["applied"] == 0 and eb.calls[-1][2] is None
    assert any(l["action"] == "promo_backfill_finished" for l in r.logs.recent(20))
    assert not [x for x in eb.send_message.call_args_list if x.args[0] != ADMIN]


async def test_busy_stop_and_stranger(app_ctx):
    published(app_ctx.repos, 2)
    c, eb = ctx_with_bot(app_ctx)
    from musicbot.promo_backfill import BackfillJob

    job = BackfillJob("apply", None)
    c.application.bot_data["promo_job"] = job
    for data in ("b:t", "b:a", "b:goa", "b:rm"):
        assert "در حال اجراست" in txt(await click(c, data))
    await click(c, "b:x")
    assert job.stop.is_set()
    c2, eb2 = ctx_with_bot(app_ctx)
    for data in ("b:t", "b:goa", "b:gor", "b:rs"):
        u = await click(c2, data, user=555)
        u.callback_query.edit_message_text.assert_not_called()
    assert eb2.calls == [] and "promo_job" not in c2.application.bot_data


async def test_rights_error_surfaces_in_summary(app_ctx):
    published(app_ctx.repos, 3)
    c, eb = ctx_with_bot(app_ctx, {102: Forbidden("rights")})
    await click(c, "b:t")
    await c.application.bot_data["promo_job"].task
    assert "Edit messages of others" in eb.edit_message_text.call_args.args[0]
    assert app_ctx.repos.songs.promo_counts()["applied"] == 0
