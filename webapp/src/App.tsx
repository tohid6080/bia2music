import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, User, login, setToken } from "./api";
import { TabBar, Tab } from "./components/Tabs";
import { EmptyState, ErrorState, Loading, Toast } from "./components/ui";
import { dirOf, Lang, pickLang } from "./i18n";
import { LangCtx, makeCtx } from "./lang";
import { Home, errText } from "./pages/Home";
import { Profile } from "./pages/Profile";
import { Soon } from "./pages/Soon";
import { getInitData, setupTelegram, tg } from "./telegram";

type Boot = { s: "loading" } | { s: "outside" } | { s: "error"; msg: string } | { s: "ready"; user: User } | { s: "deleted" };

export default function App() {
  const [boot, setBoot] = useState<Boot>({ s: "loading" });
  const [lang, setLang] = useState<Lang>(pickLang(tg()?.initDataUnsafe.user?.language_code));
  const [tab, setTab] = useState<Tab>("home");
  const [toast, setToast] = useState<string | null>(null);
  const ctx = useMemo(() => makeCtx(lang), [lang]);

  useEffect(() => { document.documentElement.lang = lang; document.documentElement.dir = dirOf(lang); }, [lang]);
  const say = useCallback((s: string) => { setToast(s); window.setTimeout(() => setToast(null), 2200); }, []);

  const start = useCallback(() => {
    setBoot({ s: "loading" });
    setupTelegram();
    if (!getInitData()) { setBoot({ s: "outside" }); return; }
    login().then((user) => { setLang(user.language); setBoot({ s: "ready", user }); })
      .catch((e) => setBoot({ s: "error", msg: errText(e instanceof ApiError ? e : new ApiError(0, "network"), ctx.t) }));
  }, [ctx.t]);
  useEffect(start, []); // eslint-disable-line react-hooks/exhaustive-deps

  let body;
  if (boot.s === "loading") body = <Loading />;
  else if (boot.s === "outside") body = <EmptyState icon="📱" text={`${ctx.t("outside.title")}\n${ctx.t("outside.body")}`} />;
  else if (boot.s === "error") body = <ErrorState text={boot.msg} onRetry={start} />;
  else if (boot.s === "deleted") body = <EmptyState icon="🗑" text={ctx.t("profile.deleted")} />;
  else {
    const user = boot.user;
    body = (
      <>
        <main className="page" key={tab}>
          {tab === "home" && <Home user={user} go={setTab} />}
          {(tab === "discover" || tab === "games" || tab === "mixtape") && <Soon page={tab} />}
          {tab === "profile" && <Profile user={user} toast={say} onLang={(l) => { setLang(l); setBoot({ s: "ready", user: { ...user, language: l } }); }}
            onDeleted={() => { setToken(null); setBoot({ s: "deleted" }); }} />}
        </main>
        <TabBar tab={tab} onChange={setTab} />
      </>
    );
  }
  return <LangCtx.Provider value={ctx}>{boot.s === "ready" ? body : <main className="page">{body}</main>}<Toast text={toast} /></LangCtx.Provider>;
}
