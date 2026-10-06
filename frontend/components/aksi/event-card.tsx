"use client";

import { EvidenceDrawer } from "@/components/aksi/evidence-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AksiEvent,
  type Lang,
  KIND_LABEL,
  copy,
  formatDate,
  formatFigure,
  formatIdr,
} from "@/lib/aksi";
import { useAksiStore } from "@/lib/stores/aksi";
import { cn } from "@/lib/utils";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function Subline({ event, lang }: { event: AksiEvent; lang: Lang }) {
  const t = copy[lang];
  const price = num(event.row.price);
  const amount = num(event.row.dividend_amount);
  const priceText = price !== null ? formatIdr(price, lang) : "—";
  let text: string;
  if (event.kind === "right_issue") {
    text = `${t.ratio} ${event.row.old_ratio ?? "—"} : ${event.row.new_ratio ?? "—"} · ${t.exercisePrice} ${priceText}`;
  } else if (event.kind === "dividend") {
    const amountText = amount !== null ? formatIdr(amount, lang) : "—";
    text = `${t.dividendPerShare} ${amountText}`;
  } else {
    text = `${t.exercisePrice} ${priceText}`;
  }
  return <p className="mt-0.5 text-xs text-muted-foreground">{text}</p>;
}

function Countdown({ days, lang }: { days: number | null; lang: Lang }) {
  if (days === null) return null;
  const t = copy[lang];
  return (
    <span className={cn("shrink-0 rounded-md border px-2 py-0.5 font-mono text-xs",
      days <= 2 ? "border-destructive/50 text-destructive" : "border-border text-muted-foreground")}>
      {days <= 0 ? t.today : t.inDays(days)}
    </span>
  );
}

function NumbersGrid({ event, lang }: { event: AksiEvent; lang: Lang }) {
  const t = copy[lang];
  const f = event.figures;
  if (!f) {
    return (
      <div className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-4">
        {t.tiles[event.kind].map((tile) => <Skeleton key={tile.key} className="h-14 rounded-lg" />)}
      </div>
    );
  }
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {t.tiles[event.kind].map((tile) => {
          const fig = f[tile.key];
          return (
            <div key={tile.key} className="rounded-lg border border-border px-3 py-2"
              title={fig ? `${fig.formula}${fig.gap ? ` — ${fig.gap}` : ""}` : undefined}>
              <div className="text-xs text-muted-foreground">{tile.label}</div>
              <div className="mt-1 font-mono text-base text-foreground">{formatFigure(fig, lang)}</div>
            </div>
          );
        })}
      </div>
      {event.kind === "right_issue" && f.dilution_if_ignored?.value != null && (
        <p className="text-xs text-muted-foreground">
          {t.dilutionBefore}{" "}
          <span className="font-mono text-foreground">{formatFigure(f.dilution_if_ignored, lang)}</span>
          {t.dilutionAfter}
        </p>
      )}
    </div>
  );
}

function Timeline({ event, asOf, lang }: { event: AksiEvent; asOf: string | null; lang: Lang }) {
  const t = copy[lang];
  const today = asOf ? asOf.slice(0, 10) : null;
  const items = [
    ...t.timelineLabels[event.kind]
      .map((p) => ({ ...p, date: event.row[p.key] ? String(event.row[p.key]).slice(0, 10) : "", isToday: false }))
      .filter((p) => p.date),
    ...(today ? [{ key: "today", label: t.today, date: today, isToday: true }] : []),
  ].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ol className="flex gap-5 overflow-x-auto px-4 py-3" aria-label={t.timelineAria}>
      {items.map((p) => (
        <li key={p.key} className="flex min-w-24 flex-col gap-1">
          <span aria-hidden className={cn("size-2 rounded-full",
            p.isToday ? "bg-primary" : today && p.date <= today ? "bg-muted-foreground" : "border border-muted-foreground")} />
          <span className={cn("text-xs", p.isToday ? "text-foreground" : "text-muted-foreground")}>{p.label}</span>
          <span className="font-mono text-xs">{formatDate(p.date, lang)}</span>
        </li>
      ))}
    </ol>
  );
}

function Scenarios({ event, lang }: { event: AksiEvent; lang: Lang }) {
  const t = copy[lang];
  const f = event.figures;
  if (event.kind !== "right_issue" || !f) return null;
  return (
    <div className="space-y-1.5 px-4 py-3 text-sm text-ink-muted">
      <div className="text-xs text-muted-foreground">{t.scenariosHeading}</div>
      <p><span className="text-foreground">{t.scenarioExercise}:</span> {t.scenarioExerciseRest(formatFigure(f.cost_to_exercise_all, lang))}</p>
      <p><span className="text-foreground">{t.scenarioSell}:</span> {t.scenarioSellRest(formatFigure(f.rights_value_total, lang), formatFigure(f.dilution_if_ignored, lang))}</p>
      <p><span className="text-foreground">{t.scenarioLapse}:</span> {t.scenarioLapseRest(formatFigure(f.deadline, lang), formatFigure(f.rights_value_total, lang))}</p>
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

function BriefBlock({ event, lang }: { event: AksiEvent; lang: Lang }) {
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
      <h3 className="text-sm font-medium">{lang === "id" ? b.headline_id : b.headline_en}</h3>
      <p className="text-sm leading-6 text-ink-muted">{lang === "id" ? b.summary_id : b.summary_en}</p>
      {verify.length > 0 && (
        <div>
          <div className="text-xs text-muted-foreground">{copy[lang].verify}</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-muted">
            {verify.map((v) => <li key={v}>{v}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export function EventCard({ event, asOf }: { event: AksiEvent; asOf: string | null }) {
  const lang = useAksiStore((s) => s.lang);
  const t = copy[lang];
  return (
    <article className="divide-y divide-border rounded-xl border border-border bg-card">
      <header className="flex items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-foreground">{event.symbol}</span>
            <span className="text-sm text-muted-foreground">· {KIND_LABEL[event.kind][lang]}</span>
          </div>
          <Subline event={event} lang={lang} />
        </div>
        <Countdown days={event.urgency} lang={lang} />
      </header>
      <NumbersGrid event={event} lang={lang} />
      <Timeline event={event} asOf={asOf} lang={lang} />
      <Scenarios event={event} lang={lang} />
      <Context event={event} lang={lang} />
      <BriefBlock event={event} lang={lang} />
      <footer className="flex items-center justify-between gap-3 px-4 py-2">
        <span className="text-xs text-muted-foreground">{t.cardDisclaimer}</span>
        <EvidenceDrawer event={event} />
      </footer>
    </article>
  );
}
