# معماری Bia2Music (Mini App)

## تصمیم‌های اصلی
- **مونولیت ماژولار، نه میکروسرویس.** یک پردازش Backend (FastAPI) + یک پردازش Bot + فایل‌های ایستای Mini App. همه از یک لایه‌ی داده‌ی مشترک (`b2m.db`) استفاده می‌کنند.
- **یک آدرس HTTPS.** Backend فایل‌های ساخته‌شده‌ی Mini App را هم سرو می‌کند (بدون CORS و با یک دامنه). جداسازی میزبانی فرانت‌اند هم ممکن است (`CORS_ORIGINS`).
- **هیچ سرویس پولی یا AI.** در مرحله‌ی ۱ هیچ فراخوانی خارجی‌ای جز API تلگرام (ربات) وجود ندارد. توصیه/DNA/Mood در مراحل بعد با الگوریتم داخلی و پشت یک رابط Provider ساخته می‌شود تا بعداً AI قابل جایگزینی باشد.
- **داده‌ی ساختگی ممنوع.** هر بخشی که داده ندارد «حالت خالی» صادقانه نشان می‌دهد. تنها استثنا دستور صریح توسعه `seed-demo` است (ردیف‌ها `is_demo=1` و در رابط برچسب «نمونه» دارند؛ در production اجرا نمی‌شود).

## ساختار پوشه‌ها
```
backend/
  b2m/core/   config، اعتبارسنجی initData، توکن نشست، محدودیت نرخ
  b2m/db/     مدل‌ها (۲۴ جدول)، نشست دیتابیس، seed، مهاجرت
  b2m/api/    روترها (HTTP)، schemas، services (منطق)، deps
  b2m/bot/    ربات تلگرام (python-telegram-bot)
  b2m/cli.py  init-db | seed-demo | check-config | dev-initdata | run
  alembic/    مهاجرت‌ها (0001 = طرح کامل)
  tests/
webapp/       React + TypeScript + Vite
  src/pages, src/components, i18n.ts (fa/en + RTL/LTR), api.ts, telegram.ts
musicbot/     ربات مدیریت قبلی (مراحل ۱ تا ۱۰ پروژه‌ی قبل) — دست‌نخورده
docs/
```

## جریان احراز هویت
1. کاربر در تلگرام Mini App را باز می‌کند؛ تلگرام `initData` امضاشده می‌دهد.
2. Frontend آن را به `POST /api/auth/telegram` می‌فرستد.
3. Backend: `secret = HMAC_SHA256("WebAppData", BOT_TOKEN)`؛ `hash` را با `data_check_string` مقایسه می‌کند (زمان‌ثابت)، فیلد تکراری را رد می‌کند، `auth_date` را (حداکثر ۲۴ ساعت، پیش‌فرض) و آینده‌ی دور را رد می‌کند، `user.id` را اعتبارسنجی می‌کند.
4. کاربر ساخته/به‌روز می‌شود و یک JWT (HS256، انقضا، `iss`) برمی‌گردد. بقیه‌ی API فقط با `Authorization: Bearer` کار می‌کند.
5. هیچ داده‌ی ارسالی کلاینت بدون این اعتبارسنجی معتبر نیست. `initData` هرگز لاگ نمی‌شود؛ فقط یک «کُد دلیل» کوتاه در `activity_logs` می‌ماند.
مدیر بودن فقط از `ADMIN_USER_ID` (و جدول `admins`) سمت سرور تعیین می‌شود، نه از کلاینت.

## API مرحله‌ی ۱
| مسیر | کار |
|---|---|
| `GET /api/health` | سلامت سرویس و دیتابیس |
| `POST /api/auth/telegram` | ورود با initData (محدودیت نرخ) |
| `GET /api/me` · `PATCH /api/me` | پروفایل · تغییر زبان |
| `DELETE /api/me` | حذف کامل حساب و داده‌ها (با `{"confirm":true}`) |
| `GET /api/home` | داده‌ی صفحه‌ی خانه (همه از دیتابیس) |
مستندات تعاملی (فقط خارج از production): `/api/docs`.

## مدل داده (۲۴ جدول)
users، admins، user_preferences، artists، genres، moods، songs، music_dna_profiles، favorites، battles، battle_votes، quizzes، quiz_questions، quiz_attempts، user_points، user_achievements، mixtapes، mixtape_songs، music_matches، trend_sources، trending_tracks، publication_queue، activity_logs، app_settings.
قواعد در خود دیتابیس اعمال می‌شوند (نه فقط در کد):
- کلید خارجی (SQLite: `PRAGMA foreign_keys=ON`)؛ حذف کاربر ← CASCADE برای داده‌ی شخصی، `SET NULL` برای لاگ‌ها.
- یکتایی: یک رأی برای هر کاربر در هر نبرد؛ یک تلاش برای هر کاربر در هر آزمون؛ امتیاز تکراری با `ref_key`؛ یک جفت Match = یک ردیف (`low < high`)؛ آهنگ تکراری (خواننده+عنوان نرمال‌شده).
- CHECK: وضعیت‌ها/انواع، `song_a ≠ song_b`، `correct_index ∈ [0,3]`، سؤال «approved» بدون `source_note` ممنوع، **فایل آهنگ فقط با `license_status='licensed'`**، **انتشار/تأیید در `publication_queue` بدون `approved_at` ممنوع** (انتشار خودکار در سطح دیتابیس هم ناممکن است).
- Music Match: پیش‌فرض `match_opt_in=0` و `profile_visibility='hidden'` (عضویت فقط با رضایت صریح).
- زمان‌ها همیشه UTC (نوع `UTCDateTime` datetime بدون منطقه را رد می‌کند).
- مهاجرت با Alembic؛ تست خودکار تضمین می‌کند مهاجرت با مدل‌ها یکی است.

## نقشه‌ی مراحل (فقط مرحله‌ی ۱ پیاده شده)
| مرحله | محتوا | وضعیت |
|---|---|---|
| ۱ | ساختار، Backend، Bot، Mini App، احراز هویت، دیتابیس، خانه و منو | ✅ این نسخه |
| ۲ | Music DNA، Mood، Roulette (موتور توصیه‌ی داخلی با رابط Provider) | ⏳ |
| ۳ | Battle، Quiz، Bia Points (امتیاز فقط سمت سرور، idempotent با `ref_key`) | ⏳ |
| ۴ | Music Match، Mixtape | ⏳ |
| ۵ | Trend Radar، رشد کانال، پنل مدیریت کامل در ربات، صف انتشار با تأیید | ⏳ |
| ۶ | تست نهایی، امنیت، استقرار | ⏳ |
تبهای «کشف»، «بازی‌ها» و «میکس‌تیپ» در مرحله‌ی ۱ فقط صفحه‌ی صادقانه‌ی «هنوز ساخته نشده» هستند و کاشی‌های «دسترسی سریع» غیرفعال و برچسب‌دار.

## امنیت (مرحله‌ی ۱)
Secretها فقط در `.env`؛ `.env` در `.gitignore`؛ هدرهای `nosniff`/`no-referrer`/CSP؛ `Cache-Control: no-store` برای API؛ خطاهای اعتبارسنجی ورودی کاربر را بازتاب نمی‌دهند؛ محدودیت نرخ (ورود و API)؛ لاگ `httpx` خاموش (URL شامل توکن است)؛ حذف حساب.
محدودیت شناخته‌شده: محدودیت نرخ درون‌حافظه است (برای چند پردازش باید Redis شود)؛ نشست JWT قبل از انقضا ابطال‌پذیر نیست (انقضای پیش‌فرض ۱۲ ساعت؛ حذف حساب توکن را بی‌اثر می‌کند).
