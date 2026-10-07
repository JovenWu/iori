"use client";

import { useEffect, useMemo, useState } from "react";
import { id as localeId } from "date-fns/locale";
import { CalendarIcon, PlayIcon, SquareIcon, XIcon } from "lucide-react";

import { AgentStatus } from "@/components/agent-status";
import { EventCard } from "@/components/aksi/event-card";
import { HoldingsEditDialog, HoldingsRail, HoldingsStrip } from "@/components/aksi/holdings-panel";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { copy, formatDate, parseDay, toDayIso, todayIso } from "@/lib/aksi";
import { useSettings } from "@/lib/settings";
import { useAksiStore } from "@/lib/stores/aksi";
import { cn } from "@/lib/utils";

/** "Today" = live mode; the calendar button opens a replay-date picker. */
function ReplayPicker() {
  const mode = useAksiStore((s) => s.mode);
  const asOf = useAksiStore((s) => s.asOf);
  const running = useAksiStore((s) => s.running);
  const [open, setOpen] = useState(false);
  const lang = useSettings().settings.language;
  const t = copy[lang];
  const store = useAksiStore.getState();

  return (
    <div className="flex items-center rounded-md border border-border text-xs" role="group" aria-label="Mode">
      <button
        type="button"
        disabled={running}
        aria-pressed={mode === "live"}
        onClick={() => store.setMode("live")}
        className={cn(
          "px-2.5 py-1 transition-colors",
          mode === "live" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
        )}
      >
        {t.modeToday}
      </button>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={running}
            aria-pressed={mode === "replay"}
            aria-label={t.pickReplayDate}
            className={cn(
              "flex items-center gap-1.5 border-l border-border px-2.5 py-1 transition-colors",
              mode === "replay" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <CalendarIcon className="size-3.5" />
            {mode === "replay" ? (
              <span className="whitespace-nowrap">{formatDate(asOf, lang)}</span>
            ) : (
              <span className="hidden whitespace-nowrap sm:inline">{t.modeReplay}</span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto p-0">
          <Calendar
            mode="single"
            captionLayout="dropdown"
            selected={parseDay(asOf)}
            defaultMonth={parseDay(asOf)}
            startMonth={new Date(2021, 0)}
            endMonth={parseDay(todayIso())}
            disabled={[{ before: new Date(2021, 0, 1) }, { after: parseDay(todayIso()) }]}
            locale={lang === "id" ? localeId : undefined}
            onSelect={(d) => {
              if (!d) return;
              const iso = toDayIso(d);
              store.setAsOf(iso);
              // Backend treats as_of >= today as a live run — mirror that here.
              store.setMode(iso < todayIso() ? "replay" : "live");
              setOpen(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}

export function AksiView() {
  const holdings = useAksiStore((s) => s.holdings);
  const holdingsLoaded = useAksiStore((s) => s.holdingsLoaded);
  const running = useAksiStore((s) => s.running);
  const failed = useAksiStore((s) => s.failed);
  const stopped = useAksiStore((s) => s.stopped);
  const tools = useAksiStore((s) => s.tools);
  const durationMs = useAksiStore((s) => s.durationMs);
  const runStartedAt = useAksiStore((s) => s.runStartedAt);
  const reportId = useAksiStore((s) => s.reportId);
  const reportMode = useAksiStore((s) => s.reportMode);
  const reportAsOf = useAksiStore((s) => s.reportAsOf);
  const order = useAksiStore((s) => s.order);
  const events = useAksiStore((s) => s.events);
  const mode = useAksiStore((s) => s.mode);
  const asOf = useAksiStore((s) => s.asOf);
  const lang = useSettings().settings.language;
  const t = copy[lang];

  const [filter, setFilter] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    const store = useAksiStore.getState();
    void store.loadHoldings();
    // A check may still be running server-side after a refresh — its replay
    // buffer rebuilds the board; otherwise show the latest persisted report.
    void store.reattach().then((attached) => {
      if (!attached) void store.loadLatest(store.mode);
    });
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const id of order) {
      const s = events[id]?.symbol;
      if (s) c[s] = (c[s] ?? 0) + 1;
    }
    return c;
  }, [order, events]);

  const groups = useMemo(() => {
    const soon: string[] = [];
    const upcoming: string[] = [];
    const undated: string[] = [];
    for (const id of order) {
      const e = events[id];
      if (!e || (filter && e.symbol !== filter)) continue;
      if (e.urgency == null) undated.push(id);
      else if (e.urgency <= 7) soon.push(id);
      else upcoming.push(id);
    }
    return [
      { key: "soon", label: t.actSoon, ids: soon },
      { key: "upcoming", label: t.upcoming, ids: upcoming },
      { key: "undated", label: t.noDeadline, ids: undated },
    ].filter((g) => g.ids.length > 0);
  }, [order, events, filter, t]);

  const emptyText = useMemo(() => {
    if (running || groups.length > 0) return null;
    if (order.length === 0) {
      if (reportId)
        return `${t.empty}${reportAsOf ? ` (${t.asOf} ${formatDate(reportAsOf, lang)})` : ""}.`;
      // Replay picked but no report exists for that date yet.
      if (mode === "replay") return t.noReplayFor(formatDate(asOf, lang));
      return null;
    }
    return filter ? t.emptyForSymbol(filter) : null;
  }, [running, groups, order, reportId, reportAsOf, mode, asOf, filter, t, lang]);

  const panelProps = {
    holdings,
    loaded: holdingsLoaded,
    counts,
    selected: filter,
    onSelect: setFilter,
    onEdit: () => setEditing(true),
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <SidebarTrigger />
        <h1 className="min-w-0 truncate text-sm font-medium tracking-tight">{t.title}</h1>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <ReplayPicker />
          {running ? (
            <Button size="sm" variant="secondary" aria-label={t.stop}
              onClick={() => useAksiStore.getState().stop()}>
              <SquareIcon className="size-3.5" />
              <span className="hidden sm:inline">{t.stop}</span>
            </Button>
          ) : (
            <Button size="sm" aria-label={t.check} disabled={!holdings.length}
              onClick={() => useAksiStore.getState().run()}>
              <PlayIcon className="size-3.5" />
              <span className="hidden sm:inline">{t.check}</span>
            </Button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <HoldingsRail {...panelProps} />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
              <HoldingsStrip {...panelProps} />

            {reportMode === "replay" && reportAsOf && (
              <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
                {t.replayBannerPre} <span className="font-mono text-foreground">{formatDate(reportAsOf, lang)}</span>. {t.replayBannerPost}
              </div>
            )}

            {(running || tools.length > 0) && (
              <AgentStatus tools={tools} active={running} failed={failed} stopped={stopped}
                durationMs={durationMs} runStartedAt={runStartedAt} />
            )}

            {filter && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>{t.filteredTo}</span>
                <button
                  type="button"
                  aria-label={t.clearFilter}
                  onClick={() => setFilter(null)}
                  className="flex items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 font-mono text-foreground transition-colors hover:bg-primary/20"
                >
                  {filter}
                  <XIcon className="size-3" />
                </button>
              </div>
            )}

            {groups.map((g) => (
              <section key={g.key} className="flex flex-col gap-2">
                <h2 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  {g.label}
                  <span className="font-mono text-[11px]">{g.ids.length}</span>
                  <span aria-hidden className="h-px flex-1 bg-border" />
                </h2>
                {g.ids.map((id) => (
                  <EventCard key={id} event={events[id]} asOf={reportAsOf}
                    replay={reportMode === "replay"} />
                ))}
              </section>
            ))}

            {emptyText && (
              <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
                {emptyText}
              </p>
            )}
            </div>
          </div>

          <footer className="shrink-0 px-4 py-2 text-center">
            <p className="text-[11px] text-muted-foreground">{t.disclaimer}</p>
          </footer>
        </div>
      </div>

      <HoldingsEditDialog holdings={holdings} open={editing} onOpenChange={setEditing} />
    </div>
  );
}
