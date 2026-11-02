FA = {
    "start": "🎧 <b>به Bia2Music خوش آمدید</b>\nYour Music Universe\n\nکشف موسیقی، بازی و آزمون، میکس‌تیپ شخصی و… همه در یک مینی‌اپ.\nبرای شروع دکمه‌ی زیر را بزنید.",
    "open": "🎵 باز کردن Bia2Music",
    "no_url": "⚠️ آدرس مینی‌اپ هنوز تنظیم نشده است. مدیر باید WEBAPP_URL (آدرس HTTPS) را در فایل .env بگذارد.",
    "help": "راهنما:\n/start — شروع و باز کردن مینی‌اپ\n/app — باز کردن مینی‌اپ\n/help — این راهنما",
    "private_only": "برای استفاده از Bia2Music در گفتگوی خصوصی با ربات /start بزنید.",
    "unknown": "برای باز کردن برنامه /app را بزنید.",
    "denied": "این دستور فقط برای مدیر است.",
}
EN = {
    "start": "🎧 <b>Welcome to Bia2Music</b>\nYour Music Universe\n\nDiscover music, play games and quizzes, build mixtapes — all in one Mini App.\nTap the button below to start.",
    "open": "🎵 Open Bia2Music",
    "no_url": "⚠️ The Mini App URL is not configured yet. The admin must set WEBAPP_URL (an HTTPS address) in the .env file.",
    "help": "Help:\n/start — start and open the Mini App\n/app — open the Mini App\n/help — this help",
    "private_only": "To use Bia2Music, send /start in a private chat with the bot.",
    "unknown": "Send /app to open the app.",
    "denied": "This command is for the admin only.",
}


def t(lang_code, key: str) -> str:
    return (FA if (lang_code or "fa").lower().startswith("fa") else EN)[key]
