"use client";

import { useEffect } from "react";
import { PlayIcon, SquareIcon } from "lucide-react";

import { AgentStatus } from "@/components/agent-status";
import { EventCard } from "@/components/aksi/event-card";
import { HoldingsEditor } from "@/components/aksi/holdings-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { formatDate, todayIso } from "@/lib/aksi";
import { useAksiStore } from "@/lib/stores/aksi";
import { cn } from "@/lib/utils";

const DISCLAIMER =
  "Informasi edukatif, bukan rekomendasi investasi. Verifikasi dengan keterbukaan informasi resmi IDX dan prospektus.";

function ModeToggle() {
  const mode = useAksiStore((s) => s.mode);
  const asOf = useAksiStore((s) => s.asOf);
  const running = useAksiStore((s) => s.running);
  return (
    <div className="flex items-center gap-2">
      <div className="flex rounded-md border border-border text-xs" role="group" aria-label="Mode">
        {(["live", "replay"] as const).map((m) => (
          <button key={m} type="button" disabled={running} aria-pressed={mode === m}
            onClick={() => useAksiStore.getState().setMode(m)}
            className={cn("px-2.5 py-1 transition-colors", mode === m ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground")}>
            {m === "live" ? "Hari ini" : "Replay"}
          </button>
        ))}
      </div>
      {mode === "replay" && (
        <Input type="date" aria-label="Tanggal replay" value={asOf} min="2021-01-01" max={todayIso()}
          disabled={running} className="h-7 w-36 font-mono text-xs"
          onChange={(e) => useAksiStore.getState().setAsOf(e.target.value)} />
      )}
    </div>
  );
}

export function AksiView() {
  const holdings = useAksiStore((s) => s.holdings);
  const holdingsLoaded = useAksiStore((s) => s.holdingsLoaded);
  const holdingsVersion = useAksiStore((s) => s.holdingsVersion);
  const running = useAksiStore((s) => s.running);
  const failed = useAksiStore((s) => s.failed);
  const stopped = useAksiStore((s) => s.stopped);
  const tools = useAksiStore((s) => s.tools);
  const credits = useAksiStore((s) => s.credits);
  const durationMs = useAksiStore((s) => s.durationMs);
  const runStartedAt = useAksiStore((s) => s.runStartedAt);
  const reportId = useAksiStore((s) => s.reportId);
  const reportMode = useAksiStore((s) => s.reportMode);
  const reportAsOf = useAksiStore((s) => s.reportAsOf);
  const order = useAksiStore((s) => s.order);
  const events = useAksiStore((s) => s.events);

  useEffect(() => {
    const store = useAksiStore.getState();
    void store.loadHoldings();
    void store.loadLatest(store.mode);
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <SidebarTrigger />
        <h1 className="text-sm font-medium tracking-tight">Aksi Korporasi</h1>
        <div className="ml-auto flex items-center gap-2">
          <ModeToggle />
          {running ? (
            <Button size="sm" variant="secondary" onClick={() => useAksiStore.getState().stop()}>
              <SquareIcon className="size-3.5" />
              Stop
            </Button>
          ) : (
            <Button size="sm" disabled={!holdings.length} onClick={() => useAksiStore.getState().run()}>
              <PlayIcon className="size-3.5" />
              Cek aksi korporasi
            </Button>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
          {reportMode === "replay" && reportAsOf && (
            <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
              Replay historis — data per <span className="font-mono text-foreground">{formatDate(reportAsOf)}</span>. Bukan data hari ini.
            </div>
          )}

          {holdingsLoaded && <HoldingsEditor key={holdingsVersion} initial={holdings} />}

          {(running || tools.length > 0) && (
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <AgentStatus tools={tools} active={running} failed={failed} stopped={stopped}
                  durationMs={durationMs} runStartedAt={runStartedAt} />
              </div>
              {credits && (
                <span className="shrink-0 pt-0.5 font-mono text-xs text-muted-foreground">
                  credits {credits.used}/{credits.budget}
                </span>
              )}
            </div>
          )}

          {order.map((id) => (
            <EventCard key={id} event={events[id]} asOf={reportAsOf} />
          ))}

          {!running && reportId && order.length === 0 && (
            <p className="rounded-xl border border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
              Tidak ada aksi korporasi untuk sahammu dalam 30 hari terakhir dan 60 hari ke depan
              {reportAsOf ? ` (per ${formatDate(reportAsOf)})` : ""}.
            </p>
          )}

          <p className="text-xs text-muted-foreground">{DISCLAIMER}</p>
        </div>
      </div>
    </div>
  );
}
