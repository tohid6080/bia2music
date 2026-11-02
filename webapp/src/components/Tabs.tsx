import { Key } from "../i18n";
import { useLang } from "../lang";
import { haptic } from "../telegram";

export type Tab = "home" | "discover" | "games" | "mixtape" | "profile";
const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;
const ICONS: Record<Tab, JSX.Element> = {
  home: <svg viewBox="0 0 24 24" {...P}><path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" /></svg>,
  discover: <svg viewBox="0 0 24 24" {...P}><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5l-2 5-5 2 2-5z" /></svg>,
  games: <svg viewBox="0 0 24 24" {...P}><rect x="3" y="8" width="18" height="10" rx="4" /><path d="M8 11v4M6 13h4M16 12h.01M18 14h.01" /></svg>,
  mixtape: <svg viewBox="0 0 24 24" {...P}><rect x="3" y="5" width="18" height="14" rx="3" /><circle cx="9" cy="12" r="2" /><circle cx="15" cy="12" r="2" /><path d="M9 16h6" /></svg>,
  profile: <svg viewBox="0 0 24 24" {...P}><circle cx="12" cy="8" r="4" /><path d="M4 21c1-4 4-6 8-6s7 2 8 6" /></svg>,
};
export const TABS: Tab[] = ["home", "discover", "games", "mixtape", "profile"];

export function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const { t } = useLang();
  return (
    <nav className="tabbar" aria-label="main">
      {TABS.map((k) => (
        <button key={k} className={k === tab ? "active" : ""} aria-current={k === tab ? "page" : undefined} onClick={() => { haptic(); onChange(k); }}>
          {ICONS[k]}<span>{t(`tab.${k}` as Key)}</span>
        </button>
      ))}
    </nav>
  );
}
