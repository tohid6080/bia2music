# استقرار Bia2Music

Mini App به **آدرس HTTPS عمومی** نیاز دارد. سه مسیر؛ هیچ‌کدام را من روی سرویس واقعی آزمایش نکرده‌ام (فقط اجرای محلی و آزمون خودکار انجام شده). شرایط و محدودیت‌های رایگان هر سرویس تغییر می‌کند؛ قبل از انتخاب، صفحه‌ی رسمی آن را بخوانید.

## الف) فقط با گوشی (Termux) + تونل HTTPS — برای آزمایش
- گوشی باید روشن و Termux فعال بماند؛ با بستن Termux ربات و Mini App قطع می‌شوند.
- تونل رایگان Cloudflare («quick tunnel») آدرس `https://…trycloudflare.com` موقت می‌دهد که هر بار عوض می‌شود؛ پس هر بار `WEBAPP_URL` را باید به‌روز و ربات را ری‌استارت کنید. (آدرس پایدار نیاز به دامنه/حساب دارد.)
- ⚠️ **ریسک شناخته‌شده در Termux:** FastAPI به `pydantic` (هسته‌ی Rust: `pydantic-core`) نیاز دارد. در Termux ساخت بسته‌های Rust گاهی شکست می‌خورد (مثل `jiter` در پروژه‌ی قبلی). اگر `pip install -r requirements.txt` خطا داد، گزینه‌ی (ب) را انتخاب کنید یا `pkg search pydantic` را بررسی کنید. **این را روی Termux آزمایش نکرده‌ام.**
- ساخت فایل‌های Mini App (`npm run build`) روی گوشی سنگین است؛ بهتر است پوشه‌ی `webapp/dist` از یک کامپیوتر/سرویس ساخته و منتقل شود.

## ب) میزبانی رایگان ابری (پیشنهادی برای پایداری)
Backend+Bot را روی یک سرویس رایگان PaaS و دیتابیس را SQLite یا PostgreSQL رایگان بگذارید. محدودیت‌هایی که باید بررسی و مستند کنید:
- **خوابیدن سرویس:** بسیاری از سطح‌های رایگان بعد از بی‌فعالیتی می‌خوابند؛ اولین باز کردن Mini App کند می‌شود و ربات با long-polling قطع می‌شود (راه‌حل: webhook یا سرویس همیشه‌روشن).
- **دیسک موقت:** روی برخی سرویس‌ها فایل SQLite با هر استقرار پاک می‌شود؛ برای ماندگاری از PostgreSQL مدیریت‌شده استفاده کنید (`pip install -r requirements-postgres.txt`، `DATABASE_URL=postgresql://…`).
- سقف منابع/ترافیک و ممنوعیت‌های احتمالی استفاده از سطح رایگان را از مستندات رسمی بخوانید.
- فرانت‌اند را هم می‌توان در یک میزبان ایستای رایگان گذاشت (آن‌گاه `CORS_ORIGINS` را تنظیم و آدرس API را با پراکسی/بازنویسی مسیر `/api` فراهم کنید). ساده‌ترین حالت همان سرو توسط Backend است.

## ج) سرور مجازی (VPS) — کاملاً پایدار
Caddy یا Nginx با گواهی خودکار Let's Encrypt جلوی `uvicorn`، سرویس systemd برای Backend و Bot. (`TRUST_PROXY_HEADERS=1` فقط پشت پراکسی خودتان.)

## نکته‌ی مهم: دو ربات یک توکن نمی‌توانند هم‌زمان polling کنند
ربات مدیریت قبلی (`musicbot`) و ربات جدید (`b2m.bot`) هر دو long-polling می‌کنند. با **یک توکن** هم‌زمان اجرا نکنید (خطای Conflict). گزینه‌ها: (۱) برای ربات جدید یک ربات دیگر در BotFather بسازید (پیشنهاد)؛ (۲) ربات قبلی را متوقف کنید. یکپارچه‌سازی دو ربات کار مراحل بعد است.

## مراحل استقرار
1. `cp backend/.env.example backend/.env` و پر کردن `BOT_TOKEN`، `ADMIN_USER_ID`، `JWT_SECRET` (و در production `APP_ENV=production`).
2. ساخت Mini App: `cd webapp && npm install && npm run build` (خروجی `webapp/dist`).
3. `cd backend && pip install -r requirements.txt && python -m b2m.cli init-db`
4. اجرای Backend: `python -m b2m.cli run --host 0.0.0.0 --port 8000` و قرار دادن پشت HTTPS.
5. `WEBAPP_URL` را روی آدرس HTTPS بگذارید و ربات را اجرا کنید: `python -m b2m.bot`.
6. در تلگرام: /start ← «باز کردن Bia2Music».
