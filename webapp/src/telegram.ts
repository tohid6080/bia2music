/** نازک‌لایه‌ی تایپ‌شده روی Telegram WebApp SDK رسمی (telegram-web-app.js). */
export interface TgWebApp {
  initData: string;
  initDataUnsafe: { user?: { language_code?: string; first_name?: string } };
  colorScheme?: string;
  ready(): void;
  expand(): void;
  disableVerticalSwipes?(): void;
  setHeaderColor?(c: string): void;
  setBackgroundColor?(c: string): void;
  HapticFeedback?: { impactOccurred(s: string): void; notificationOccurred(s: string): void };
  openLink?(url: string): void;
  showConfirm?(msg: string, cb: (ok: boolean) => void): void;
  close(): void;
}
declare global { interface Window { Telegram?: { WebApp?: TgWebApp } } }

export const tg = (): TgWebApp | undefined => window.Telegram?.WebApp;

/** initData واقعی تلگرام؛ در توسعه می‌توان با VITE_DEV_INIT_DATA (امضاشده با `python -m b2m.cli dev-initdata`) جایگزین کرد. */
export function getInitData(): string {
  const real = tg()?.initData;
  if (real) return real;
  return import.meta.env.DEV ? ((import.meta.env.VITE_DEV_INIT_DATA as string | undefined) ?? "") : "";
}

export function setupTelegram(): void {
  const w = tg();
  if (!w) return;
  try {
    w.ready();
    w.expand();
    w.disableVerticalSwipes?.();
    w.setHeaderColor?.("#0b0b14");
    w.setBackgroundColor?.("#0b0b14");
  } catch { /* نسخه‌های قدیمی تلگرام برخی متدها را ندارند */ }
}

export const haptic = (kind: "light" | "success" = "light") => {
  try { kind === "success" ? tg()?.HapticFeedback?.notificationOccurred("success") : tg()?.HapticFeedback?.impactOccurred("light"); } catch { /* */ }
};

export function openExternal(url: string): void {
  if (!/^https?:\/\//i.test(url)) return;                    // فقط http(s)
  const w = tg();
  if (w?.openLink) w.openLink(url); else window.open(url, "_blank", "noopener,noreferrer");
}
