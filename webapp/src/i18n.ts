export type Lang = "fa" | "en";

const fa = {
  appName: "Bia2Music", tagline: "Your Music Universe",
  "tab.home": "خانه", "tab.discover": "کشف", "tab.games": "بازی‌ها", "tab.mixtape": "میکس‌تیپ", "tab.profile": "پروفایل",
  "home.hello": "سلام {name}", "home.songOfDay": "پیشنهاد روز", "home.trending": "موسیقی‌های ترند", "home.challenge": "چالش روز",
  "home.suggested": "جدیدترین‌ها در آرشیو", "home.quick": "دسترسی سریع",
  "home.noSong": "هنوز آهنگی در آرشیو منتشر نشده است. به‌محض افزودن آهنگ توسط مدیر، پیشنهاد روز اینجا نمایش داده می‌شود.",
  "home.noTrend": "داده‌ی ترند هنوز در دسترس نیست. رادار ترند در مرحله‌ی ۵ فعال می‌شود و هرگز رتبه‌ی ساختگی نمایش نمی‌دهد.",
  "home.noChallenge": "امروز چالشی فعال نیست. نبرد و آزمون روزانه در مرحله‌ی ۳ اضافه می‌شود.",
  "home.noSuggested": "آرشیو هنوز خالی است.",
  "home.demoNote": "⚠️ این فهرست شامل داده‌ی نمونه‌ی توسعه است (آشکارا ساختگی).",
  "home.basisDaily": "انتخاب روزانه از آرشیو (هنوز شخصی‌سازی نشده)",
  "feature.music_dna": "Music DNA", "feature.mood": "حال‌وهوا", "feature.roulette": "گردونه‌ی کشف", "feature.battle": "نبرد آهنگ‌ها",
  "feature.quiz": "آزمون موسیقی", "feature.match": "Music Match", "feature.mixtape": "میکس‌تیپ", "feature.trend_radar": "رادار ترند",
  "feature.stage": "مرحله {n}", "feature.soon": "به‌زودی",
  "soon.title": "این بخش هنوز ساخته نشده", "soon.body": "{what} در مرحله‌ی {n} پروژه اضافه می‌شود. در حال حاضر هیچ دکمه‌ی نمایشی‌ای در این صفحه وجود ندارد.",
  "soon.discover": "کشف موسیقی (Music DNA، حال‌وهوا و گردونه)", "soon.games": "بازی‌ها (نبرد و آزمون)", "soon.mixtape": "میکس‌تیپ شخصی",
  "profile.title": "پروفایل", "profile.language": "زبان", "profile.points": "امتیاز Bia", "profile.joined": "عضویت از", "profile.admin": "مدیر",
  "profile.deleteTitle": "حذف حساب و اطلاعات", "profile.deleteBody": "با حذف حساب، تمام اطلاعات شما از Bia2Music پاک می‌شود و قابل بازگشت نیست.",
  "profile.delete": "حذف حساب من", "profile.deleteConfirm": "بله، برای همیشه حذف شود", "profile.cancel": "انصراف", "profile.deleted": "حساب شما حذف شد. می‌توانید دوباره از تلگرام وارد شوید.",
  "common.retry": "تلاش دوباره", "common.loading": "در حال بارگذاری…", "common.saved": "ذخیره شد", "common.error": "مشکلی پیش آمد.",
  "err.network": "ارتباط با سرور برقرار نشد. اینترنت را بررسی و دوباره تلاش کنید.",
  "err.rate": "درخواست‌ها زیاد بود؛ چند لحظه بعد دوباره تلاش کنید.",
  "err.auth": "ورود ناموفق بود. برنامه را از ربات دوباره باز کنید.",
  "err.server": "خطای سرور. کمی بعد دوباره تلاش کنید.",
  "outside.title": "این برنامه باید از تلگرام باز شود", "outside.body": "ربات را در تلگرام Start کنید و دکمه‌ی «باز کردن Bia2Music» را بزنید.",
  "song.source": "منبع", "song.demo": "نمونه",
};

const en: typeof fa = {
  appName: "Bia2Music", tagline: "Your Music Universe",
  "tab.home": "Home", "tab.discover": "Discover", "tab.games": "Games", "tab.mixtape": "Mixtape", "tab.profile": "Profile",
  "home.hello": "Hi {name}", "home.songOfDay": "Song of the day", "home.trending": "Trending music", "home.challenge": "Today's challenge",
  "home.suggested": "Latest in the archive", "home.quick": "Quick access",
  "home.noSong": "No songs have been published to the archive yet. The song of the day will appear here as soon as the admin adds music.",
  "home.noTrend": "Trend data isn't available yet. Trend Radar arrives in stage 5 and never shows invented rankings.",
  "home.noChallenge": "No active challenge today. Daily battle and quiz arrive in stage 3.",
  "home.noSuggested": "The archive is still empty.",
  "home.demoNote": "⚠️ This list includes development sample data (clearly fake).",
  "home.basisDaily": "Daily pick from the archive (not personalised yet)",
  "feature.music_dna": "Music DNA", "feature.mood": "Mood", "feature.roulette": "Discover Roulette", "feature.battle": "Music Battle",
  "feature.quiz": "Music Quiz", "feature.match": "Music Match", "feature.mixtape": "Mixtape", "feature.trend_radar": "Trend Radar",
  "feature.stage": "Stage {n}", "feature.soon": "Coming soon",
  "soon.title": "This section isn't built yet", "soon.body": "{what} will be added in stage {n} of the project. There are no placeholder buttons on this page.",
  "soon.discover": "Discover (Music DNA, Mood and Roulette)", "soon.games": "Games (Battle and Quiz)", "soon.mixtape": "Personal Mixtape",
  "profile.title": "Profile", "profile.language": "Language", "profile.points": "Bia Points", "profile.joined": "Member since", "profile.admin": "Admin",
  "profile.deleteTitle": "Delete account and data", "profile.deleteBody": "Deleting your account permanently erases all your data from Bia2Music. This cannot be undone.",
  "profile.delete": "Delete my account", "profile.deleteConfirm": "Yes, delete forever", "profile.cancel": "Cancel", "profile.deleted": "Your account was deleted. You can sign in again from Telegram.",
  "common.retry": "Try again", "common.loading": "Loading…", "common.saved": "Saved", "common.error": "Something went wrong.",
  "err.network": "Couldn't reach the server. Check your connection and try again.",
  "err.rate": "Too many requests; please try again in a moment.",
  "err.auth": "Sign-in failed. Reopen the app from the bot.",
  "err.server": "Server error. Please try again shortly.",
  "outside.title": "Open this app from Telegram", "outside.body": "Start the bot in Telegram and tap “Open Bia2Music”.",
  "song.source": "Source", "song.demo": "Sample",
};

export type Key = keyof typeof fa;
export const DICT: Record<Lang, Record<Key, string>> = { fa, en };
export const dirOf = (l: Lang): "rtl" | "ltr" => (l === "fa" ? "rtl" : "ltr");

export function translate(lang: Lang, key: Key, vars?: Record<string, string | number>): string {
  let s = DICT[lang][key] ?? DICT.fa[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
  return s;
}

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export function num(lang: Lang, n: number | string): string {
  const s = String(n);
  return lang === "fa" ? s.replace(/\d/g, (d) => FA_DIGITS[Number(d)]) : s;
}

export function pickLang(telegramLang?: string | null): Lang {
  return (telegramLang ?? "fa").toLowerCase().startsWith("fa") || !telegramLang ? "fa" : "en";
}
