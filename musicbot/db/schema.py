"""طرح دیتابیس. SQL استاندارد و ساده تا انتقال به PostgreSQL آسان باشد.

نسخه‌بندی با PRAGMA user_version؛ برای تغییرات بعدی، یک مورد به MIGRATIONS اضافه کنید.
"""

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'owner',
    display_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    username TEXT,
    first_name TEXT,
    language_code TEXT,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS languages (
    code TEXT PRIMARY KEY,
    name_fa TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_fa TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS moods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_fa TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- status: draft | ready | scheduled | published | archived
CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    artist TEXT,
    language_code TEXT REFERENCES languages(code),
    genre_id INTEGER REFERENCES genres(id),
    mood_id INTEGER REFERENCES moods(id),
    telegram_file_id TEXT,
    file_unique_id TEXT UNIQUE,
    file_hash TEXT,
    duration_seconds INTEGER,
    file_size INTEGER,
    caption TEXT,
    hashtags TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    channel_message_id INTEGER,
    post_url TEXT,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_songs_status ON songs(status);
CREATE INDEX IF NOT EXISTS idx_songs_file_hash ON songs(file_hash);

-- status: pending | approved | published | rejected | cancelled | failed
-- محافظ: وضعیت published بدون approved_at (تأیید صریح مدیر) در دیتابیس هم رد می‌شود.
CREATE TABLE IF NOT EXISTS publication_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER NOT NULL REFERENCES songs(id),
    channel_ref TEXT NOT NULL,
    scheduled_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TEXT,
    published_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    CHECK (status <> 'published' OR (approved_at IS NOT NULL AND approved_by IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS channel_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_ref TEXT NOT NULL,
    title TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS playlist_songs (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (playlist_id, song_id)
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    level TEXT NOT NULL DEFAULT 'info',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON activity_logs(id DESC);

CREATE TABLE IF NOT EXISTS ai_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

# (کد، نام فارسی)
SEED_LANGUAGES = [("fa", "فارسی"), ("en", "انگلیسی"), ("tr", "ترکی"), ("ar", "عربی"), ("other", "سایر زبان‌ها")]
SEED_GENRES = [
    ("pop", "پاپ"), ("rap", "رپ"), ("rock", "راک"), ("traditional", "سنتی"),
    ("classical", "کلاسیک"), ("electronic", "الکترونیک"), ("instrumental", "بی‌کلام"), ("other", "سایر سبک‌ها"),
]
SEED_MOODS = [
    ("romantic", "عاشقانه"), ("sad", "غمگین"), ("happy", "شاد"), ("calm", "آرامش‌بخش"),
    ("motivational", "انگیزشی"), ("emotional", "احساسی"), ("nostalgic", "نوستالژیک"),
    ("driving", "مناسب رانندگی"), ("workout", "مناسب ورزش"),
]

MIGRATIONS = {1: SCHEMA_V1}

# مرحله ۲: ستون‌های نرمال‌شده برای جست‌وجو و تشخیص آهنگ مشابه (املای فارسی/عربی یکسان می‌شود)
SCHEMA_V2 = """
ALTER TABLE songs ADD COLUMN title_norm TEXT;
ALTER TABLE songs ADD COLUMN artist_norm TEXT;
CREATE INDEX IF NOT EXISTS idx_songs_norm ON songs(artist_norm, title_norm);
CREATE INDEX IF NOT EXISTS idx_songs_language ON songs(language_code);
CREATE INDEX IF NOT EXISTS idx_songs_genre ON songs(genre_id);
CREATE INDEX IF NOT EXISTS idx_songs_mood ON songs(mood_id);
"""

MIGRATIONS[2] = SCHEMA_V2

# مرحله ۴: تنظیمات ربات، رضایت و علایق کاربران (فقط با رضایت صریح)، پسندها، درخواست آهنگ
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
ALTER TABLE users ADD COLUMN consent_at TEXT;

CREATE TABLE IF NOT EXISTS user_interests (
    telegram_user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- language | genre | mood
    ref TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (telegram_user_id, kind, ref)
);

CREATE TABLE IF NOT EXISTS song_likes (
    telegram_user_id INTEGER NOT NULL,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (telegram_user_id, song_id)
);
CREATE INDEX IF NOT EXISTS idx_likes_song ON song_likes(song_id);

-- status: new | done | dismissed
CREATE TABLE IF NOT EXISTS song_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_requests_user ON song_requests(telegram_user_id, created_at);
"""

MIGRATIONS[3] = SCHEMA_V3

# مرحله ۵: آمار (بدون هویت)، کمپین‌های تبلیغ/همکاری، پرداخت اشتراک ویژه (Telegram Stars)
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    day TEXT NOT NULL,
    metric TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, metric)
);

CREATE TABLE IF NOT EXISTS member_snapshots (
    day TEXT PRIMARY KEY,
    members INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS post_stats (
    channel_message_id INTEGER PRIMARY KEY,
    reactions INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- kind: ad | collab ؛ status: draft | publishing | active | done | cancelled
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'ad',
    title TEXT NOT NULL,
    partner_link TEXT,
    notes TEXT,
    price INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',
    post_text TEXT,
    button_label TEXT,
    button_url TEXT,
    starts_at TEXT,
    ends_at TEXT,
    channel_message_id INTEGER,
    members_start INTEGER,
    members_end INTEGER,
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status, kind);

-- status: paid | refunded
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    days INTEGER NOT NULL,
    charge_id TEXT NOT NULL UNIQUE,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'paid',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(telegram_user_id);

ALTER TABLE users ADD COLUMN premium_until TEXT;
ALTER TABLE playlists ADD COLUMN is_premium INTEGER NOT NULL DEFAULT 0;
"""

MIGRATIONS[4] = SCHEMA_V4

# مرحله AI: علامت «توسط AI بررسی شد» تا آهنگ‌های بی‌پاسخ دوباره هزینه نکنند
SCHEMA_V5 = """
ALTER TABLE songs ADD COLUMN ai_checked INTEGER NOT NULL DEFAULT 0;
"""

MIGRATIONS[5] = SCHEMA_V5

# مرحله ۶: کمپین‌های جذب مخاطب و شمارش ورود/خروج اعضا (تجمیعی؛ بدون ذخیره‌ی هویت)
SCHEMA_V6 = """
CREATE TABLE IF NOT EXISTS growth_campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    invite_link TEXT UNIQUE,
    link_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',     -- active | revoked
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    revoked_at TEXT
);

-- campaign_id=0: منبع نامشخص/ارگانیک (ورود بدون لینک، یا لینکی که این ربات نساخته)
CREATE TABLE IF NOT EXISTS member_events_daily (
    day TEXT NOT NULL,
    campaign_id INTEGER NOT NULL DEFAULT 0,
    joins INTEGER NOT NULL DEFAULT 0,
    leaves INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, campaign_id)
);

-- فقط اگر مدیر صریحاً روشن کند: هش نمکی یک‌طرفه (نه شناسه)؛ با خروج عضو پاک می‌شود
CREATE TABLE IF NOT EXISTS member_hashes (
    hash TEXT PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    joined_day TEXT NOT NULL
);
"""

MIGRATIONS[6] = SCHEMA_V6

# مرحله ۷: متن‌های تبلیغ (قابل ویرایش)، برنامه‌ی هفتگی، نقاط عطف رشد (قابل تغییر)
SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS growth_texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    variant INTEGER NOT NULL DEFAULT 0,
    campaign_id INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS growth_plans (
    week TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- نقطه‌های عطف فقط پیشنهادند و قابل تغییر؛ رسیدن به آن‌ها هیچ انتشار خودکاری را فعال نمی‌کند
CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    members INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    note TEXT
);
INSERT OR IGNORE INTO milestones(members,title,note) VALUES
 (22,  'مرحله شروع و آزمایش محتوا', 'سبک‌ها و زمان‌های مختلف را آزمایش کنید و ثبات انتشار را بسازید.'),
 (100, 'بررسی اولیه علایق مخاطبان', 'علایق تجمیعی و پسندها را بررسی کنید و محتوا را به آن‌ها نزدیک‌تر کنید.'),
 (500, 'توسعه برنامه انتشار و تنوع موسیقی', 'برنامه‌ی هفتگی ثابت و تنوع بیشتر سبک و زبان.'),
 (1000,'تحلیل جدی‌تر عملکرد محتوا و برنامه رشد', 'نتایج آزمایش‌ها را ثبت و مقایسه کنید؛ همکاری‌ها را منظم ارزیابی کنید.');
"""

MIGRATIONS[7] = SCHEMA_V7

# مرحله ۸: رادار موسیقی ترند (وضعیت منابع، عکس‌های کش‌شده‌ی نمودار، ثبت دستی)
SCHEMA_V8 = """
-- تعریف منابع در کد است؛ اینجا فقط وضعیت (فعال‌بودن با تأیید صریح مدیر، مناطق، آخرین دریافت)
CREATE TABLE IF NOT EXISTS radar_sources (
    source_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    regions TEXT,
    last_fetch_at TEXT,
    last_ok_at TEXT,
    last_status TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS radar_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    region TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    ok INTEGER NOT NULL,
    entry_count INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_radar_snap ON radar_snapshots(source_id, region, id DESC);

CREATE TABLE IF NOT EXISTS radar_entries (
    snapshot_id INTEGER NOT NULL REFERENCES radar_snapshots(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    ext_id TEXT,
    title TEXT NOT NULL,
    artist TEXT,
    url TEXT,
    native_score REAL,
    native_label TEXT,
    published_at TEXT,
    genre TEXT,
    title_norm TEXT,
    artist_norm TEXT,
    PRIMARY KEY (snapshot_id, rank)
);

CREATE TABLE IF NOT EXISTS radar_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT,
    url TEXT,
    source_note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

MIGRATIONS[8] = SCHEMA_V8

# مرحله ۹ + اعمال دکمه روی پست‌های قبلی: پیشنهادهای رادار و ردیابی پست‌های ویرایش‌شده
SCHEMA_V9 = """
-- هر پیشنهاد یک آهنگ یکتا (کلید نرمال‌شده‌ی خواننده|عنوان) با وضعیت و مجوز
-- status: new | saved | in_archive | drafted | rejected ؛ license_status: unknown | official_link | licensed_by_admin
CREATE TABLE IF NOT EXISTS radar_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_norm TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    artist TEXT,
    kind TEXT NOT NULL DEFAULT 'foreign',
    kind_override INTEGER NOT NULL DEFAULT 0,
    source_id TEXT,
    region TEXT,
    best_rank INTEGER,
    url TEXT,
    native_label TEXT,
    published_at TEXT,
    genre TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    license_status TEXT NOT NULL DEFAULT 'unknown',
    license_note TEXT,
    song_id INTEGER,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    last_seen_at TEXT,
    reported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_radar_sug_status ON radar_suggestions(status);

-- پست‌های کانال که دکمه‌ی ربات روی آن‌ها اعمال (یا رد) شده؛ status: applied | skipped
CREATE TABLE IF NOT EXISTS promo_applied (
    channel_message_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
"""

MIGRATIONS[9] = SCHEMA_V9


# مرحله ۱۱: فعالیت کاربران داخل ربات (فقط با رضایت جداگانه‌ی خودِ کاربر؛ پیش‌فرض خاموش)
SCHEMA_V10 = """
ALTER TABLE users ADD COLUMN activity_consent_at TEXT;

CREATE TABLE IF NOT EXISTS song_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('view','like','download')),
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_events_song ON song_events(song_id, at);
CREATE INDEX IF NOT EXISTS idx_events_user ON song_events(telegram_user_id);
"""

MIGRATIONS[10] = SCHEMA_V10
