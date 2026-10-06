/* Aksi Korporasi types + formatting. Shapes come from backend/app/aksi —
   keep in sync. Numbers are only formatted here, never computed. */

export type Lang = "id" | "en";

export type Holding = { symbol: string; shares: number; avg_price?: number | null };

export type FigureUnit = "IDR" | "shares" | "rights" | "ratio" | "days" | "date";

export type Figure = {
  key: string;
  value: number | string | null;
  unit: FigureUnit;
  formula: string;
  inputs: Record<string, unknown>;
  gap: string | null;
};

export type Finding = {
  id: string;
  kind: string;
  text_id: string;
  text_en: string;
  values: Record<string, unknown>;
  source_tool: string;
  fetched_at: string | null;
};

export type Brief = {
  headline_id: string;
  headline_en: string;
  summary_id: string;
  summary_en: string;
  verify_id: string[];
  verify_en: string[];
  context_ids: string[];
  gate: { passed: boolean; reasons: string[]; template: boolean };
};

export type EventKind = "right_issue" | "dividend" | "warrant";

export type PublicEvent = {
  event_id: string;
  symbol: string;
  kind: EventKind;
  phase: string;
  shares: number;
  urgency: number | null;
  row: Record<string, string | number | null>;
};

export type AksiEvent = PublicEvent & {
  figures?: Record<string, Figure>;
  findings: Finding[];
  brief?: Brief;
};

export type ReportEvent = {
  event: PublicEvent;
  figures: Record<string, Figure>;
  findings: Finding[];
  brief: Brief;
};

export type Report = {
  id: string;
  mode: "live" | "replay";
  as_of: string;
  status: string;
  holdings_snapshot: Holding[];
  events: ReportEvent[];
  credits_spent: number;
  created_at: string;
  updated_at: string;
};

export type AksiStreamEvent = {
  seq: number;
  type:
    | "started"
    | "step"
    | "tool"
    | "event_found"
    | "numbers"
    | "finding"
    | "brief"
    | "budget"
    | "done"
    | "stopped"
    | "error";
  data: unknown;
};

export const KIND_LABEL: Record<EventKind, string> = {
  right_issue: "Rights issue (HMETD)",
  dividend: "Cash dividend",
  warrant: "Warrant",
};

const MONTHS: Record<Lang, string[]> = {
  id: ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

function nf(lang: Lang, digits: number) {
  return new Intl.NumberFormat(lang === "id" ? "id-ID" : "en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatIdr(v: number, lang: Lang = "id"): string {
  const abs = Math.abs(v);
  const digits = abs < 1000 && !Number.isInteger(abs) ? 2 : 0;
  return `${v < 0 ? "−" : ""}Rp${nf(lang, digits).format(abs)}`;
}

export function formatPct(ratio: number, lang: Lang = "id"): string {
  return `${nf(lang, 2).format(ratio * 100)}%`;
}

export function formatDate(iso: string, lang: Lang = "id"): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[lang][m - 1]} ${y}`;
}

export function formatFigure(f: Figure | undefined, lang: Lang = "id"): string {
  if (!f || f.value === null || f.value === undefined) return "—";
  switch (f.unit) {
    case "IDR":
      return formatIdr(Number(f.value), lang);
    case "ratio":
      return formatPct(Number(f.value), lang);
    case "date":
      return formatDate(String(f.value), lang);
    case "days":
      return lang === "id" ? `${f.value} hari` : `${f.value} days`;
    default:
      return nf(lang, 0).format(Number(f.value));
  }
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
