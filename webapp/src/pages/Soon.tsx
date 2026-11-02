import { EmptyState } from "../components/ui";
import { useLang } from "../lang";

const INFO = { discover: { what: "soon.discover", stage: 2 }, games: { what: "soon.games", stage: 3 }, mixtape: { what: "soon.mixtape", stage: 4 } } as const;

export function Soon({ page }: { page: keyof typeof INFO }) {
  const { t, n } = useLang();
  const i = INFO[page];
  return <div className="stack"><h1 className="page-title">{t(`tab.${page}`)}</h1><EmptyState icon="🚧" text={`${t("soon.title")}\n${t("soon.body", { what: t(i.what), n: n(i.stage) })}`} /></div>;
}
