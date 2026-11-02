import { useState } from "react";
import { User, deleteAccount, setLanguage } from "../api";
import { Lang } from "../i18n";
import { useLang } from "../lang";
import { errText } from "./Home";

export function Profile({ user, onLang, onDeleted, toast }: { user: User; onLang: (l: Lang) => void; onDeleted: () => void; toast: (s: string) => void }) {
  const { t, n, lang } = useLang();
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const joined = new Date(user.created_at).toLocaleDateString(lang === "fa" ? "fa-IR" : "en-US");

  async function pick(l: Lang) {
    if (l === lang || busy) return;
    setBusy(true);
    try { await setLanguage(l); onLang(l); toast(t("common.saved")); } catch (e) { toast(errText(e, t)); } finally { setBusy(false); }
  }
  async function del() {
    setBusy(true);
    try { await deleteAccount(); onDeleted(); } catch (e) { toast(errText(e, t)); setBusy(false); }
  }
  return (
    <div className="stack">
      <h1 className="page-title">{t("profile.title")}</h1>
      <div className="card profile">
        <div className="avatar" aria-hidden>{(user.first_name || "?").slice(0, 1).toUpperCase()}</div>
        <div className="grow"><div className="title">{user.first_name}{user.is_admin && <span className="chip">{t("profile.admin")}</span>}</div>
          {user.username && <div className="meta" dir="ltr">@{user.username}</div>}</div>
      </div>
      <div className="card kv"><span>{t("profile.points")}</span><b>{n(user.points)}</b></div>
      <div className="card kv"><span>{t("profile.joined")}</span><b>{joined}</b></div>
      <div className="card">
        <div className="label">{t("profile.language")}</div>
        <div className="seg" role="group" aria-label={t("profile.language")}>
          <button className={lang === "fa" ? "on" : ""} disabled={busy} onClick={() => pick("fa")}>فارسی</button>
          <button className={lang === "en" ? "on" : ""} disabled={busy} onClick={() => pick("en")}>English</button>
        </div>
      </div>
      <div className="card danger">
        <div className="label">{t("profile.deleteTitle")}</div>
        <p className="hint">{t("profile.deleteBody")}</p>
        {!confirm ? <button className="btn ghost-danger" onClick={() => setConfirm(true)}>{t("profile.delete")}</button> : (
          <div className="actions"><button className="btn danger-btn" disabled={busy} onClick={del}>{t("profile.deleteConfirm")}</button>
            <button className="btn ghost" disabled={busy} onClick={() => setConfirm(false)}>{t("profile.cancel")}</button></div>
        )}
      </div>
    </div>
  );
}
