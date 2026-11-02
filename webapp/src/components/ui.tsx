import { ReactNode } from "react";
import { Song } from "../api";
import { useLang } from "../lang";
import { openExternal } from "../telegram";

export const Skeleton = ({ h = 90, w = "100%" }: { h?: number; w?: string }) => <div className="skeleton" style={{ height: h, width: w }} aria-hidden />;

export function Loading() {
  const { t } = useLang();
  return <div className="stack" role="status" aria-label={t("common.loading")}><Skeleton h={150} /><Skeleton h={22} w="40%" /><Skeleton h={72} /><Skeleton h={72} /></div>;
}

export function EmptyState({ icon, text }: { icon: string; text: string }) {
  return <div className="empty"><div className="empty-icon" aria-hidden>{icon}</div><p>{text}</p></div>;
}

export function ErrorState({ text, onRetry }: { text: string; onRetry: () => void }) {
  const { t } = useLang();
  return <div className="empty error" role="alert"><div className="empty-icon" aria-hidden>⚠️</div><p>{text}</p><button className="btn" onClick={onRetry}>{t("common.retry")}</button></div>;
}

export const Section = ({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) => (
  <section className="section"><h2>{title}</h2>{hint && <p className="hint">{hint}</p>}{children}</section>
);

/** کاور تولیدی از شناسه (گرادیان)؛ اگر cover_url باشد تصویر واقعی. */
export function Cover({ song, size = 56 }: { song: Pick<Song, "id" | "cover_url" | "title">; size?: number }) {
  const hue = (song.id * 47) % 360;
  const style = { width: size, height: size, background: `linear-gradient(135deg, hsl(${hue} 70% 45%), hsl(${(hue + 60) % 360} 70% 35%))` };
  return <div className="cover" style={style} aria-hidden>{song.cover_url ? <img src={song.cover_url} alt="" loading="lazy" referrerPolicy="no-referrer" /> : <span>♪</span>}</div>;
}

export function SongRow({ song }: { song: Song }) {
  const { t } = useLang();
  const meta = [song.artist, song.genre, song.mood].filter(Boolean).join(" · ");
  return (
    <div className="row-card">
      <Cover song={song} />
      <div className="grow"><div className="title">{song.title}{song.is_demo && <span className="chip demo">{t("song.demo")}</span>}</div><div className="meta">{meta}</div></div>
      {song.source_url && <button className="icon-btn" aria-label={t("song.source")} onClick={() => openExternal(song.source_url!)}>↗</button>}
    </div>
  );
}

export function Toast({ text }: { text: string | null }) {
  return <div className={`toast ${text ? "show" : ""}`} role="status" aria-live="polite">{text}</div>;
}
