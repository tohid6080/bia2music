"""پنل کپشن و هشتگ (تولید با قالب/AI Provider، ویرایش دستی)."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.publishing.captions import MAX_CAPTION, ensure_caption, final_caption, normalize_hashtags
from musicbot.ui import keyboards as K
from musicbot.ui import publish_ui as PU
from musicbot.ui import texts as T

NOT_FOUND = "❌ این آهنگ پیدا نشد."


async def show_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, note: str = "", generated_real=None) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(sid)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if song["status"] == "published":
        await show(update, "⛔ کپشن آهنگ منتشرشده از اینجا قابل ویرایش نیست.", K.back_to_menu())
        return
    if not song.get("caption"):
        generated_real = await ensure_caption(ctx, sid)
        song = ctx.repos.songs.get(sid)
    body = final_caption(song)
    source = ""
    if generated_real is not None:
        source = "\n🤖 ساخته‌شده با هوش مصنوعی" if generated_real else "\nℹ️ ساخته‌شده با قالب و قوانین (هوش مصنوعی واقعی نیست)"
    text = (
        f"📝 <b>کپشن و هشتگ</b>\n🎵 {esc(song.get('title') or '—')} — {esc(song.get('artist') or '—')}\n\n"
        f"<blockquote>{esc(body) or 'خالی'}</blockquote>\n"
        f"{len(body)}/{MAX_CAPTION} حرف{source}"
        + (f"\n\n{note}" if note else "")
    )
    await show(update, text, PU.caption_panel_keyboard(sid, song["status"] in ("ready", "scheduled")))


@admin_only
async def captions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    context.user_data.pop("awaiting", None)
    try:
        if len(parts) == 2:
            await show_panel(update, context, int(parts[1]))
            return
        action, sid = parts[1], int(parts[2])
        if not ctx.repos.songs.get(sid):
            await show(update, NOT_FOUND, K.back_to_menu())
        elif action == "gen":
            if ctx.repos.songs.get(sid)["status"] == "published":
                await show_panel(update, context, sid)
                return
            real = await ensure_caption(ctx, sid, force=True)
            ctx.repos.logs.add("caption_generated", update.effective_user.id, f"id={sid}")
            await show_panel(update, context, sid, "🔄 دوباره ساخته شد.", real)
        elif action in ("ec", "eh"):
            context.user_data["awaiting"] = f"{'caption' if action == 'ec' else 'hashtags'}:{sid}"
            prompt = ("✏️ متن جدید <b>کپشن</b> را بفرستید (بدون هشتگ؛ هشتگ‌ها جدا ذخیره می‌شوند):" if action == "ec"
                      else "#️⃣ هشتگ‌ها را بفرستید (با فاصله یا کاما جدا کنید؛ علامت # اختیاری است):")
            await show(update, prompt, PU.cancel_to_caption(sid))
        else:
            raise ValueError("action")
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    kind, _, sid_s = awaiting.partition(":")
    sid = int(sid_s)
    song = ctx.repos.songs.get(sid)
    text = (update.effective_message.text or "").strip()
    if not song or song["status"] == "published":
        context.user_data.pop("awaiting", None)
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if kind == "caption":
        if not text:
            await show(update, "❌ متن خالی است. دوباره بفرستید یا لغو کنید.", PU.cancel_to_caption(sid))
            return
        if len(text) + len(song.get("hashtags") or "") + 2 > MAX_CAPTION:
            await show(update, f"❌ متن خیلی بلند است (کپشن + هشتگ حداکثر {MAX_CAPTION} حرف). کوتاه‌تر بفرستید.",
                       PU.cancel_to_caption(sid))
            return
        ctx.repos.songs.update(sid, caption=text)
    else:
        tags = normalize_hashtags(text)
        if not tags:
            await show(update, "❌ هشتگ معتبری پیدا نشد. دوباره بفرستید یا لغو کنید.", PU.cancel_to_caption(sid))
            return
        joined = " ".join(tags)
        if len(song.get("caption") or "") + len(joined) + 2 > MAX_CAPTION:
            await show(update, "❌ هشتگ‌ها خیلی بلند است. کمتر بفرستید.", PU.cancel_to_caption(sid))
            return
        ctx.repos.songs.update(sid, hashtags=joined)
    context.user_data.pop("awaiting", None)
    ctx.repos.logs.add("caption_edited", update.effective_user.id, f"id={sid} {kind}")
    await show_panel(update, context, sid, "✅ ذخیره شد.")
