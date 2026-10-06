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
    { key: "rights_entitled", label: "HMETD kamu" },
    { key: "cost_to_exercise_all", label: "Dana untuk tebus semua" },
    { key: "terp", label: "TERP (teoretis)" },
    { key: "rights_value_total", label: "Nilai teoretis hak" },
  ],
  dividend: [
    { key: "gross_dividend", label: "Dividen bruto kamu" },
    { key: "yield_on_cost", label: "Yield on cost" },
    { key: "days_to_cum", label: "Menuju tanggal cum" },
  ],
  warrant: [
    { key: "intrinsic_per_warrant", label: "Nilai intrinsik / waran" },
    { key: "days_to_deadline", label: "Menuju batas pelaksanaan" },
  ],
};

const TIMELINE: Record<EventKind, { key: string; label: string }[]> = {
  right_issue: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "trading_period_start", label: "Mulai perdagangan HMETD" },
    { key: "trading_period_end", label: "Batas HMETD" },
  ],
  dividend: [
    { key: "cum_date", label: "Cum" },
    { key: "ex_date", label: "Ex" },
    { key: "recording_date", label: "Recording" },
    { key: "payment_date", label: "Pembayaran" },
  ],
  warrant: [
    { key: "trading_period_start", label: "Mulai perdagangan" },
    { key: "ex_per_start", label: "Mulai pelaksanaan" },
    { key: "ex_per_end", label: "Akhir pelaksanaan" },
    { key: "maturity_date", label: "Jatuh tempo" },
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
      ? `Rasio ${event.row.old_ratio ?? "—"} : ${event.row.new_ratio ?? "—"} · Harga pelaksanaan ${price !== null ? formatIdr(price) : "—"}`
      : event.kind === "dividend"
        ? `Dividen per saham ${amount !== null ? formatIdr(amount) : "—"}`
        : `Harga pelaksanaan ${price !== null ? formatIdr(price) : "—"}`;
  return <p className="mt-0.5 text-xs text-muted-foreground">{text}</p>;
}

function Countdown({ days }: { days: number | null }) {
  if (days === null) return null;
  return (
    <span className={cn("shrink-0 rounded-md border px-2 py-0.5 font-mono text-xs",
      days <= 2 ? "border-destructive/50 text-destructive" : "border-border text-muted-foreground")}>
      {days <= 0 ? "hari ini" : `${days} hari lagi`}
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
              <div className="mt-1 font-mono text-base text-foreground">{formatFigure(fig)}</div>
            </div>
          );
        })}
      </div>
      {event.kind === "right_issue" && f.dilution_if_ignored?.value != null && (
        <p className="text-xs text-muted-foreground">
          Jika HMETD dibiarkan hangus, porsi kepemilikan turun{" "}
          <span className="font-mono text-foreground">{formatFigure(f.dilution_if_ignored)}</span>.
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
    ...(today ? [{ key: "today", label: "Hari ini", date: today, isToday: true }] : []),
  ].sort((a, b) => a.date.localeCompare(b.date));
  return (
    <ol className="flex gap-5 overflow-x-auto px-4 py-3" aria-label="Linimasa">
      {items.map((p) => (
        <li key={p.key} className="flex min-w-24 flex-col gap-1">
          <span aria-hidden className={cn("size-2 rounded-full",
            p.isToday ? "bg-primary" : today && p.date <= today ? "bg-muted-foreground" : "border border-muted-foreground")} />
          <span className={cn("text-xs", p.isToday ? "text-foreground" : "text-muted-foreground")}>{p.label}</span>
          <span className="font-mono text-xs">{formatDate(p.date)}</span>
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
      <div className="text-xs text-muted-foreground">Tiga skenario (teoretis, sebelum biaya transaksi):</div>
      <p><span className="text-foreground">Ditebus semua:</span> bayar <span className="font-mono">{formatFigure(f.cost_to_exercise_all)}</span>, porsi kepemilikan tetap.</p>
      <p><span className="text-foreground">HMETD dijual:</span> nilai teoretis ±<span className="font-mono">{formatFigure(f.rights_value_total)}</span>, porsi turun <span className="font-mono">{formatFigure(f.dilution_if_ignored)}</span>.</p>
      <p><span className="text-foreground">Dibiarkan:</span> hak hangus setelah <span className="font-mono">{formatFigure(f.deadline)}</span>, nilai teoretis hilang <span className="font-mono">{formatFigure(f.rights_value_total)}</span>.</p>
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
        <div className="flex rounded-md border border-border text-xs" role="group" aria-label="Bahasa">
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
  const [lang, setLang] = useState<Lang>("id");
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
        <span className="text-xs text-muted-foreground">Informasi edukatif, bukan rekomendasi investasi.</span>
        <EvidenceDrawer event={event} />
      </footer>
    </article>
  );
}
