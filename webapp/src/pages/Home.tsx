import { useCallback, useEffect, useState } from "react";
import { ApiError, Feature, Home as HomeData, User, getHome } from "../api";
import { Cover, EmptyState, ErrorState, Loading, Section, SongRow } from "../components/ui";
import { Key } from "../i18n";
import { useLang } from "../lang";
import { openExternal } from "../telegram";
import { Tab } from "../components/Tabs";

const ICON: Record<string, string> = { music_dna: "🧬", mood: "🎭", roulette: "🎡", battle: "⚔️", quiz: "🧠", match: "🤝", mixtape: "📼", trend_radar: "📡" };
const TARGET: Record<string, Tab> = { music_dna: "discover", mood: "discover", roulette: "discover", battle: "games", quiz: "games", match: "profile", mixtape: "mixtape", trend_radar: "discover" };

export function errText(e: unknown, t: ReturnType<typeof useLang>["t"]): string {
  const k = e instanceof ApiError ? e.kind : "network";
  return t(k === "rate" ? "err.rate" : k === "auth" ? "err.auth" : k === "server" ? "err.server" : k === "network" ? "err.network" : "common.error");
}

export function Home({ user, go }: { user: User; go: (t: Tab) => void }) {
  const { t, n } = useLang();
  const [data, setData] = useState<HomeData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => { setErr(null); setData(null); getHome().then(setData).catch((e) => setErr(errText(e, t))); }, [t]);
  useEffect(load, [load]);
  if (err) return <ErrorState text={err} onRetry={load} />;
  if (!data) return <Loading />;
  const sod = data.song_of_day;
  return (
    <div className="stack">
      <header className="hero">
        <div className="hero-glow" aria-hidden />
        <p className="hello">{t("home.hello", { name: user.first_name || "" })}</p>
        <h1>{t("appName")}</h1>
        <p className="tag">{t("tagline")}</p>
      </header>
      {data.has_demo_data && <p className="notice">{t("home.demoNote")}</p>}

      <Section title={t("home.songOfDay")} hint={sod ? t("home.basisDaily") : undefined}>
        {sod ? (
          <div className="sod">
            <Cover song={sod} size={96} />
            <div className="grow"><div className="sod-title">{sod.title}</div><div className="meta">{[sod.artist, sod.genre, sod.mood].filter(Boolean).join(" · ")}</div>
              {sod.source_url && <button className="btn small" onClick={() => openExternal(sod.source_url!)}>↗ {t("song.source")}</button>}</div>
          </div>
        ) : <EmptyState icon="🎧" text={t("home.noSong")} />}
      </Section>

      <Section title={t("home.quick")}>
        <div className="grid">
          {data.features.map((f: Feature) => (
            <button key={f.key} className="tile" disabled={!f.available} onClick={() => go(TARGET[f.key])} aria-disabled={!f.available}>
              <span className="tile-icon" aria-hidden>{ICON[f.key]}</span>
              <span className="tile-name">{t(`feature.${f.key}` as Key)}</span>
              <span className="chip">{f.available ? "" : `${t("feature.soon")} · ${t("feature.stage", { n: n(f.stage) })}`}</span>
            </button>
          ))}
        </div>
      </Section>

      <Section title={t("home.trending")}>
        {data.trending_available ? data.trending.map((x) => (
          <div className="row-card" key={`${x.region}${x.rank}`}><div className="rank">{n(x.rank)}</div>
            <div className="grow"><div className="title">{x.title}</div><div className="meta">{[x.artist, x.source, x.region].filter(Boolean).join(" · ")}</div></div>
            {x.url && <button className="icon-btn" aria-label={t("song.source")} onClick={() => openExternal(x.url!)}>↗</button>}</div>
        )) : <EmptyState icon="📡" text={t("home.noTrend")} />}
      </Section>

      <Section title={t("home.challenge")}>
        {data.daily_challenge ? null : <EmptyState icon="🏆" text={t("home.noChallenge")} />}
      </Section>

      <Section title={t("home.suggested")}>
        {data.suggested.length ? data.suggested.map((s) => <SongRow key={s.id} song={s} />) : <EmptyState icon="💿" text={t("home.noSuggested")} />}
      </Section>
    </div>
  );
}
