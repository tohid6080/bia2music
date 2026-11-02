"""تولید متن تبلیغ با قالب‌های رایگان (بدون AI). فقط از داده‌ی واقعی آرشیو استفاده می‌شود؛ هر خطی که داده‌اش نباشد
نمی‌آید و هیچ عددی ساخته نمی‌شود. متن‌ها را مدیر دستی منتشر می‌کند؛ ربات چیزی ارسال نمی‌کند."""
from __future__ import annotations

from typing import Callable, Optional

from musicbot.publishing.captions import normalize_hashtags

NAME = "Bia2Music"
VARIANTS = 3
KINDS = {
    "whatsapp": ("💬", "واتساپ"), "instagram": ("📸", "اینستاگرام"), "telegram": ("✈️", "تلگرام (گروه/استوری/پست)"),
    "partner": ("🤝", "همکاری با کانال‌ها"), "invite": ("👫", "پیام کوتاه دعوت دوستان"), "songs": ("🎧", "معرفی آهنگ‌های محبوب"),
}
NOTES = {
    "telegram": "⚠️ قبل از ارسال در گروه‌ها قوانین تبلیغ همان گروه را رعایت کنید.",
    "whatsapp": "⚠️ فقط برای افراد و گروه‌هایی بفرستید که موافقند؛ ارسال انبوه ناخواسته ممنوع است.",
    "instagram": "ℹ️ در اینستاگرام لینک داخل کپشن کلیک‌پذیر نیست؛ آن را در بیو بگذارید.",
    "partner": "ℹ️ اگر تعداد اعضا یا آمار دیگری می‌نویسید، فقط عدد واقعی را بنویسید.",
}


class NoData(Exception):
    """داده‌ی لازم (مثلاً آهنگ منتشرشده) وجود ندارد."""

    def __init__(self, message_fa: str):
        super().__init__(message_fa)
        self.message_fa = message_fa


def channel_link(ctx, campaign_id: int = 0) -> Optional[str]:
    """لینک کمپین (برای ردیابی عضویت) یا لینک عمومی کانال؛ None اگر هیچ‌کدام در دسترس نباشد."""
    if campaign_id:
        c = ctx.repos.growth.get_campaign(campaign_id)
        return c["invite_link"] if c and c["status"] == "active" and c["invite_link"] else None
    ref = ctx.effective_channel_ref()
    return f"https://t.me/{ref[1:]}" if ref and ref.startswith("@") else None


def facts(ctx) -> dict:
    r = ctx.repos
    n = r.songs.count("published")
    recent = r.songs.list("published", limit=3) if n else []
    liked = r.userdata.top_liked(3)
    genre_names = {str(i["key"]): i["name_fa"] for i in r.categories.list("genres")}
    counts = r.songs.counts_by("g", published_only=True)
    top_genres = [genre_names[str(k)] for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:2] if str(k) in genre_names]
    return {"published": n, "recent": recent, "liked": liked, "top_genres": top_genres}


def _name(s: dict) -> str:
    return " - ".join(x for x in (s.get("artist"), s.get("title")) if x)


def _blocks(*parts: Optional[str]) -> str:
    return "\n".join(p for p in parts if p)


def _count(f: dict) -> Optional[str]:
    return f"🎵 {f['published']} آهنگ در آرشیو" if f["published"] >= 5 else None


def _samples(f: dict, label: str = "مثلاً:") -> Optional[str]:
    rows = [_name(s) for s in f["recent"][:2] if _name(s)]
    return (f"{label} " + " | ".join(rows)) if rows else None


def _hashtags(f: dict) -> str:
    tags = ["#موزیک", "#آهنگ", "#موسیقی_ایرانی", f"#{NAME}"] + normalize_hashtags(" ".join(f["top_genres"]))
    return " ".join(dict.fromkeys(tags))


def _whatsapp(v: int, f: dict, link: str) -> str:
    if v == 0:
        return _blocks("سلام 👋", f"کانال موسیقی {NAME} رو پیشنهاد می‌کنم 🎧", _count(f), _samples(f), "اگه موسیقی دوست داری، عضو شو 👇", link)
    if v == 1:
        return _blocks("🎶 دنبال آهنگ خوب می‌گردی؟", f"{NAME}: موسیقی ایرانی و خارجی، دسته‌بندی‌شده و قابل جست‌وجو", _samples(f), link)
    return _blocks("سلام! یه کانال موسیقی راه انداختم: " + NAME + " 🎧", _count(f), f"لینک: {link}", "نظرت رو بگو 🌹")


def _instagram(v: int, f: dict, link: str) -> str:
    tail = _blocks("", "👇 لینک عضویت در بیو (یا مستقیم):", link, "", _hashtags(f))
    if v == 0:
        return _blocks(f"🎧 {NAME}", "موسیقی ایرانی و خارجی، منتخب و دسته‌بندی‌شده", _count(f), _samples(f, "🎵")) + "\n" + tail
    if v == 1:
        return _blocks("✨ حال‌وهوای امروزت چیه؟", "برای هر حال‌وهوا آهنگ داریم 🎶", _count(f)) + "\n" + tail
    return _blocks(f"📣 کانال تلگرام {NAME}", "آهنگ‌های ایرانی و خارجی؛ بشنو، پیدا کن، ذخیره کن", _samples(f, "🎵")) + "\n" + tail


def _telegram(v: int, f: dict, link: str) -> str:
    if v == 0:
        return _blocks(f"🎧 {NAME}", "موسیقی ایرانی و خارجی، دسته‌بندی‌شده", _count(f), _samples(f, "🎵"), f"👈 {link}")
    if v == 1:
        return _blocks(f"🎶 اگر آهنگ خوب دوست دارید، کانال {NAME} را ببینید", _samples(f, "🎵"), link)
    return _blocks(f"سلام دوستان 🌹 کانال موسیقی {NAME}", _count(f), "نظرتون رو درباره‌ی آهنگ‌ها بگید 🙏", link)


def _partner(v: int, f: dict, link: str) -> str:
    about = _blocks(f"کانال: {NAME}", "موضوع: موسیقی ایرانی و خارجی", _count(f), _samples(f, "نمونه:"), f"لینک: {link}")
    if v == 0:
        return _blocks("سلام و وقت بخیر 🌹", f"من مدیر کانال موسیقی {NAME} هستم و کانال شما را دنبال می‌کنم.", "پیشنهادم یک تبادل/معرفی متقابل است تا مخاطبان واقعی و علاقه‌مند هر دو کانال با هم آشنا شوند.", "", about, "", "هر دو طرف: فقط اعضای واقعی و بدون خرید عضو. اگر موافقید، شکل و زمان همکاری را هماهنگ کنیم. 🙏")
    if v == 1:
        return _blocks("درود 🌿", f"{NAME} یک کانال موسیقی است و دنبال همکاری با کانال‌های هم‌موضوع هستیم.", "پیشنهاد: هر کانال یک پست معرفی برای دیگری بگذارد (با لینک اختصاصی تا نتیجه سنجیده شود).", "", about, "", "هر دو طرف: فقط مخاطب واقعی و بدون خرید عضو. منتظر نظرتان هستم.")
    return _blocks("سلام 👋", f"کانال {NAME} با علاقه به موسیقی راه‌اندازی شده و می‌خواهیم با کانال‌های خوب موسیقی ارتباط بگیریم.", "اگر تبادل معرفی برایتان مناسب است، بفرمایید (فقط مخاطب واقعی؛ بدون خرید عضو).", "", about)


def _invite(v: int, f: dict, link: str) -> str:
    if v == 0:
        return f"سلام! کانال موسیقی {NAME} رو ببین 🎶 {link}"
    if v == 1:
        return f"آهنگ‌های خوب این‌جاست 🎧 {link}"
    return f"اگه موسیقی دوست داری، {NAME} رو امتحان کن 🌹 {link}"


def _songs(v: int, f: dict, link: str) -> str:
    if f["liked"]:
        title, rows = "❤️ محبوب‌ترین آهنگ‌های ما (بر اساس پسند اعضا)", [(t.get("artist"), t.get("title")) for t in f["liked"]]
    elif f["recent"]:
        title, rows = "🆕 تازه‌ترین آهنگ‌های ما", [(s.get("artist"), s.get("title")) for s in f["recent"]]
    else:
        raise NoData("هنوز آهنگ منتشرشده‌ای در آرشیو نیست؛ این متن بدون داده‌ی واقعی ساخته نمی‌شود.")
    lines = [f"{i}. {_name({'artist': a, 'title': t})}" for i, (a, t) in enumerate(rows, 1) if _name({'artist': a, 'title': t})]
    if v == 0:
        return _blocks(title, *lines, "", f"همه‌ی آهنگ‌ها در {NAME} 👇", link)
    if v == 1:
        return _blocks(f"🎶 {NAME}", title, *lines, "", link)
    return _blocks(title, "", *lines, "", f"عضو شوید و آهنگ‌های بیشتر بشنوید: {link}")


_BUILDERS: dict[str, Callable] = {"whatsapp": _whatsapp, "instagram": _instagram, "telegram": _telegram,
                                  "partner": _partner, "invite": _invite, "songs": _songs}


def generate(ctx, kind: str, campaign_id: int = 0, variant: int = 0) -> tuple[str, int]:
    """(متن، شماره‌ی نسخه). NoData اگر داده/لینک لازم نباشد."""
    if kind not in _BUILDERS:
        raise ValueError("kind")
    link = channel_link(ctx, campaign_id)
    if not link:
        raise NoData("لینکی برای درج در متن نیست: کانال لینک عمومی (@username) ندارد یا کمپین فعال نیست. یک کمپین با لینک دعوت بسازید و آن را انتخاب کنید.")
    v = variant % VARIANTS
    return _BUILDERS[kind](v, facts(ctx), link), v
