from tests.conftest import ADMIN, make_update  # noqa: F401


def txt(u):
    q = u.callback_query
    if q and q.message.audio:
        return q.message.reply_text.call_args.args[0]
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.args[0]


def markup(u):
    q = u.callback_query
    if q and q.message.audio:
        return q.message.reply_text.call_args.kwargs["reply_markup"]
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.kwargs["reply_markup"]


def buttons(u):
    return [b for r in markup(u).inline_keyboard for b in r]


def cbs(u):
    return {b.callback_data for b in buttons(u) if b.callback_data}


def ready_song(repos, uid="u1", status="ready", **kw):
    sid = repos.songs.create(title=kw.get("title", "شب"), artist=kw.get("artist", "علی"), telegram_file_id="FILE" + uid, file_unique_id=uid,
                             duration_seconds=100)
    repos.songs.update(sid, language_code=kw.get("lang", "fa"), status=status, caption=kw.get("caption", "کپشن"), hashtags="#a")
    if status == "published":
        repos.db.execute("UPDATE songs SET post_url=?, channel_message_id=? WHERE id=?", (f"https://t.me/bia2music1395/{sid}", sid, sid))
    return sid
