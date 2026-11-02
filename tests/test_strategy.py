"""مرحله ۱۰: استراتژی محتوا و رشد — فقط پیشنهاد، بدون حدس، بدون ارسال."""
from pathlib import Path

from musicbot import growth_strategy as GS
from musicbot.radar import suggest as S
from tests.conftest import ADMIN, make_context
from tests.helpers import cbs, txt
from tests.test_radar import T0, click, make
from tests.test_radar_suggest import fetch, ready, route  # noqa: F401


def build(app_ctx, members=22):
    return GS.build_strategy(app_ctx, members, T0)


def test_empty_state_is_honest(app_ctx):
    make(app_ctx, yt=False, lf=False)
    t = build(app_ctx, None)
    assert "نامشخص" in t and "در دسترس نیست" in t and "فعلاً پیشنهاد رادار ندارم" in t and "تضمین" in t
    assert "منتشر نمی‌شود" in t or "خودکار منتشر" in t


async def test_picks_follow_language_interest(app_ctx, ready):
    await fetch(app_ctx)
    assert [i.title for i in GS.pick_radar(app_ctx, T0, "fa")[0]] == ["Shab"]
    foreign = {i.title for i in GS.pick_radar(app_ctx, T0, "en")[0]}
    assert foreign == {"Rain", "Old"}
    assert "Shab" in {i.title for i in GS.pick_radar(app_ctx, T0, None)[0]}


async def test_excludes_archive_and_rejected(app_ctx, ready):
    await fetch(app_ctx)
    items = S.build_items(app_ctx)
    app_ctx.repos.radar.set_suggestion(next(i for i in items if i.title == "Rain").sug["id"], status="rejected")
    app_ctx.repos.songs.create(title="Shab", artist="علی", created_by=ADMIN)
    titles = {i.title for i in GS.pick_radar(app_ctx, T0, None)[0]}
    assert titles == {"Old"}


async def test_pipeline_notes_fileless_drafts(app_ctx, ready):
    await fetch(app_ctx)
    sug = next(i for i in S.build_items(app_ctx) if i.title == "Rain").sug
    sid, _ = S.ensure_song(app_ctx, sug, ADMIN)
    app_ctx.repos.radar.set_suggestion(sug["id"], status="drafted")
    t = build(app_ctx)
    assert "فایل ندارد" in t and "Rain" in t and "با مجوز" in t


async def test_strategy_screen_and_stranger(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    u = await click(c, "w:st") if False else None
    from musicbot.handlers import growth_content as gc
    from tests.conftest import make_update

    u = make_update(data="w:st")
    await gc.content_callback(u, c)
    assert "استراتژی محتوا" in txt(u) and "w:pl" in cbs(u)
    u = make_update(user_id=555, data="w:st")
    await gc.content_callback(u, c)
    assert u.callback_query.edit_message_text.call_args is None or "استراتژی" not in txt(u)


def test_strategy_module_cannot_send_or_publish():
    t = (Path(__file__).parent.parent / "musicbot/growth_strategy.py").read_text()
    for banned in ("send_message", "send_audio", "send_document", "forward_message", "publish_now", "create_chat_invite_link", "get_file"):
        assert banned not in t
