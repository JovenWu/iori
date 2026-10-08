"use client";

import { useState } from "react";
import { ChevronDownIcon } from "lucide-react";

import { EvidenceDrawer } from "@/components/aksi/evidence-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AksiEvent,
  type Lang,
  KIND_LABEL,
  copy,
  deadlineOf,
  formatDate,
  formatFigure,
  formatIdr,
  gapText,
  humanizeVars,
  sourceLabel,
} from "@/lib/aksi";
import { useSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function Subline({ event, lang }: { event: AksiEvent; lang: Lang }) {
  const t = copy[lang];
  const row = event.row ?? {};
  const price = num(row.price);
  const amount = num(row.dividend_amount);
  const priceText = price !== null ? formatIdr(price, lang) : "—";
  let text: string;
  if (event.kind === "right_issue") {
    text = `${t.ratio} ${row.old_ratio ?? "—"} : ${row.new_ratio ?? "—"} · ${t.exercisePrice} ${priceText}`;
  } else if (event.kind === "dividend") {
    const amountText = amount !== null ? formatIdr(amount, lang) : "—";
    text = `${t.dividendPerShare} ${amountText}`;
  } else {
    text = `${t.exercisePrice} ${priceText}`;
  }
  return <p className="mt-0.5 text-xs text-muted-foreground">{text}</p>;
}

function DeadlineChip({ event, asOf, replay, lang }: {
  event: AksiEvent; asOf: string | null; replay: boolean; lang: Lang;
}) {
  const deadline = deadlineOf(event, asOf);
  if (!deadline) return null;
  const t = copy[lang];
  const days = event.urgency;
  const soon = days !== null && days <= 2;
  // Replay speaks in absolute dates (relative days would lie about "today");
  // live reads better relative — a past deadline still falls back to the date.
  let text: string;
  if (replay) text = formatDate(deadline, lang);
  else if (days === 0) text = t.today;
  else if (days !== null && days > 0) text = t.inDays(days);
  else text = formatDate(deadline, lang);
  return (
    <span
      aria-label={`${t.deadlineLabel}: ${formatDate(deadline, lang)}`}
      className={cn("shrink-0 rounded-md border px-2 py-0.5 font-mono text-xs",
        soon ? "border-destructive/50 text-destructive" : "border-border text-muted-foreground")}
    >
      {text}
    </span>
  );
}

function NumbersGrid({ event, lang }: { event: AksiEvent; lang: Lang }) {
  const t = copy[lang];
  const f = event.figures;
  // Server kinds outside the copy table degrade to an empty grid, not a crash.
  const tiles = t.tiles[event.kind] ?? [];
  if (!f) {
    return (
      <div className="grid grid-cols-2 gap-3 px-4 py-3 sm:grid-cols-4">
        {tiles.map((tile) => <Skeleton key={tile.key} className="h-14 rounded-lg" />)}
      </div>
    );
  }
  return (
    <div className="space-y-2 px-4 py-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((tile) => {
          const fig = f[tile.key];
          return (
            <div key={tile.key} className="rounded-lg border border-border px-3 py-2"
              title={fig ? `${humanizeVars(fig.formula, lang)}${fig.gap ? ` — ${gapText(fig.gap, lang)}` : ""}` : undefined}>
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
    ...(t.timelineLabels[event.kind] ?? [])
      .map((p) => ({ ...p, date: event.row?.[p.key] ? String(event.row[p.key]).slice(0, 10) : "", isToday: false }))
      .filter((p) => p.date),
    ...(today ? [{ key: "today", label: t.today, date: today, isToday: true }] : []),
  ].sort((a, b) => a.date.localeCompare(b.date));
  // Equal columns on a shared row grid (subgrid): each label owns its whole
  // column and may wrap, while dots, labels and dates stay aligned across.
  return (
    <ol className="grid auto-cols-fr grid-flow-col grid-rows-[auto_auto_auto] gap-y-1 px-4 py-3"
      aria-label={t.timelineAria}>
      {items.map((p, i) => {
        const last = i === items.length - 1;
        return (
          <li key={p.key} className="row-span-3 grid min-w-0 grid-rows-subgrid">
            <div className="flex h-2 items-center">
              <span aria-hidden className={cn("size-2 shrink-0 rounded-full",
                p.isToday ? "bg-primary" : today && p.date <= today ? "bg-muted-foreground" : "border border-muted-foreground")} />
              {!last && <span aria-hidden className="h-px flex-1 bg-border" />}
            </div>
            <span className={cn("min-w-0 pr-3 text-xs break-words hyphens-auto",
              p.isToday ? "text-foreground" : "text-muted-foreground")}>
              {p.label}
            </span>
            <span className="min-w-0 pr-3 font-mono text-xs break-words">
              {formatDate(p.date, lang)}
            </span>
          </li>
        );
      })}
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
  const findings = event.findings ?? [];
  if (!findings.length) return null;
  return (
    <ul className="space-y-2 px-4 py-3">
      {findings.map((f) => (
        <li key={f.id} className="text-sm text-ink-muted">
          {lang === "id" ? f.text_id : f.text_en}{" "}
          <span className="ml-1 whitespace-nowrap rounded border border-border px-1 py-0.5 font-mono text-[11px] text-muted-foreground">
            {sourceLabel(f.source_tool, lang)}
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

export function EventCard({ event, asOf, replay }: {
  event: AksiEvent; asOf: string | null; replay: boolean;
}) {
  const lang = useSettings().settings.language;
  const t = copy[lang];
  const [open, setOpen] = useState(false);
  // An event kind outside the known union has no copy/labels — skip the card
  // rather than crash on KIND_LABEL[event.kind].
  if (!KIND_LABEL[event.kind]) return null;
  return (
    <article className="rounded-xl border border-border bg-card">
      <button
        type="button"
        aria-expanded={open}
        aria-label={t.toggleDetails}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start justify-between gap-3 rounded-xl px-4 py-3 text-left transition-colors hover:bg-secondary/50"
      >
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 font-mono text-sm font-semibold text-foreground">{event.symbol}</span>
            <span className="min-w-0 truncate text-sm text-muted-foreground">
              {KIND_LABEL[event.kind][lang]}
            </span>
          </div>
          <Subline event={event} lang={lang} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <DeadlineChip event={event} asOf={asOf} replay={replay} lang={lang} />
          <ChevronDownIcon
            className={cn("size-4 text-muted-foreground transition-transform duration-200", open && "rotate-180")}
          />
        </div>
      </button>
      {open && (
        <div className="divide-y divide-border border-t border-border">
          <NumbersGrid event={event} lang={lang} />
          <Timeline event={event} asOf={asOf} lang={lang} />
          <Scenarios event={event} lang={lang} />
          <Context event={event} lang={lang} />
          <BriefBlock event={event} lang={lang} />
          <footer className="flex items-center justify-between gap-3 px-4 py-2">
            <span className="text-xs text-muted-foreground">{t.cardDisclaimer}</span>
            <EvidenceDrawer event={event} />
          </footer>
        </div>
      )}
    </article>
  );
}
