"""آرشیو: فهرست صفحه‌بندی‌شده، فیلتر بر اساس دسته، و جست‌وجو."""
from __future__ import annotations

import math

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import ctx_of, esc, show
from musicbot.songs.textutils import normalize
from musicbot.ui import song_ui as U

_DIM_PREFIX = {"all": "همه آهنگ‌ها", "draft": "پیش‌نویس‌ها", "ready": "آماده انتشار", "scheduled": "زمان‌بندی‌شده", "published": "منتشرشده", "nolang": "منتشرشده‌های بدون زبان", "q": "نتایج جست‌وجو"}


async def show_archive_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    await show(update, U.archive_menu_text(ctx.repos.songs.counts_by_status()),
               U.archive_menu_keyboard(ctx.repos.songs.count("nolang")))


async def show_dim_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, dim: str) -> None:
    ctx = ctx_of(context)
    items = ctx.repos.categories.list(U.DIM_TABLE[dim])
    counts = ctx.repos.songs.counts_by(dim)
    await show(update, f"🗂 <b>{U.DIM_TITLE[dim]}</b>\nیکی را انتخاب کنید:", U.dim_menu_keyboard(dim, items, counts))


def _title(ctx, flt: str, q: str | None) -> str:
    if flt in _DIM_PREFIX:
        base = _DIM_PREFIX[flt]
        return f"{base}: «{q}»" if flt == "q" and q else base
    dim, _, val = flt.partition(".")
    for it in ctx.repos.categories.list(U.DIM_TABLE[dim]):
        if str(it["key"]) == val:
            return f"{U.DIM_TITLE[dim]}: {it['name_fa']}"
    return "فهرست"


async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, flt: str, page: int) -> None:
    ctx = ctx_of(context)
    q_raw = context.user_data.get("search_q")
    q_norm = normalize(q_raw) if flt == "q" else None
    if flt == "q" and not q_norm:
        await show(update, "⌛ جست‌وجو منقضی شده است. دوباره جست‌وجو کنید.", U.cancel_search())
        return
    try:
        total = ctx.repos.songs.count(flt, q_norm)
    except ValueError:
        await show(update, "❌ فیلتر نامعتبر است.", U.cancel_search())
        return
    pages = max(1, math.ceil(total / U.PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    songs = ctx.repos.songs.list(flt, q_norm, U.PAGE_SIZE, page * U.PAGE_SIZE)
    await show(update, U.list_text(_title(ctx, flt, q_raw), total, page, pages), U.list_keyboard(songs, flt, page, pages))


async def ask_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting"] = "search"
    await show(update, "🔍 <b>جست‌وجو</b>\n\nبخشی از نام آهنگ یا خواننده را بفرستید.", U.cancel_search())


async def receive_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if not normalize(text):
        await show(update, "❌ عبارت معتبری بفرستید یا لغو کنید.", U.cancel_search())
        return
    context.user_data.pop("awaiting", None)
    context.user_data["search_q"] = text[:60]
    await show_list(update, context, "q", 0)
