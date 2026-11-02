import { createContext, useContext } from "react";
import { Key, Lang, num, translate } from "./i18n";

export interface Ctx { lang: Lang; t: (k: Key, v?: Record<string, string | number>) => string; n: (x: number | string) => string }
export const LangCtx = createContext<Ctx>({ lang: "fa", t: (k) => k, n: String });
export const useLang = () => useContext(LangCtx);
export const makeCtx = (lang: Lang): Ctx => ({ lang, t: (k, v) => translate(lang, k, v), n: (x) => num(lang, x) });
