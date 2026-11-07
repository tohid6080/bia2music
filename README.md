# Bia2Music — Your Music Universe 🎧

Mini App تلگرام برای کشف موسیقی (کانال: https://t.me/bia2music1395).
**وضعیت: مرحله‌ی ۱ از ۶** — ساختار پروژه، Backend، Bot، Mini App، ورود امن با هویت تلگرام، دیتابیس، صفحه‌ی خانه و منوی اصلی.
مراحل ۲ تا ۶ (Music DNA، Battle، Quiz، Match، Mixtape، Trend Radar…) هنوز **ساخته نشده‌اند**؛ در برنامه هم همین‌طور نشان داده می‌شوند.

> ربات مدیریت/انتشار قبلی در پوشه‌ی `musicbot/` است (مستندات: `docs/legacy-bot-README.md`). تازه: گزارش فعالیت کاربران با رضایت جداگانه + اجرا بدون Termux روی میزبان ابری ([docs/HOSTING-FREE.md](docs/HOSTING-FREE.md)).

## چه چیزی کار می‌کند؟ (مرحله‌ی ۱)
- ربات: `/start` و `/app` ← دکمه‌ی «باز کردن Bia2Music»؛ دکمه‌ی منوی ربات هم Mini App را باز می‌کند؛ `/admin` (فقط مدیر) آمار واقعی.
- Mini App: ورود خودکار با هویت تلگرام (اعتبارسنجی امن سمت سرور)، صفحه‌ی خانه، ۵ تب، فارسی/انگلیسی با RTL/LTR، تم تاریک، حالت‌های بارگذاری/خالی/خطا، تغییر زبان، **حذف حساب و داده‌ها**.
- صفحه‌ی خانه فقط داده‌ی واقعی نشان می‌دهد؛ تا وقتی آهنگی در آرشیو نیست، بخش‌ها «خالی» و صادقانه‌اند. ترند، چالش روز و کشف در مراحل بعد.

## راه‌اندازی سریع (روی کامپیوتر)
```bash
cd backend
cp .env.example .env          # BOT_TOKEN, ADMIN_USER_ID را پر کنید
pip install -r requirements.txt
python -m b2m.cli init-db
python -m b2m.cli seed-demo   # (اختیاری) ۵ آهنگ آشکارا نمونه برای دیدن رابط
cd ../webapp && npm install && npm run build && cd ../backend
python -m b2m.cli run         # Backend + Mini App روی http://127.0.0.1:8000
python -m b2m.bot             # ربات (در ترمینال دیگر؛ نیازمند WEBAPP_URL با HTTPS)
```
برای باز شدن در تلگرام باید آدرس **HTTPS عمومی** داشته باشید: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
معماری، API و مدل داده: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## متغیرهای محیطی
همه در `backend/.env.example` توضیح داده شده‌اند. حیاتی‌ها: `BOT_TOKEN`، `ADMIN_USER_ID`، `WEBAPP_URL` (HTTPS)، `JWT_SECRET` (در production الزامی).

## تست
```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q   # Backend + Bot + دیتابیس + مهاجرت
cd webapp && npm test && npm run build                                      # i18n + تایپ‌چک + ساخت
```
برای آزمون مرورگر بدون تلگرام: `python -m b2m.cli dev-initdata` یک initData امضاشده می‌سازد (به `BOT_TOKEN` واقعی نیاز دارد؛ خروجی را منتشر نکنید) و در `webapp/.env.local` با `VITE_DEV_INIT_DATA=...` و `npm run dev` استفاده می‌شود.

## قواعد ثابت پروژه
بدون انتشار خودکار در کانال (انتشار فقط با تأیید صریح مدیر؛ در دیتابیس هم اعمال شده)، بدون AI/سرویس پولی، بدون Secret در Git، بدون عضو فیک/عضویت اجباری/پیام انبوه، بدون آمار/ترند ساختگی، انتشار فایل فقط با مجوز.
