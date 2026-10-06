"use client";

import { useState } from "react";

import { EvidenceDrawer } from "@/components/aksi/evidence-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AksiEvent,
  type EventKind,
  type Lang,
  KIND_LABEL,
  formatDate,
  formatFigure,
  formatIdr,
} from "@/lib/aksi";
import { cn } from "@/lib/utils";

const TILES: Record<EventKind, { key: string; label: string }[]> = {
  right_issue: [
    { key: "rights_entitled", label: "Your rights (HMETD)" },
    { key: "cost_to_exercise_all", label: "Cost to exercise all" },
    { key: "terp", label: "TERP (theoretical)" },
    { key: "rights_value_total", label: "Theoretical rights value" },
  ],
  dividend: [
    { key: "gross_dividend", label: "Your gross dividend" },
    { key: "yield_on_cost", label: "Yield on cost" },
    { key: "days_to_cum", label: "Days to cum date" },
  ],
  warrant: [
    { key: "intrinsic_per_warrant", label: "Intrinsic value / warrant" },
    { key: "days_to_deadline", label: "Days to exercise deadline" },
  ],
};

const TIMELINE: Record<EventKind, { key: string; label: string }[]> = {
  right_issue: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "trading_period_start", label: "Rights trading starts" },
    { key: "trading_period_end", label: "Rights deadline" },
  ],
  dividend: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "payment_date", label: "Payment" },
  ],
  warrant: [
    { key: "trading_period_start", label: "Trading starts" },
    { key: "ex_per_start", label: "Exercise starts" },
    { key: "ex_per_end", label: "Exercise ends" },
    { key: "maturity_date", label: "Maturity" },
  ],
};

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function Subline({ event }: { event: AksiEvent }) {
  const price = num(event.row.price);
  const amount = num(event.row.dividend_amount);
  const text =
    event.kind === "right_issue"
      ? `Ratio ${event.row.old_ratio ?? "—"} : ${event.row.new_ratio ?? "—"} · Exercise price ${price !== null ? formatIdr(price, "en") : "—"}`
      : event.kind === "dividend"
        ? `Dividend per share ${amount !== null ? formatIdr(amount, "en") : "—"}`
        : `Exercise price ${price !== null ? formatIdr(price, "en") : "—"}`;
  return <p className="mt-0.5 text-xs text-muted-foreground">{text}</p>;
}

function Countdown({ days }: { days: number | null }) {
  if (days === null) return null;
  return (
    <span className={cn("shrink-0 rounded-md border px-2 py-0.5 font-mono text-xs",
      days <= 2 ? "border-destructive/50 text-destructive" : "border-border text-muted-foreground")}>
      {days <= 0 ? "today" : `in ${days} days`}
    </span>
  );
}

function NumbersGrid({ event }: { event: AksiEvent }) {
  const f = event.figures;
  if (!f) {
    return (
      <div className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-4">
        {TILES[event.kind].map((t) => <Skeleton key={t.key} className="h-14 rounded-lg" />)}
      </div>
    );
  }
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {TILES[event.kind].map((t) => {
          const fig = f[t.key];
          return (
            <div key={t.key} className="rounded-lg border border-border px-3 py-2"
              title={fig ? `${fig.formula}${fig.gap ? ` — ${fig.gap}` : ""}` : undefined}>
              <div className="text-xs text-muted-foreground">{t.label}</div>
              <div className="mt-1 font-mono text-base text-foreground">{formatFigure(fig, "en")}</div>
            </div>
          );
        })}
      </div>
      {event.kind === "right_issue" && f.dilution_if_ignored?.value != null && (
        <p className="text-xs text-muted-foreground">
          If the rights lapse, your ownership falls{" "}
          <span className="font-mono text-foreground">{formatFigure(f.dilution_if_ignored, "en")}</span>.
        </p>
      )}
    </div>
  );
}

function Timeline({ event, asOf }: { event: AksiEvent; asOf: string | null }) {
  const today = asOf ? asOf.slice(0, 10) : null;
  const items = [
    ...TIMELINE[event.kind]
      .map((p) => ({ ...p, date: event.row[p.key] ? String(event.row[p.key]).slice(0, 10) : "", isToday: false }))
      .filter((p) => p.date),
    ...(today ? [{ key: "today", label: "Today", date: today, isToday: true }] : []),
  ].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ol className="flex gap-5 overflow-x-auto px-4 py-3" aria-label="Timeline">
      {items.map((p) => (
        <li key={p.key} className="flex min-w-24 flex-col gap-1">
          <span aria-hidden className={cn("size-2 rounded-full",
            p.isToday ? "bg-primary" : today && p.date <= today ? "bg-muted-foreground" : "border border-muted-foreground")} />
          <span className={cn("text-xs", p.isToday ? "text-foreground" : "text-muted-foreground")}>{p.label}</span>
          <span className="font-mono text-xs">{formatDate(p.date, "en")}</span>
        </li>
      ))}
    </ol>
  );
}

function Scenarios({ event }: { event: AksiEvent }) {
  const f = event.figures;
  if (event.kind !== "right_issue" || !f) return null;
  return (
    <div className="space-y-1.5 px-4 py-3 text-sm text-ink-muted">
      <div className="text-xs text-muted-foreground">Three scenarios (theoretical, before transaction costs):</div>
      <p><span className="text-foreground">Exercise all:</span> pay <span className="font-mono">{formatFigure(f.cost_to_exercise_all, "en")}</span>, ownership unchanged.</p>
      <p><span className="text-foreground">Sell the rights:</span> theoretical value ±<span className="font-mono">{formatFigure(f.rights_value_total, "en")}</span>, ownership falls <span className="font-mono">{formatFigure(f.dilution_if_ignored, "en")}</span>.</p>
      <p><span className="text-foreground">Let lapse:</span> rights expire after <span className="font-mono">{formatFigure(f.deadline, "en")}</span>, theoretical value of <span className="font-mono">{formatFigure(f.rights_value_total, "en")}</span> lost.</p>
    </div>
  );
}

function Context({ event, lang }: { event: AksiEvent; lang: Lang }) {
  if (!event.findings.length) return null;
  return (
    <ul className="space-y-2 px-4 py-3">
      {event.findings.map((f) => (
        <li key={f.id} className="text-sm text-ink-muted">
          {lang === "id" ? f.text_id : f.text_en}{" "}
          <span className="ml-1 whitespace-nowrap rounded border border-border px-1 py-0.5 font-mono text-[11px] text-muted-foreground">
            {f.source_tool.replace(/^sectors_/, "")}
            {f.fetched_at ? ` · ${formatDate(f.fetched_at, lang)}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

function BriefBlock({ event, lang, onLang }: { event: AksiEvent; lang: Lang; onLang: (l: Lang) => void }) {
  const b = event.brief;
  if (!b) {
    return (
      <div className="space-y-2 px-4 py-3">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-full" />
      </div>
    );
  }
  const verify = lang === "id" ? b.verify_id : b.verify_en;
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{lang === "id" ? b.headline_id : b.headline_en}</h3>
        <div className="flex rounded-md border border-border text-xs" role="group" aria-label="Language">
          {(["id", "en"] as const).map((l) => (
            <button key={l} type="button" aria-pressed={lang === l} onClick={() => onLang(l)}
              className={cn("px-2 py-0.5 font-mono uppercase", lang === l ? "bg-secondary text-foreground" : "text-muted-foreground")}>
              {l}
            </button>
          ))}
        </div>
      </div>
      <p className="text-sm leading-6 text-ink-muted">{lang === "id" ? b.summary_id : b.summary_en}</p>
      {verify.length > 0 && (
        <div>
          <div className="text-xs text-muted-foreground">{lang === "id" ? "Yang perlu kamu cek" : "What to verify"}</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
            {verify.map((v) => <li key={v}>{v}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function EventCard({ event, asOf }: { event: AksiEvent; asOf: string | null }) {
  const [lang, setLang] = useState<Lang>("en");
  return (
    <article className="divide-y divide-border rounded-xl border border-border bg-card">
      <header className="flex items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-foreground">{event.symbol}</span>
            <span className="text-sm text-muted-foreground">· {KIND_LABEL[event.kind]}</span>
          </div>
          <Subline event={event} />
        </div>
        <Countdown days={event.urgency} />
      </header>
      <NumbersGrid event={event} />
      <Timeline event={event} asOf={asOf} />
      <Scenarios event={event} />
      <Context event={event} lang={lang} />
      <BriefBlock event={event} lang={lang} onLang={setLang} />
      <footer className="flex items-center justify-between gap-3 px-4 py-2">
        <span className="text-xs text-muted-foreground">Educational information, not investment advice.</span>
        <EvidenceDrawer event={event} />
      </footer>
    </article>
  );
}
